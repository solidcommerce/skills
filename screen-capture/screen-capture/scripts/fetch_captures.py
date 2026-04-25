#!/usr/bin/env python3
"""Fetch the latest screen captures from the VCapture control-plane API."""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import x25519
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    CRYPTO_IMPORT_ERROR = None
except ImportError as exc:
    hashes = None
    serialization = None
    x25519 = None
    AESGCM = None
    HKDF = None
    CRYPTO_IMPORT_ERROR = exc

OUTPUT_DIR = Path('/tmp/screen-captures')
DEFAULT_API_BASE_URL = 'https://vcapture.takeoffcommerce.com'
DEFAULT_STALE_THRESHOLD = 60
DEFAULT_COUNT = 2
DEFAULT_FETCH_LIMIT = 20
DEFAULT_STATE_DIR = Path.home() / '.config' / 'vcapture'
DEFAULT_ACCESS_TOKEN_FILE = DEFAULT_STATE_DIR / 'skill-token'
DEFAULT_ACCESS_TOKEN_METADATA_FILE = DEFAULT_STATE_DIR / 'skill-token.json'
DEFAULT_CONTENT_KEY_FILE = DEFAULT_STATE_DIR / 'content-key.json'
DEFAULT_LINK_SESSION_FILE = DEFAULT_STATE_DIR / 'skill-link.json'


class ApiError(RuntimeError):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = int(status_code)


class AuthorizationRequired(RuntimeError):
    def __init__(self, payload):
        super().__init__(payload.get('message') or 'VCapture authorization is required.')
        self.payload = payload


def trim_trailing_slash(value):
    return str(value or '').rstrip('/')


def get_env(*names):
    for name in names:
        value = os.environ.get(name)
        if value and str(value).strip():
            return str(value).strip()
    return ''


def require_crypto():
    if CRYPTO_IMPORT_ERROR is not None:
        raise RuntimeError(
            "VCapture end-to-end encryption requires the Python 'cryptography' package. "
            "Install it with `pip install -r requirements.txt` before using this skill."
        )


def to_json_bytes(payload):
    return json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def b64url_encode(value):
    import base64
    return base64.urlsafe_b64encode(bytes(value)).rstrip(b'=').decode('ascii')


