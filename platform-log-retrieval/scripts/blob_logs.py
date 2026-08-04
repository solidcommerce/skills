#!/usr/bin/env python3
"""Azure Blob Storage log retrieval for the Solid Commerce platform.

Downloads, decompresses, parses, and filters logs from blob storage containers:
  - services-logs (ZIP, 90 services)
  - web-logs (ZIP, 13 APIs)
  - openretail (GZIP, 10+ services)
"""

import argparse
import gzip
import io
import json
import os
import sys
import time
import zipfile
from typing import Any, Optional

from _common import load_env

load_env()


def _get_blob_service_client():
    """Create BlobServiceClient from connection string env var."""
    from azure.storage.blob import BlobServiceClient

    conn_str = os.environ.get("SC_LOGS_BLOB_CONNECTION_STRING", "")
    if not conn_str:
        print(json.dumps({
            "error": "Missing SC_LOGS_BLOB_CONNECTION_STRING environment variable",
            "message": "Set SC_LOGS_BLOB_CONNECTION_STRING in the .env file with the SAS token connection string.",
        }), file=sys.stderr)
        sys.exit(1)

    return BlobServiceClient.from_connection_string(conn_str)


def _build_prefix(container: str, date: str, service: Optional[str],
                  sub_container: Optional[str], hour_start: int, hour_end: int) -> str:
    """Build blob name prefix for efficient listing."""
    if container == "openretail":
        sub = sub_container or "applogs"
        if service:
            return f"{sub}/{date}/{service.lower()}/"
        return f"{sub}/{date}/"
    elif container in ("services-logs", "web-logs"):
        if service:
            return f"{date}/{service}/"
        return f"{date}/"
    return f"{date}/"


def _hour_from_blob_name(blob_name: str) -> Optional[int]:
    """Extract hour from blob filename like '2026-04-02-14.zip' or '2026-04-02-14.log.gz'."""
    basename = blob_name.rsplit("/", 1)[-1]
    # Pattern: {date}-{HH}.zip or {date}-{HH}.log.gz
    parts = basename.split(".")
    if parts:
        stem = parts[0]  # e.g., "2026-04-02-14"
        segments = stem.split("-")
        if len(segments) >= 4:
            try:
                return int(segments[-1])
            except ValueError:
                pass
    return None


def _list_services(client, container: str, date: str, sub_container: Optional[str]) -> list[str]:
    """List available service names for a given date."""
    container_client = client.get_container_client(container)

    if container == "openretail":
        sub = sub_container or "applogs"
        prefix = f"{sub}/{date}/"
    else:
        prefix = f"{date}/"

    services: set[str] = set()
    try:
        for blob in container_client.list_blobs(name_starts_with=prefix):
            # Extract service name from path
            parts = blob.name.split("/")
            if container == "openretail" and len(parts) >= 3:
                services.add(parts[2])  # applogs/{date}/{service}/...
            elif len(parts) >= 2:
                services.add(parts[1])  # {date}/{service}/...
    except Exception as e:
        print(f"Error listing blobs: {e}", file=sys.stderr)
        sys.exit(1)

    return sorted(services)


def _get_field(record: dict, *keys: str) -> Any:
    """Get first non-None value from record trying multiple key variants (PascalCase, camelCase)."""
    for key in keys:
        val = record.get(key)
        if val is not None:
            return val
    return None


