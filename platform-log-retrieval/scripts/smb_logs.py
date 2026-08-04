#!/usr/bin/env python3
"""SMB network share log access for the Solid Commerce platform.

Accesses \\\\logs.scservices.com\\Logs via smbclient for real-time logs
(last 4 hours before blob upload). Gracefully degrades when credentials
are not configured.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Optional

from _common import load_env

load_env()


# Valid subfolders on the share
VALID_SUBFOLDERS = [
    "LDS_Amazon_Services", "LDS_Services", "LDS_Stores",
    "SC_Services", "Web_Logs",
]


def _check_smbclient() -> None:
    """Verify smbclient is installed."""
    if not shutil.which("smbclient"):
        print(json.dumps({
            "error": "smbclient not found",
            "message": "smbclient is not installed. Install with: sudo apt-get install smbclient",
        }), file=sys.stderr)
        sys.exit(1)


def _check_credentials() -> tuple[str, str, str, str]:
    """Check and return SMB credentials. Exit 2 if not configured."""
    share = os.environ.get("SC_LOGS_SMB_SHARE", "//logs.scservices.com/Logs")
    user = os.environ.get("SC_LOGS_SMB_USER", "")
    password = os.environ.get("SC_LOGS_SMB_PASSWORD", "")
    domain = os.environ.get("SC_LOGS_SMB_DOMAIN", "")

    if not user or not password:
        result = {
            "error": "SMB credentials not configured",
            "message": ("The SMB network share requires credentials that are not yet configured. "
                        "Set SC_LOGS_SMB_USER, SC_LOGS_SMB_PASSWORD, and SC_LOGS_SMB_DOMAIN "
                        "environment variables in the .env file."),
            "fallback_suggestion": ("Use blob_logs.py for historical logs (note: most recent "
                                    "4 hours may not be available in blob storage yet)"),
        }
        json.dump(result, sys.stdout, indent=2)
        print()
        sys.exit(2)

    return share, user, password, domain


def _create_auth_file(user: str, password: str, domain: str) -> str:
    """Create a temp auth file for smbclient. Returns path. Caller must clean up."""
    fd, path = tempfile.mkstemp(prefix="smb_auth_", suffix=".conf")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(f"username = {user}\n")
            f.write(f"password = {password}\n")
            f.write(f"domain = {domain}\n")
        os.chmod(path, 0o600)
    except Exception:
        os.unlink(path)
        raise
    return path


_SAFE_FILENAME_RE = re.compile(r"^[\w\.\-\s\(\)]+$")


def _validate_filename(filename: str) -> None:
    """Reject filenames with characters that could manipulate smbclient commands."""
    if not _SAFE_FILENAME_RE.match(filename):
        raise ValueError(
            f"Unsafe filename rejected: {filename!r}. "
            "Filenames must contain only alphanumeric, dot, dash, underscore, space, or parentheses."
        )


def _run_smbclient(share: str, auth_file: str, command: str,
                    timeout: int = 30) -> tuple[str, str]:
    """Run an smbclient command and return (stdout, stderr)."""
    cmd = ["smbclient", share, "-A", auth_file, "-c", command]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"SMB command timed out after {timeout}s: {command}")
    except FileNotFoundError:
        raise RuntimeError("smbclient not found on PATH")

    stderr = result.stderr.strip()

    # Classify errors
    if result.returncode != 0:
        if "NT_STATUS_LOGON_FAILURE" in stderr:
            raise RuntimeError("SMB authentication failed. Check SC_LOGS_SMB_* env vars.")
        elif "NT_STATUS_BAD_NETWORK_NAME" in stderr or "NT_STATUS_HOST_UNREACHABLE" in stderr:
            raise RuntimeError(
                f"Network share unavailable at {share}. "
                "Fall back to blob storage (note: most recent 4 hours may be missing)."
            )
        elif "NT_STATUS_OBJECT_NAME_NOT_FOUND" in stderr or "NT_STATUS_NO_SUCH_FILE" in stderr:
            raise RuntimeError(f"Path not found on share: {command}")
        elif stderr:
            raise RuntimeError(f"smbclient error (code {result.returncode}): {stderr}")

    return result.stdout, stderr


def _parse_ls_output(output: str) -> list[dict[str, str]]:
    """Parse smbclient 'ls' output into file list."""
    files = []
    # smbclient ls output format:
    #   filename                        A      1234  Wed Apr  2 14:30:00 2026
    pattern = re.compile(
        r"^\s+(.+?)\s+([ADHRSAN]+)\s+(\d+)\s+(.+)$"
    )
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            name = match.group(1).strip()
            # Skip . and .. entries
            if name in (".", ".."):
                continue
            size = match.group(3)
            date_str = match.group(4).strip()
            files.append({
                "name": name,
                "size": size,
                "date": date_str,
            })

    return files


def _parse_nlog_csv_line(line: str) -> Optional[dict[str, Any]]:
    """Parse a NLog CSV (tab-delimited) line into a normalized entry."""
    parts = line.split("\t")
    if len(parts) < 2:
        return None

    # NLog columns: logDateTime, level, serverName, logType, IntegrationName,
    # ServiceName, InternalCustomerId, SolidCommercecompanyId,
    # shortDescription, longDescription, Request, Response
    def _get(idx: int) -> Optional[str]:
        if idx < len(parts):
            val = parts[idx].strip()
            return val if val else None
        return None

    company_id = None
    raw_cid = _get(7)
    if raw_cid:
        try:
            company_id = int(raw_cid)
        except ValueError:
            pass

    return {
        "timestamp": _get(0),
        "level": _get(1) or "unknown",
        "server_name": _get(2),
        "service_name": _get(5) or _get(4),
        "company_id": company_id,
        "short_description": _get(8),
        "long_description": _get(9),
        "request": _get(10),
        "response": _get(11),
        "thread_id": None,
        "raw_line": None,
    }


def _parse_freetext_line(line: str) -> dict[str, Any]:
    """Best-effort parsing of a free-text log line."""
    entry: dict[str, Any] = {
        "timestamp": None,
        "level": "unknown",
        "server_name": None,
        "service_name": None,
        "company_id": None,
        "short_description": line[:500] if len(line) > 500 else line,
        "long_description": None,
        "request": None,
        "response": None,
        "thread_id": None,
        "raw_line": line,
    }

    # Try to extract timestamp
    ts_pattern = re.compile(r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})")
    ts_match = ts_pattern.search(line)
    if ts_match:
        entry["timestamp"] = ts_match.group(1)

    # Try to extract log level
    level_pattern = re.compile(r"\b(ERROR|WARN(?:ING)?|INFO|DEBUG|TRACE|FATAL)\b", re.IGNORECASE)
    level_match = level_pattern.search(line)
    if level_match:
        level_raw = level_match.group(1).upper()
        level_map = {"ERROR": "Error", "WARN": "Warning", "WARNING": "Warning",
                     "INFO": "Info", "DEBUG": "Debug", "TRACE": "Trace", "FATAL": "Error"}
        entry["level"] = level_map.get(level_raw, "unknown")

    return entry


def _detect_and_parse_line(line: str) -> Optional[dict[str, Any]]:
    """Detect line format (NLog CSV or free text) and parse accordingly."""
    line = line.rstrip("\n\r")
    if not line.strip():
        return None

    # If line has multiple tabs, treat as NLog CSV
    if line.count("\t") >= 3:
        parsed = _parse_nlog_csv_line(line)
        if parsed:
            return parsed

    # Try JSON
    if line.strip().startswith("{"):
        try:
            record = json.loads(line)
            return {
                "timestamp": record.get("LogDateTime") or record.get("logDateTime"),
                "level": record.get("Level") or record.get("level") or record.get("LogType") or "unknown",
                "server_name": record.get("ServerName") or record.get("serverName"),
                "service_name": record.get("ServiceName"),
                "company_id": record.get("CompanyId") or record.get("SolidCommercecompanyId"),
                "short_description": record.get("ShortDescription") or record.get("shortDescription"),
                "long_description": record.get("LongDescription") or record.get("longDescription"),
                "request": record.get("Request"),
                "response": record.get("Response"),
                "thread_id": record.get("ThreadId"),
                "raw_line": None,
            }
        except json.JSONDecodeError:
            pass

    # Fall back to free text
    return _parse_freetext_line(line)


def _tail_lines(filepath: str, n: int) -> list[str]:
    """Read the last n lines from a file efficiently."""
    try:
        file_size = os.path.getsize(filepath)
    except OSError:
        return []

    if file_size == 0:
        return []

    # For files < 10MB, just read the whole thing
    if file_size < 10 * 1024 * 1024:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            # Strip incomplete last line (file may be actively written)
            if lines and not lines[-1].endswith("\n"):
                lines = lines[:-1]
            return lines[-n:]

    # For large files, read from the end in chunks
    chunk_size = min(file_size, 1024 * 1024)  # 1MB chunks
    collected: list[str] = []  # built in reverse order, reversed at end
    with open(filepath, "rb") as f:
        f.seek(0, 2)  # Seek to end
        pos = f.tell()
        remaining = b""

        while pos > 0 and len(collected) < n + 1:
            read_size = min(chunk_size, pos)
            pos -= read_size
            f.seek(pos)
            chunk = f.read(read_size) + remaining
            remaining = b""

            chunk_lines = chunk.split(b"\n")
            # First element may be partial if we're not at file start
            if pos > 0:
                remaining = chunk_lines[0]
                chunk_lines = chunk_lines[1:]

            for raw in reversed(chunk_lines):
                decoded = raw.decode("utf-8", errors="replace").rstrip("\r")
                if decoded:
                    collected.append(decoded + "\n")
                if len(collected) >= n + 1:
                    break

    # Reverse to restore chronological order
    collected.reverse()

    # Strip incomplete last line
    if collected and not collected[-1].endswith("\n"):
        collected = collected[:-1]

    return collected[-n:]


def _filter_entries(entries: list[dict], service: Optional[str],
                    keyword: Optional[str], level: Optional[str],
                    company_id: Optional[int]) -> list[dict]:
    """Apply filters to parsed entries."""
    filtered = []
    for entry in entries:
        if level and entry.get("level", "").lower() != level.lower():
            continue
        if company_id is not None and entry.get("company_id") != company_id:
            continue
        if service:
            svc_lower = (entry.get("service_name") or "").lower()
            if service.lower() not in svc_lower:
                continue
        if keyword:
            kw_lower = keyword.lower()
            searchable = " ".join(filter(None, [
                str(entry.get("short_description") or ""),
                str(entry.get("long_description") or ""),
                str(entry.get("request") or ""),
                str(entry.get("response") or ""),
                str(entry.get("raw_line") or ""),
            ])).lower()
            if kw_lower not in searchable:
                continue
        filtered.append(entry)
    return filtered


def list_files(share: str, auth_file: str, subfolder: str,
               service: Optional[str] = None) -> dict:
    """List files in an SMB subfolder."""
    start_time = time.time()

    ls_cmd = f'ls "{subfolder}\\*"'
    stdout, _ = _run_smbclient(share, auth_file, ls_cmd)

    files = _parse_ls_output(stdout)

    if service:
        service_lower = service.lower()
        files = [f for f in files if service_lower in f["name"].lower()]

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "subfolder": subfolder,
        "files": files,
        "total_files": len(files),
        "query_time_ms": elapsed_ms,
    }


def read_file(share: str, auth_file: str, subfolder: str, filename: str,
              tail: int = 500, service: Optional[str] = None,
              keyword: Optional[str] = None, level: Optional[str] = None,
              company_id: Optional[int] = None) -> dict:
    """Download and parse a specific log file from the share."""
    _validate_filename(filename)
    start_time = time.time()

    tmpdir = tempfile.mkdtemp(prefix="smb_logs_")
    local_path = os.path.join(tmpdir, filename)

    try:
        remote_path = f"{subfolder}\\{filename}"
        get_cmd = f'get "{remote_path}" "{local_path}"'
        _run_smbclient(share, auth_file, get_cmd)

        lines = _tail_lines(local_path, tail)

        entries = []
        for line in lines:
            parsed = _detect_and_parse_line(line)
            if parsed:
                parsed["source"] = "smb"
                parsed["container_or_table"] = subfolder
                entries.append(parsed)

        entries = _filter_entries(entries, service, keyword, level, company_id)

    finally:
        # Clean up temp files
        try:
            if os.path.exists(local_path):
                os.unlink(local_path)
            os.rmdir(tmpdir)
        except OSError:
            pass

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "metadata": {
            "source": "smb",
            "container_or_table": subfolder,
            "query_filters": {
                "subfolder": subfolder,
                "filename": filename,
                "service": service,
                "keyword": keyword,
                "level": level,
                "tail": tail,
            },
            "total_results": len(entries),
            "truncated": False,
            "files_read": [filename],
            "query_time_ms": elapsed_ms,
        },
        "entries": entries,
    }


def search_subfolder(share: str, auth_file: str, subfolder: str,
                     service: Optional[str] = None, keyword: Optional[str] = None,
                     tail: int = 500, level: Optional[str] = None,
                     company_id: Optional[int] = None) -> dict:
    """Search across files in a subfolder, optionally filtered by service name."""
    start_time = time.time()

    # List files in subfolder
    ls_result = list_files(share, auth_file, subfolder, service)
    files = ls_result["files"]

    if not files:
        elapsed_ms = int((time.time() - start_time) * 1000)
        return {
            "metadata": {
                "source": "smb",
                "container_or_table": subfolder,
                "query_filters": {
                    "subfolder": subfolder, "service": service,
                    "keyword": keyword, "tail": tail,
                },
                "total_results": 0, "truncated": False,
                "files_read": [], "query_time_ms": elapsed_ms,
            },
            "entries": [],
        }

    # Sort by date (most recent first) and take top files
    # Limit to a reasonable number of files to avoid downloading everything
    max_files = 5
    target_files = files[:max_files]

    all_entries: list[dict] = []
    files_read: list[str] = []

    tmpdir = tempfile.mkdtemp(prefix="smb_logs_")

    try:
        for file_info in target_files:
            fname = file_info["name"]
            local_path = os.path.join(tmpdir, fname)

            try:
                remote_path = f"{subfolder}\\{fname}"
                get_cmd = f'get "{remote_path}" "{local_path}"'
                _run_smbclient(share, auth_file, get_cmd)

                lines = _tail_lines(local_path, tail)

                for line in lines:
                    parsed = _detect_and_parse_line(line)
                    if parsed:
                        parsed["source"] = "smb"
                        parsed["container_or_table"] = subfolder
                        all_entries.append(parsed)

                files_read.append(fname)

            except RuntimeError as e:
                print(f"Warning: Failed to read {fname}: {e}", file=sys.stderr)
            finally:
                try:
                    if os.path.exists(local_path):
                        os.unlink(local_path)
                except OSError:
                    pass
    finally:
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass

    # Apply filters after collecting all entries
    all_entries = _filter_entries(all_entries, service, keyword, level, company_id)

    # Limit total entries
    all_entries = all_entries[-tail:]

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "metadata": {
            "source": "smb",
            "container_or_table": subfolder,
            "query_filters": {
                "subfolder": subfolder, "service": service,
                "keyword": keyword, "level": level, "tail": tail,
            },
            "total_results": len(all_entries),
            "truncated": len(files) > max_files,
            "files_read": files_read,
            "query_time_ms": elapsed_ms,
        },
        "entries": all_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Access real-time logs from the SMB network share (last 4 hours).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --subfolder LDS_Services --list-files
  %(prog)s --subfolder SC_Services --service "OrderImport" --tail 200
  %(prog)s --subfolder LDS_Amazon_Services --keyword "error" --tail 500
  %(prog)s --subfolder Web_Logs --filename "OrdersAPI_2026-04-02.log" --tail 100
        """,
    )

    parser.add_argument("--subfolder", type=str, required=True,
                        choices=VALID_SUBFOLDERS,
                        help="Share subfolder to access")
    parser.add_argument("--service", type=str, default=None,
                        help="Service name to filter files")
    parser.add_argument("--keyword", type=str, default=None,
                        help="Search log file contents for this text")
    parser.add_argument("--tail", type=int, default=500,
                        help="Number of recent lines to read per file (default: 500)")
    parser.add_argument("--list-files", action="store_true",
                        help="List available log files in the subfolder")
    parser.add_argument("--filename", type=str, default=None,
                        help="Read a specific file by name")
    parser.add_argument("--level", type=str, default=None,
                        help="Filter by log level")
    parser.add_argument("--company-id", type=int, default=None,
                        help="Filter by company ID")

    args = parser.parse_args()

    # Pre-flight checks
    _check_smbclient()
    share, user, password, domain = _check_credentials()

    auth_file = _create_auth_file(user, password, domain)

    try:
        if args.list_files:
            result = list_files(share, auth_file, args.subfolder, args.service)
            json.dump(result, sys.stdout, indent=2)
            print()
            sys.exit(0)

        if args.filename:
            result = read_file(
                share, auth_file, args.subfolder, args.filename,
                tail=args.tail, service=args.service,
                keyword=args.keyword, level=args.level,
                company_id=args.company_id,
            )
        else:
            result = search_subfolder(
                share, auth_file, args.subfolder,
                service=args.service, keyword=args.keyword,
                tail=args.tail, level=args.level,
                company_id=args.company_id,
            )

        json.dump(result, sys.stdout, indent=2)
        print()

        if result.get("metadata", {}).get("error"):
            sys.exit(1)
        sys.exit(0)

    except RuntimeError as e:
        error_result = {
            "error": str(e),
            "fallback_suggestion": ("Use blob_logs.py for historical logs "
                                    "(note: most recent 4 hours may not be available)"),
        }
        json.dump(error_result, sys.stdout, indent=2)
        print()
        sys.exit(1)

    finally:
        # Always clean up auth file
        try:
            os.unlink(auth_file)
        except OSError:
            pass


if __name__ == "__main__":
    main()
