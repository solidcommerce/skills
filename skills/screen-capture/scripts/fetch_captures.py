#!/usr/bin/env python3
"""
Fetch the latest screen captures from Azure Blob Storage.

Connects to the avcapture storage account, finds the most recent captures,
downloads them locally, and reports their paths and freshness.

Usage:
    python fetch_captures.py [--count N] [--stale-threshold SECONDS]

Environment:
    AVCAPTURE_CONNECTION_STRING - Azure Blob Storage connection string
    Falls back to Key Vault (coding-agent-keyvault) if env var is not set.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_DIR = Path("/tmp/screen-captures")
CONTAINER_NAME = "avcapture"
BLOB_PREFIX = "captures"
KEYVAULT_NAME = "coding-agent-keyvault"
SECRET_NAME = "avcapture-blob-connection-string"


def get_connection_string():
    """Get the Azure Blob Storage connection string from env var or Key Vault."""
    conn_str = os.environ.get("AVCAPTURE_CONNECTION_STRING")
    if conn_str:
        return conn_str

    # Fallback: try Key Vault via az CLI
    try:
        result = subprocess.run(
            [
                "az", "keyvault", "secret", "show",
                "--vault-name", KEYVAULT_NAME,
                "--name", SECRET_NAME,
                "--query", "value",
                "-o", "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def list_recent_blobs(connection_string, count):
    """List the most recent blobs using az CLI."""
    # List all blobs with the prefix, sorted by last modified (descending)
    result = subprocess.run(
        [
            "az", "storage", "blob", "list",
            "--connection-string", connection_string,
            "--container-name", CONTAINER_NAME,
            "--prefix", BLOB_PREFIX,
            "--num-results", "500",
            "--query",
            "sort_by([?ends_with(name, '.jpg') || ends_with(name, '.png')], &properties.lastModified) | reverse(@) | [0:{}].[name, properties.lastModified, properties.contentLength]".format(count),
            "--output", "json",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to list blobs: {result.stderr.strip()}")

    blobs = json.loads(result.stdout)
    return blobs


def download_blob(connection_string, blob_name, local_path):
    """Download a single blob to a local path."""
    result = subprocess.run(
        [
            "az", "storage", "blob", "download",
            "--connection-string", connection_string,
            "--container-name", CONTAINER_NAME,
            "--name", blob_name,
            "--file", str(local_path),
            "--no-progress",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to download {blob_name}: {result.stderr.strip()}")


def parse_blob_timestamp(blob_name):
    """Extract timestamp from blob name like captures/2026/04/08/window_X/20260408T225605835Z.jpg"""
    filename = Path(blob_name).stem  # e.g., 20260408T225605835Z
    try:
        # Parse compact ISO format: YYYYMMDDTHHMMSSfffZ
        ts_str = filename.rstrip("Z")
        dt = datetime(
            year=int(ts_str[0:4]),
            month=int(ts_str[4:6]),
            day=int(ts_str[6:8]),
            hour=int(ts_str[9:11]),
            minute=int(ts_str[11:13]),
            second=int(ts_str[13:15]),
            microsecond=int(ts_str[15:18]) * 1000 if len(ts_str) > 15 else 0,
            tzinfo=timezone.utc,
        )
        return dt
    except (ValueError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description="Fetch latest screen captures from Azure Blob Storage")
    parser.add_argument("--count", type=int, default=2, help="Number of captures to fetch (default: 2)")
    parser.add_argument("--stale-threshold", type=int, default=60, help="Seconds before captures are considered stale (default: 60)")
    args = parser.parse_args()

    # Get connection string
    conn_str = get_connection_string()
    if not conn_str:
        print(json.dumps({
            "status": "error",
            "message": "AVCAPTURE_CONNECTION_STRING environment variable is not set and Key Vault fallback failed. "
                       "Please set the env var or ensure 'az' CLI is logged in with access to coding-agent-keyvault."
        }))
        sys.exit(1)

    # Prepare output directory
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up old captures
    for old_file in OUTPUT_DIR.glob("capture_*.jpg"):
        old_file.unlink()
    for old_file in OUTPUT_DIR.glob("capture_*.png"):
        old_file.unlink()

    try:
        # List recent blobs
        blobs = list_recent_blobs(conn_str, args.count)

        if not blobs:
            print(json.dumps({
                "status": "error",
                "message": "No captures found in blob storage. Please verify AVCapture is running and capturing."
            }))
            sys.exit(1)

        now = datetime.now(timezone.utc)
        captures = []
        labels = ["latest", "previous", "third", "fourth", "fifth"]

        for i, blob_info in enumerate(blobs):
            blob_name = blob_info[0]
            ext = Path(blob_name).suffix or ".jpg"
            label = labels[i] if i < len(labels) else f"capture_{i}"
            local_path = OUTPUT_DIR / f"capture_{label}{ext}"

            download_blob(conn_str, blob_name, local_path)

            # Parse timestamp from filename
            ts = parse_blob_timestamp(blob_name)
            age_seconds = int((now - ts).total_seconds()) if ts else None

            captures.append({
                "path": str(local_path),
                "blob_name": blob_name,
                "timestamp": ts.isoformat() if ts else "unknown",
                "age_seconds": age_seconds,
            })

        # Check staleness based on the most recent capture
        latest_age = captures[0].get("age_seconds")
        is_stale = latest_age is not None and latest_age > args.stale_threshold

        output = {
            "status": "ok",
            "captures": captures,
            "stale": is_stale,
        }

        if is_stale:
            output["stale_message"] = (
                f"Latest capture is {latest_age} seconds old (threshold: {args.stale_threshold}s). "
                "AVCapture may not be running. Please start or resume AVCapture on your machine."
            )

        print(json.dumps(output, indent=2))

    except Exception as e:
        print(json.dumps({
            "status": "error",
            "message": str(e),
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()