def b64url_decode(value, label='value'):
    import base64
    text = str(value or '').strip()
    if not text:
        raise RuntimeError(f'{label} is required.')
    padding = '=' * ((4 - len(text) % 4) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except Exception as exc:
        raise RuntimeError(f'{label} is not valid base64url.') from exc


def ensure_state_dir():
    DEFAULT_STATE_DIR.mkdir(parents=True, exist_ok=True)


def read_text_file(path_value):
    path = Path(path_value).expanduser()
    if not path.is_file():
        raise RuntimeError(f'VCapture token file was not found: {path}')
    return path.read_text(encoding='utf-8').strip()


def read_json_file(path):
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def write_json_file(path, payload):
    ensure_state_dir()
    path.write_text(f'{json.dumps(payload, indent=2)}\n', encoding='utf-8')


def delete_file(path):
    try:
        path.unlink()
    except FileNotFoundError:
        return


def get_access_token(cli_value, cli_file_value):
    if cli_value:
        return str(cli_value).strip(), 'cli'
    file_value = cli_file_value or get_env('VCAPTURE_ACCESS_TOKEN_FILE', 'AVCAPTURE_ACCESS_TOKEN_FILE')
    if file_value:
        return read_text_file(file_value), 'file'
    token = get_env('VCAPTURE_ACCESS_TOKEN', 'AVCAPTURE_ACCESS_TOKEN')
    if token:
        return str(token).strip(), 'env'
    if DEFAULT_ACCESS_TOKEN_FILE.is_file():
        return read_text_file(DEFAULT_ACCESS_TOKEN_FILE), 'saved'
    return '', 'none'


def get_api_base_url(cli_value):
    value = cli_value or get_env('VCAPTURE_API_BASE_URL', 'AVCAPTURE_API_BASE_URL')
    return trim_trailing_slash(value or DEFAULT_API_BASE_URL)


def get_default_source_id(cli_value):
    value = cli_value or get_env('VCAPTURE_SOURCE_ID', 'AVCAPTURE_SOURCE_ID')
    return str(value or '').strip()


def parse_iso_datetime(value):
    if not value:
        return None
    text = str(value).strip()
    if text.endswith('Z'):
        text = f"{text[:-1]}+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def read_error_message(exc):
    try:
        body = exc.read().decode('utf-8')
    except Exception:
        body = ''
    if not body:
        return exc.reason or 'request failed'
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(parsed, dict):
        return parsed.get('error') or parsed.get('message') or body.strip()
    return body.strip()


def json_request(method, url, access_token='', payload=None, timeout=30):
    headers = {'Accept': 'application/json'}
    data = None
    if access_token:
        headers['Authorization'] = f'Bearer {access_token}'
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    elif method.upper() == 'POST':
        data = b''

    req = request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode('utf-8')
            return json.loads(body) if body else {}
    except error.HTTPError as exc:
        raise ApiError(exc.code, read_error_message(exc)) from exc
    except error.URLError as exc:
        raise RuntimeError(f'Failed to reach VCapture API: {exc.reason}') from exc


def download_bytes(url, timeout=30):
    req = request.Request(url, headers={'Accept': 'image/*, application/octet-stream'})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read(), response.headers.get('Content-Type', '')
    except error.HTTPError as exc:
        raise ApiError(exc.code, read_error_message(exc)) from exc
    except error.URLError as exc:
        raise RuntimeError(f'Failed to download capture: {exc.reason}') from exc


def preferred_extension(read_url, content_type):
    parsed = parse.urlparse(read_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}:
        return '.jpg' if suffix == '.jpeg' else suffix
    normalized = str(content_type or '').split(';', 1)[0].strip().lower()
    if normalized == 'image/png':
        return '.png'
    if normalized == 'image/webp':
        return '.webp'
    if normalized == 'image/bmp':
        return '.bmp'
    return '.jpg'


def build_capture_aad(capture):
    return to_json_bytes({
        'v': 1,
        'capturedAt': str(capture.get('capturedAt') or ''),
        'sourceType': str(capture.get('sourceType') or ''),
        'sourceId': str(capture.get('sourceId') or ''),
    })


def decrypt_capture_bytes(ciphertext, capture):
    encryption = capture.get('encryption')
    if not isinstance(encryption, dict) or not encryption.get('scheme'):
        return ciphertext, ''

    require_crypto()
    content_key = load_content_key()
    if not content_key:
        raise RuntimeError('Encrypted captures are available but this skill does not have a content key yet. Reconnect VCapture.')

    key_version = max(1, int(encryption.get('keyVersion') or 1))
    if key_version != content_key['keyVersion']:
        raise RuntimeError('VCapture content key version mismatch. Reconnect the skill to refresh its encryption key.')

    aes = AESGCM(content_key['keyBytes'])
    plaintext = aes.decrypt(
        b64url_decode(encryption.get('iv'), 'Capture IV'),
        bytes(ciphertext) + b64url_decode(encryption.get('tag'), 'Capture tag'),
        build_capture_aad(capture),
    )
    return plaintext, str(encryption.get('plaintextType') or 'image/jpeg')


def save_access_token(result, api_base_url):
    token = str(result.get('token') or '').strip()
    if not token:
        raise RuntimeError('VCapture API did not return a skill token.')
    ensure_state_dir()
    DEFAULT_ACCESS_TOKEN_FILE.write_text(f'{token}\n', encoding='utf-8')
    write_json_file(DEFAULT_ACCESS_TOKEN_METADATA_FILE, {
      'apiBaseUrl': api_base_url,
      'tokenType': str(result.get('tokenType') or 'Bearer'),
      'issuedAt': str(result.get('createdAt') or datetime.now(timezone.utc).isoformat()),
      'expiresAt': str(result.get('expiresAt') or ''),
      'permissions': list(result.get('permissions') or []),
      'label': str(result.get('label') or 'VCapture screen-capture skill'),
    })
    return token


def delete_saved_access_token():
    delete_file(DEFAULT_ACCESS_TOKEN_FILE)
    delete_file(DEFAULT_ACCESS_TOKEN_METADATA_FILE)


def generate_skill_key_pair():
    require_crypto()
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    return {
        'privateKey': b64url_encode(private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )),
        'publicKey': b64url_encode(public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )),
        'keyWrapAlgorithm': 'x25519-hkdf-sha256-aes-256-gcm-v1',
    }


def save_content_key(content_key, api_base_url):
    ensure_state_dir()
    payload = {
        **content_key,
        'apiBaseUrl': api_base_url,
    }
    DEFAULT_CONTENT_KEY_FILE.write_text(f'{json.dumps(payload, indent=2)}\n', encoding='utf-8')
    return payload


