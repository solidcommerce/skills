#!/usr/bin/env python3
"""Shared utilities for platform-log-retrieval scripts."""

import os
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = SKILL_DIR / ".env"


def load_env() -> None:
    """Load environment variables from the skill's .env file.

    Tries python-dotenv first, falls back to manual parsing.
    Existing environment variables are not overwritten.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_FILE)
        return
    except ImportError:
        pass
    # Manual fallback — handles values with = (e.g., connection strings)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