def _safe_int(val: Any) -> Optional[int]:
    """Convert a value to int, handling string representations."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def _parse_ndjson_line(line: str, container: str) -> Optional[dict[str, Any]]:
    """Parse a single NDJSON line into a normalized entry.

    Handles both PascalCase (docs) and camelCase (actual blob data) field names,
    and string-encoded numeric values.
    """
    line = line.strip()
    if not line:
        return None
    # Strip trailing comma (web-logs use comma-separated JSON objects)
    if line.endswith(","):
        line = line[:-1].rstrip()
    try:
        record = json.loads(line)
    except json.JSONDecodeError:
        return None

    # Detect if it's an RrLogRecord (has Request/Response but no Level/ShortDescription)
    has_rr = _get_field(record, "Request", "request") is not None or _get_field(record, "Response", "response") is not None
    has_app = _get_field(record, "ShortDescription", "shortDescription") is not None or \
              _get_field(record, "Level", "level") is not None or \
              _get_field(record, "LogType", "logType") is not None

    level_val = _get_field(record, "Level", "level") or \
                _get_field(record, "LogType", "logType") or \
                ("Info" if has_rr and not has_app else "unknown")

    entry: dict[str, Any] = {
        "source": "blob",
        "container_or_table": container,
        # Handle all timestamp field variants: LogDateTime, logDateTime, logDatetime
        "timestamp": _get_field(record, "LogDateTime", "logDateTime", "logDatetime"),
        "level": level_val,
        "service_name": None,  # filled in by caller from blob path
        "server_name": _get_field(record, "ServerName", "serverName"),
        "company_id": _safe_int(_get_field(record, "CompanyId", "companyId")),
        "short_description": _get_field(record, "ShortDescription", "shortDescription"),
        "long_description": _get_field(record, "LongDescription", "longDescription"),
        "request": _get_field(record, "Request", "request"),
        "response": _get_field(record, "Response", "response"),
        "thread_id": _safe_int(_get_field(record, "ThreadId", "threadId")),
        "raw_line": None,
    }
    return entry


def _matches_filters(entry: dict, level: Optional[str], company_id: Optional[int],
                     keyword: Optional[str]) -> bool:
    """Check if an entry matches the active filters."""
    if level and entry.get("level", "").lower() != level.lower():
        return False
    if company_id is not None and entry.get("company_id") != company_id:
        return False
    if keyword:
        kw_lower = keyword.lower()
        searchable = " ".join(filter(None, [
            str(entry.get("short_description") or ""),
            str(entry.get("long_description") or ""),
            str(entry.get("request") or ""),
            str(entry.get("response") or ""),
        ])).lower()
        if kw_lower not in searchable:
            return False
    return True


def _service_from_blob_path(blob_name: str, container: str) -> str:
    """Extract service name from blob path."""
    parts = blob_name.split("/")
    if container == "openretail" and len(parts) >= 3:
        return parts[2]
    elif len(parts) >= 2:
        return parts[1]
    return "unknown"


def _process_zip_blob(blob_data: bytes, blob_name: str, container: str,
                      level: Optional[str], company_id: Optional[int],
                      keyword: Optional[str], server_filter: Optional[str],
                      limit: int, entries: list[dict],
                      skipped: list[int]) -> None:
    """Process a ZIP blob, extracting and parsing NDJSON content."""
    service_name = _service_from_blob_path(blob_name, container)
    try:
        with zipfile.ZipFile(io.BytesIO(blob_data)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                with zf.open(info) as f:
                    for raw_line in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
                        if len(entries) >= limit:
                            return
                        entry = _parse_ndjson_line(raw_line, container)
                        if entry is None:
                            skipped[0] += 1
                            continue
                        entry["service_name"] = service_name
                        if server_filter and entry.get("server_name", "").lower() != server_filter.lower():
                            continue
                        if _matches_filters(entry, level, company_id, keyword):
                            entries.append(entry)
    except Exception as e:
        print(f"Warning: Failed to process ZIP blob {blob_name}: {e}", file=sys.stderr)
        skipped[0] += 1


def _process_gzip_blob(blob_data: bytes, blob_name: str, container: str,
                       level: Optional[str], company_id: Optional[int],
                       keyword: Optional[str], server_filter: Optional[str],
                       limit: int, entries: list[dict],
                       skipped: list[int]) -> None:
    """Process a GZIP blob, decompressing and parsing NDJSON content."""
    service_name = _service_from_blob_path(blob_name, container)
    try:
        with gzip.open(io.BytesIO(blob_data), "rt", encoding="utf-8", errors="replace") as f:
            for raw_line in f:
                if len(entries) >= limit:
                    return
                entry = _parse_ndjson_line(raw_line, container)
                if entry is None:
                    skipped[0] += 1
                    continue
                entry["service_name"] = service_name
                if server_filter and entry.get("server_name", "").lower() != server_filter.lower():
                    continue
                if _matches_filters(entry, level, company_id, keyword):
                    entries.append(entry)
    except Exception as e:
        print(f"Warning: Failed to process GZIP blob {blob_name}: {e}", file=sys.stderr)
        skipped[0] += 1


def query_blob_logs(container: str, date: str, service: Optional[str] = None,
                    level: Optional[str] = None, company_id: Optional[int] = None,
                    keyword: Optional[str] = None, hour_start: int = 0,
                    hour_end: int = 23, limit: int = 200,
                    sub_container: Optional[str] = None,
                    server: Optional[str] = None) -> dict:
    """Query blob storage for log entries."""
    start_time = time.time()

    client = _get_blob_service_client()
    container_client = client.get_container_client(container)

    prefix = _build_prefix(container, date, service, sub_container, hour_start, hour_end)

    entries: list[dict] = []
    skipped = [0]  # mutable counter
    blobs_processed = 0

    try:
        blob_list = list(container_client.list_blobs(name_starts_with=prefix))
    except Exception as e:
        return {
            "metadata": {
                "source": "blob",
                "container_or_table": container,
                "query_filters": {"date": date, "service": service, "level": level},
                "total_results": 0,
                "truncated": False,
                "skipped_entries": 0,
                "blobs_processed": 0,
                "query_time_ms": int((time.time() - start_time) * 1000),
                "error": f"Failed to list blobs: {e}",
            },
            "entries": [],
        }

    # Filter blobs by hour range
    filtered_blobs = []
    for blob in blob_list:
        hour = _hour_from_blob_name(blob.name)
        if hour is not None:
            if hour_start <= hour <= hour_end:
                filtered_blobs.append(blob)
        else:
            # Can't determine hour, include it
            filtered_blobs.append(blob)

    # Sort blobs by name (chronological since names encode date-hour)
    filtered_blobs.sort(key=lambda b: b.name)

    for blob in filtered_blobs:
        if len(entries) >= limit:
            break

        try:
            blob_client = container_client.get_blob_client(blob.name)
            # Download blob data
            download = blob_client.download_blob()
            blob_data = download.readall()
            blobs_processed += 1
        except Exception as e:
            print(f"Warning: Failed to download blob {blob.name}: {e}", file=sys.stderr)
            skipped[0] += 1
            continue

        # Process based on file extension
        if blob.name.endswith(".zip"):
            _process_zip_blob(blob_data, blob.name, container, level, company_id,
                              keyword, server, limit, entries, skipped)
        elif blob.name.endswith(".gz") or blob.name.endswith(".log.gz"):
            _process_gzip_blob(blob_data, blob.name, container, level, company_id,
                               keyword, server, limit, entries, skipped)

    elapsed_ms = int((time.time() - start_time) * 1000)

    return {
        "metadata": {
            "source": "blob",
            "container_or_table": container,
            "query_filters": {
                "date": date,
                "service": service,
                "level": level,
                "company_id": company_id,
                "keyword": keyword,
                "hour_range": f"{hour_start}-{hour_end}",
                "server": server,
            },
            "total_results": len(entries),
            "truncated": len(entries) >= limit,
            "skipped_entries": skipped[0],
            "blobs_processed": blobs_processed,
            "query_time_ms": elapsed_ms,
        },
        "entries": entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query Azure Blob Storage logs for Solid Commerce platform services.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --container services-logs --date 2026-04-02 --service LDS_AmazonOrdersSync --level Error
  %(prog)s --container web-logs --date 2026-04-02 --service OrdersAPI
  %(prog)s --container openretail --date 2026-04-02 --service lds_bigcommerceorderssync --sub-container applogs
  %(prog)s --container services-logs --date 2026-04-02 --list-services
        """,
    )

    parser.add_argument("--container", type=str, required=False,
                        choices=["services-logs", "web-logs", "openretail"],
                        help="Blob container: services-logs, web-logs, or openretail")
    parser.add_argument("--date", type=str, required=False,
                        help="Date in YYYY-MM-DD format")
    parser.add_argument("--service", type=str, default=None,
                        help="Service name (blob path segment)")
    parser.add_argument("--level", type=str, default=None,
                        choices=["Error", "Warning", "Info", "Debug", "Trace"],
                        help="Log level filter")
    parser.add_argument("--company-id", type=int, default=None,
                        help="Filter by CompanyId")
    parser.add_argument("--keyword", type=str, default=None,
                        help="Search in ShortDescription + LongDescription")
    parser.add_argument("--hour-start", type=int, default=0,
                        help="Start hour 0-23 (default: 0)")
    parser.add_argument("--hour-end", type=int, default=23,
                        help="End hour 0-23 (default: 23)")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max entries returned (default: 200)")
    parser.add_argument("--sub-container", type=str, default="applogs",
                        choices=["applogs", "rrlogs"],
                        help="For openretail: applogs or rrlogs (default: applogs)")
    parser.add_argument("--server", type=str, default=None,
                        help="Filter by ServerName")
    parser.add_argument("--list-services", action="store_true",
                        help="List available services for the date")

    args = parser.parse_args()

    if not args.container:
        parser.error("--container is required")
    if not args.date:
        parser.error("--date is required")

    if args.list_services:
        client = _get_blob_service_client()
        services = _list_services(client, args.container, args.date, args.sub_container)
        output = {
            "container": args.container,
            "date": args.date,
            "services": services,
            "total_services": len(services),
        }
        json.dump(output, sys.stdout, indent=2)
        print()
        sys.exit(0)

    result = query_blob_logs(
        container=args.container,
        date=args.date,
        service=args.service,
        level=args.level,
        company_id=args.company_id,
        keyword=args.keyword,
        hour_start=args.hour_start,
        hour_end=args.hour_end,
        limit=args.limit,
        sub_container=args.sub_container,
        server=args.server,
    )

    json.dump(result, sys.stdout, indent=2)
    print()

    if result["metadata"].get("error"):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