def load_content_key():
    payload = read_json_file(DEFAULT_CONTENT_KEY_FILE)
    if not isinstance(payload, dict):
        return None
    key = str(payload.get('key') or '').strip()
    if not key:
        return None
    try:
        key_bytes = b64url_decode(key, 'Saved content key')
    except RuntimeError:
        return None
    if len(key_bytes) != 32:
        return None
    return {
        'key': key,
        'keyBytes': key_bytes,
        'keyVersion': max(1, int(payload.get('keyVersion') or 1)),
        'algorithm': str(payload.get('algorithm') or 'aes-256-gcm-v1').strip() or 'aes-256-gcm-v1',
        'updatedAt': str(payload.get('updatedAt') or ''),
        'apiBaseUrl': str(payload.get('apiBaseUrl') or ''),
    }


def unwrap_content_key(approved_result, pending):
    require_crypto()
    wrapped = approved_result.get('wrappedContentKey')
    if not isinstance(wrapped, dict):
        raise RuntimeError('VCapture approval response did not include a wrapped content key.')

    link_id = str(pending.get('linkId') or '').strip()
    private_key_b64 = str(pending.get('privateKey') or '').strip()
    if not link_id or not private_key_b64:
        raise RuntimeError('The pending VCapture link is missing its private key material. Start the link again.')

    private_key = x25519.X25519PrivateKey.from_private_bytes(b64url_decode(private_key_b64, 'Skill private key'))
    sender_public_key = x25519.X25519PublicKey.from_public_bytes(
        b64url_decode(wrapped.get('senderPublicKey'), 'Wrapped sender public key')
    )
    shared_secret = private_key.exchange(sender_public_key)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b64url_decode(wrapped.get('salt'), 'Wrapped key salt'),
        info=to_json_bytes({
            'v': 1,
            'purpose': 'vcapture-content-key-wrap',
            'linkId': link_id,
        }),
    )
    wrapping_key = hkdf.derive(shared_secret)
    aes = AESGCM(wrapping_key)
    plaintext = aes.decrypt(
        b64url_decode(wrapped.get('iv'), 'Wrapped key IV'),
        b64url_decode(wrapped.get('ciphertext'), 'Wrapped key ciphertext') + b64url_decode(wrapped.get('tag'), 'Wrapped key tag'),
        to_json_bytes({
            'v': 1,
            'purpose': 'vcapture-content-key-wrap',
            'keyVersion': max(1, int(wrapped.get('contentKeyVersion') or 1)),
        }),
    )
    if len(plaintext) != 32:
        raise RuntimeError('VCapture returned an invalid content key length.')
    return {
        'key': b64url_encode(plaintext),
        'keyVersion': max(1, int(wrapped.get('contentKeyVersion') or 1)),
        'algorithm': str(wrapped.get('contentKeyAlgorithm') or 'aes-256-gcm-v1').strip() or 'aes-256-gcm-v1',
        'updatedAt': datetime.now(timezone.utc).isoformat(),
    }


def load_pending_link():
    payload = read_json_file(DEFAULT_LINK_SESSION_FILE)
    if not isinstance(payload, dict):
        return None
    if not str(payload.get('linkId') or '').strip() or not str(payload.get('secret') or '').strip():
        clear_pending_link()
        return None
    if not str(payload.get('privateKey') or '').strip() or not str(payload.get('publicKey') or '').strip():
        clear_pending_link()
        return None
    expires_at = parse_iso_datetime(payload.get('expiresAt'))
    if expires_at and expires_at <= datetime.now(timezone.utc):
        clear_pending_link()
        return None
    return payload


def save_pending_link(payload):
    write_json_file(DEFAULT_LINK_SESSION_FILE, payload)


def clear_pending_link():
    delete_file(DEFAULT_LINK_SESSION_FILE)


def build_authorization_payload(payload, resumed=False):
    authorize_url = str(payload.get('authorizeUrl') or '')
    link_code = str(payload.get('userCode') or '')
    expires_at = str(payload.get('expiresAt') or '')
    status_value = str(payload.get('status') or '').strip()
    if status_value == 'awaiting_device':
        message = 'Account approved. Keep VCapture running for a few seconds, then retry the screen-capture request.'
    elif resumed:
        message = 'Finish the open VCapture connection flow, then retry the screen-capture request.'
    else:
        message = 'Open authorizeUrl to connect VCapture, then retry the screen-capture request.'
    return {
        'status': 'authorization_required',
        'message': message,
        'authorize_url': authorize_url,
        'link_code': link_code,
        'expires_at': expires_at,
        'poll_after_seconds': 5,
    }


def start_link_session(api_base_url):
    skill_keys = generate_skill_key_pair()
    response = json_request('POST', f'{api_base_url}/v1/skill/link/start', payload={
        'label': 'VCapture screen-capture skill',
        'publicKey': skill_keys['publicKey'],
        'keyWrapAlgorithm': skill_keys['keyWrapAlgorithm'],
    })
    if not isinstance(response, dict) or not response.get('linkId') or not response.get('secret'):
        raise RuntimeError('VCapture API returned an invalid skill-link response.')
    pending = {
        **response,
        **skill_keys,
    }
    save_pending_link(pending)
    return pending


