---
name: screen-capture
description: "View the user's screen by fetching recent screen captures through the VCapture control-plane API. Use this skill whenever the user asks you to look at their screen, see what's happening, check a visual element, or references something visible on their display. Also trigger when the user mentions 'the error on screen', 'that dialog box', 'what I'm looking at', 'my screen', 'can you see', or any context where seeing the user's current screen state would help you assist them. This skill is your eyes and should be used whenever fresh visual context from VCapture would improve the response."
---

# Screen Capture Viewer

This skill lets you see what is on the user's screen by fetching the latest VCapture images through the hosted VCapture control-plane API. A separate VCapture desktop app runs on the user's machine, captures screenshots every ~2 seconds, encrypts them locally, uploads the ciphertext to private storage, and the skill decrypts them locally after the hosted account-link flow completes.

Do not read Azure Blob Storage directly. Do not ask for storage account keys or connection strings.

## How it works

1. Run the bundled fetch script.
2. If the skill is not linked yet, the script creates a hosted account-link session and returns a browser URL plus a short code.
3. The user opens that hosted URL and signs in with Google, Microsoft, or email/password.
4. The next script run polls the hosted link session, receives a read-only skill token plus a wrapped content key, unwraps the content key locally on the skill machine, and continues.
5. The script calls the VCapture API to list recent captures and request short-lived read URLs.
6. The script downloads the encrypted blobs, decrypts them locally, and saves the images to `/tmp/screen-captures/`.

## Required auth

Primary production flow:

- hosted account-link through the VCapture control plane

Optional support overrides:

- `VCAPTURE_ACCESS_TOKEN`
- `AVCAPTURE_ACCESS_TOKEN`
- `VCAPTURE_ACCESS_TOKEN_FILE`
- `AVCAPTURE_ACCESS_TOKEN_FILE`
- `--access-token <token>`
- `--access-token-file <path>`

Default local state on the skill machine:

- saved token: `~/.config/vcapture/skill-token`
- saved token metadata: `~/.config/vcapture/skill-token.json`
- saved content key: `~/.config/vcapture/content-key.json`
- pending hosted link session: `~/.config/vcapture/skill-link.json`

Python dependency:

- `pip install -r requirements.txt`

## Step-by-step usage

### 1. Fetch the latest captures

Run:

```bash
python3 scripts/fetch_captures.py
```

### 2. If the script says authorization is required

The script will output JSON like:

```json
{
  "status": "authorization_required",
  "message": "Open authorizeUrl to connect VCapture, then retry the screen-capture request.",
  "authorize_url": "https://vcapture.takeoffcommerce.com/skill/connect?link_id=...",
  "link_code": "ABCD1234",
  "expires_at": "2026-04-23T03:45:00.000Z",
  "poll_after_seconds": 5
}
```

Tell the user to open `authorize_url`, sign in to VCapture, and complete the hosted connection page.

If the flow says the account is approved but the skill is still waiting, keep the VCapture desktop app running for a few seconds and rerun the script. The desktop app finishes the secure key wrap needed for end-to-end decryption.

Then rerun:

```bash
python3 scripts/fetch_captures.py
```

Once linked, the script stores a read-only token and the wrapped/decrypted content key on the skill machine. Later runs should work without repeating the browser flow until the token expires, is revoked, or the content key is refreshed.

### 3. Check successful output

The script outputs JSON like:

```json
{
  "status": "ok",
  "captures": [
    {
      "path": "/tmp/screen-captures/capture_latest.jpg",
      "capture_id": "...",
      "timestamp": "2026-04-22T05:58:04.835000+00:00",
      "age_seconds": 4,
      "source_id": "screen:0:0",
      "source_name": "Entire screen"
    },
    {
      "path": "/tmp/screen-captures/capture_previous.jpg",
      "capture_id": "...",
      "timestamp": "2026-04-22T05:58:02.812000+00:00",
      "age_seconds": 6,
      "source_id": "screen:0:0",
      "source_name": "Entire screen"
    }
  ],
  "selected_source_id": "screen:0:0",
  "stale": false
}
```

### 4. Handle staleness or auth failures

- If `status` is `"error"`, report the error clearly.
- If `status` is `"authorization_required"`, ask the user to complete the hosted `authorize_url`.
- If `status` is `"error"` and the message mentions `401`, the saved skill token is expired, revoked, or invalid. Rerun the script to start a fresh hosted link flow.
- If `status` is `"error"` and the message mentions `403` or `captures:read`, the stored token is wrong for this skill and the user should reconnect.
- If `stale` is `true`, tell the user:
  > "The screen captures appear to be stale. Please make sure VCapture is running and still capturing on your machine."

### 5. View the captures

Read the downloaded images:

- `/tmp/screen-captures/capture_latest.jpg`
- `/tmp/screen-captures/capture_previous.jpg`

The latest capture shows the current state. The previous capture provides motion/change context.

### 6. Describe what you see

After viewing the images, describe the UI, error, or state that matters to the user's request.

## Troubleshooting

| Problem | Likely cause | What to tell the user |
|---------|--------------|-----------------------|
| `authorization_required` | The skill is not linked yet | Ask the user to open the hosted `authorize_url` and sign in |
| `authorization_required` after account approval | The desktop app has not finished the encrypted key handoff yet | Ask the user to keep VCapture running for a few seconds, then retry |
| `401 Unauthorized` | Saved token expired, revoked, or invalid | Ask the user to reconnect through the hosted VCapture link flow |
| `403 Forbidden` or `captures:read` missing | Wrong token or wrong account-link state | Ask the user to reconnect the skill |
| `content key` / decryption error | The skill has the wrong or missing end-to-end key | Ask the user to reconnect the skill so VCapture can issue a fresh wrapped key |
| `No captures found` | VCapture has not uploaded anything yet | Ask the user to confirm VCapture is running and capturing |
| `stale: true` | VCapture is paused, closed, or no longer capturing | Ask the user to start or resume VCapture |

## Important notes

- The skill reads screenshots only through the VCapture HTTPS API.
- Hosted account-link is the primary flow and works whether the skill and VCapture are on the same machine or not.
- Images are encrypted before upload and decrypted on the skill machine after account-link succeeds.
- Read URLs are short-lived and should be fetched fresh each time.
- Prefer images from a single active source so the current and previous captures stay comparable.
- Always fetch fresh captures instead of relying on an older local download.
