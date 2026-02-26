"""Centralised config loader — reads from .env and environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (silently skipped if absent in CI)
load_dotenv(Path(__file__).parent / ".env")


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _get_int(key: str, default: int = 0) -> int:
    try:
        return int(_get(key, str(default)))
    except ValueError:
        return default


def _get_float(key: str, default: float = 0.0) -> float:
    try:
        return float(_get(key, str(default)))
    except ValueError:
        return default


def _get_list(key: str, default: str = "") -> list[str]:
    raw = _get(key, default)
    return [x.strip() for x in raw.split(",") if x.strip()]


# ── Google Sheets ──────────────────────────────────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_JSON: str = _get("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT: str = _get("GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")
GOOGLE_SHARE_EMAIL: str = _get("GOOGLE_SHARE_EMAIL")
GOOGLE_SPREADSHEET_ID: str = _get("GOOGLE_SPREADSHEET_ID")

# ── Notion ─────────────────────────────────────────────────────────────────────
NOTION_TOKEN: str = _get("NOTION_TOKEN")
NOTION_PARENT_PAGE_ID: str = _get("NOTION_PARENT_PAGE_ID")
NOTION_DATABASE_ID: str = _get("NOTION_DATABASE_ID")

# ── Scraper ────────────────────────────────────────────────────────────────────
COMPLEX_IDS: list[str] = _get_list("COMPLEX_IDS", "8928")
TRADE_TYPES: list[str] = _get_list("TRADE_TYPES", "A1,B1,B2")
MAX_LISTINGS_PER_COMPLEX: int = _get_int("MAX_LISTINGS_PER_COMPLEX", 200)
SLEEP_MIN: float = _get_float("SLEEP_MIN", 2.5)
SLEEP_MAX: float = _get_float("SLEEP_MAX", 6.0)
HEADLESS: bool = _get("HEADLESS", "true").lower() in ("1", "true", "yes")