def poll_link_session(api_base_url, pending):
    link_id = str(pending.get('linkId') or '').strip()
    secret = str(pending.get('secret') or '').strip()
    if not link_id or not secret:
        clear_pending_link()
        return None
    url = (
        f"{api_base_url}/v1/skill/link/poll?"
        f"{parse.urlencode({'link_id': link_id, 'secret': secret})}"
    )
    response = json_request('GET', url)
    if not isinstance(response, dict):
        raise RuntimeError('VCapture API returned an invalid skill-link poll response.')
    if response.get('status') == 'approved':
        clear_pending_link()
        return response
    return response


def wait_for_pending_link(api_base_url, pending, wait_seconds):
    deadline = time.time() + max(0, int(wait_seconds))
    latest = pending
    first_attempt = True
    while first_attempt or time.time() < deadline:
        first_attempt = False
        remaining = int(max(0, deadline - time.time()))
        poll = poll_link_session(api_base_url, latest)
        if poll and poll.get('status') == 'approved':
            return poll
        latest = {
            **latest,
            **(poll or {})
        }
        if time.time() >= deadline:
            break
        sleep_for = min(5, max(1, remaining))
        time.sleep(sleep_for)
    return latest


def ensure_skill_access(api_base_url, access_token, token_source, wait_for_link_seconds):
    if access_token:
        return access_token

    pending = load_pending_link()
    if pending:
        result = wait_for_pending_link(api_base_url, pending, wait_for_link_seconds)
        if result and result.get('status') == 'approved':
            save_content_key(unwrap_content_key(result, pending), api_base_url)
            clear_pending_link()
            return save_access_token(result, api_base_url)
        raise AuthorizationRequired(build_authorization_payload({
            **pending,
            **(result or {})
        }, resumed=True))

    pending = start_link_session(api_base_url)
    if wait_for_link_seconds > 0:
        result = wait_for_pending_link(api_base_url, pending, wait_for_link_seconds)
        if result and result.get('status') == 'approved':
            save_content_key(unwrap_content_key(result, pending), api_base_url)
            clear_pending_link()
            return save_access_token(result, api_base_url)
    raise AuthorizationRequired(build_authorization_payload(pending, resumed=False))


def list_captures(api_base_url, access_token, limit, source_id):
    query = {'limit': str(limit)}
    if source_id:
        query['sourceId'] = source_id
    url = f"{api_base_url}/v1/skill/captures?{parse.urlencode(query)}"
    response = json_request('GET', url, access_token=access_token)
    captures = response.get('captures')
    if not isinstance(captures, list):
        raise RuntimeError('VCapture API returned an invalid captures payload.')
    return captures


def choose_captures(captures, count, requested_source_id=''):
    ordered = sorted(
        captures,
        key=lambda entry: parse_iso_datetime(entry.get('capturedAt')) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    if not ordered:
        return [], requested_source_id or None

    if requested_source_id:
        filtered = [entry for entry in ordered if str(entry.get('sourceId') or '') == requested_source_id]
        return filtered[:count], requested_source_id

    most_recent_source_id = str(ordered[0].get('sourceId') or '').strip()
    if most_recent_source_id:
        same_source = [entry for entry in ordered if str(entry.get('sourceId') or '') == most_recent_source_id]
        if same_source:
            return same_source[:count], most_recent_source_id

    return ordered[:count], most_recent_source_id or None


def issue_read_url(api_base_url, access_token, capture_id):
    url = f"{api_base_url}/v1/skill/captures/{parse.quote(str(capture_id), safe='')}/read-url"
    response = json_request('POST', url, access_token=access_token)
    if not isinstance(response, dict) or not response.get('url'):
        raise RuntimeError('VCapture API did not return a read URL.')
    return response


def prepare_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for pattern in ('capture_*.jpg', 'capture_*.png', 'capture_*.webp', 'capture_*.bmp'):
        for old_file in OUTPUT_DIR.glob(pattern):
            old_file.unlink()


def fetch_recent_captures(api_base_url, access_token, count, stale_threshold, source_id):
    captures = list_captures(api_base_url, access_token, max(DEFAULT_FETCH_LIMIT, count * 8), source_id)
    selected, selected_source_id = choose_captures(captures, count, source_id)
    if not selected:
        raise RuntimeError('No captures found in VCapture. Please verify VCapture is running and capturing.')

    prepare_output_dir()
    now = datetime.now(timezone.utc)
    labels = ['latest', 'previous', 'third', 'fourth', 'fifth']
    downloaded = []

    for index, capture in enumerate(selected):
        label = labels[index] if index < len(labels) else f'capture_{index}'
        capture_id = capture.get('captureId')
        read_url_response = issue_read_url(api_base_url, access_token, capture_id)
        encryption = capture.get('encryption') if isinstance(capture.get('encryption'), dict) else {}
        plaintext_type_hint = str(encryption.get('plaintextType') or '')
        extension = preferred_extension(read_url_response['url'], plaintext_type_hint)
        destination = OUTPUT_DIR / f'capture_{label}{extension}'
        downloaded_bytes, content_type = download_bytes(read_url_response['url'])
        plaintext_bytes, plaintext_type = decrypt_capture_bytes(downloaded_bytes, capture)
        destination.write_bytes(plaintext_bytes)
        actual_extension = preferred_extension(read_url_response['url'], plaintext_type or plaintext_type_hint or content_type)
        if actual_extension != destination.suffix:
            corrected_destination = destination.with_suffix(actual_extension)
            destination.rename(corrected_destination)
            destination = corrected_destination

        captured_at = parse_iso_datetime(capture.get('capturedAt'))
        age_seconds = int((now - captured_at).total_seconds()) if captured_at else None
        downloaded.append({
            'path': str(destination),
            'capture_id': str(capture_id or ''),
            'timestamp': captured_at.isoformat() if captured_at else capture.get('capturedAt') or 'unknown',
            'age_seconds': age_seconds,
            'source_id': str(capture.get('sourceId') or ''),
            'source_name': str(capture.get('sourceName') or ''),
            'read_url_expires_at': str(read_url_response.get('expiresAt') or ''),
        })

    latest_age = downloaded[0].get('age_seconds')
    stale = latest_age is not None and latest_age > stale_threshold
    result = {
        'status': 'ok',
        'captures': downloaded,
        'selected_source_id': selected_source_id,
        'stale': stale,
    }
    if stale:
        result['stale_message'] = (
            f'Latest capture is {latest_age} seconds old (threshold: {stale_threshold}s). '
            'VCapture may not be running or capturing.'
        )
    return result


def main():
    parser = argparse.ArgumentParser(description='Fetch latest screen captures from the VCapture API')
    parser.add_argument('--count', type=int, default=DEFAULT_COUNT, help='Number of captures to fetch (default: 2)')
    parser.add_argument('--stale-threshold', type=int, default=DEFAULT_STALE_THRESHOLD, help='Seconds before captures are considered stale (default: 60)')
    parser.add_argument('--api-base-url', default='', help='Override the VCapture API base URL')
    parser.add_argument('--access-token', default='', help='VCapture bearer token with captures:read')
    parser.add_argument('--access-token-file', default='', help='Path to a file containing the VCapture bearer token')
    parser.add_argument('--source-id', default='', help='Optional sourceId to restrict captures to one source')
    parser.add_argument('--wait-for-link', type=int, default=0, help='Seconds to wait for hosted account-link completion before returning authorization_required')
    args = parser.parse_args()

    api_base_url = get_api_base_url(args.api_base_url)
    source_id = get_default_source_id(args.source_id)
    count = max(1, min(10, int(args.count or DEFAULT_COUNT)))
    stale_threshold = max(1, int(args.stale_threshold or DEFAULT_STALE_THRESHOLD))

    access_token, token_source = get_access_token(args.access_token, args.access_token_file)

    try:
        access_token = ensure_skill_access(api_base_url, access_token, token_source, args.wait_for_link)
        try:
            result = fetch_recent_captures(api_base_url, access_token, count, stale_threshold, source_id)
        except ApiError as exc:
            if exc.status_code in (401, 403) and token_source == 'saved':
                delete_saved_access_token()
                access_token = ensure_skill_access(api_base_url, '', 'none', args.wait_for_link)
                result = fetch_recent_captures(api_base_url, access_token, count, stale_threshold, source_id)
            else:
                raise
        print(json.dumps(result, indent=2))
    except AuthorizationRequired as exc:
        print(json.dumps(exc.payload, indent=2))
        sys.exit(2)
    except ApiError as exc:
        print(json.dumps({
            'status': 'error',
            'message': f'VCapture API {exc.status_code}: {exc}',
        }))
        sys.exit(1)
    except Exception as exc:
        print(json.dumps({
            'status': 'error',
            'message': str(exc),
        }))
        sys.exit(1)


if __name__ == '__main__':
    main()
