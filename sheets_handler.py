"""
Google Sheets handler.

Supports two credential modes:
  - Local:  GOOGLE_SERVICE_ACCOUNT_JSON = /path/to/service_account.json
  - CI:     GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT = raw JSON string (GitHub Secret)
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

import config
from models import Listing
from utils import get_logger

log = get_logger("sheets")

_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

_HEADERS = [
    "listing_id",
    "complex_id",
    "trade_type",
    "date",
    "price",
    "monthly_rent",
    "area_m2",
    "floor",
    "total_floors",
    "direction",
    "article_name",
    "agent_name",
    "confirmed_type",
    "description",
    "tags",
]


# ── Auth ───────────────────────────────────────────────────────────────────────

def _get_client() -> gspread.Client:
    """Build gspread client from env-configured credentials."""
    raw_json = config.GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT
    if raw_json and raw_json.strip():
        info = json.loads(raw_json)
        creds = Credentials.from_service_account_info(info, scopes=_SCOPES)
        log.info("Authenticated via GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT")
    else:
        path = config.GOOGLE_SERVICE_ACCOUNT_JSON
        if not path:
            raise ValueError(
                "Set GOOGLE_SERVICE_ACCOUNT_JSON (file path) or "
                "GOOGLE_SERVICE_ACCOUNT_JSON_CONTENT (raw JSON)"
            )
        creds = Credentials.from_service_account_file(path, scopes=_SCOPES)
        log.info("Authenticated via file: %s", path)
    return gspread.authorize(creds)


# ── Spreadsheet / worksheet management ────────────────────────────────────────

def get_or_create_spreadsheet(gc: gspread.Client) -> gspread.Spreadsheet:
    """Return existing spreadsheet or create a new one.

    On first run (GOOGLE_SPREADSHEET_ID is blank), creates the sheet,
    shares it with GOOGLE_SHARE_EMAIL, and logs the new ID.
    """
    spreadsheet_id = config.GOOGLE_SPREADSHEET_ID
    if spreadsheet_id:
        log.info("Opening spreadsheet: %s", spreadsheet_id)
        return gc.open_by_key(spreadsheet_id)

    # First run — create new
    sh = gc.create("Naver Real Estate Data")
    log.info("Created new spreadsheet. ID: %s", sh.id)
    log.info(">> Set GOOGLE_SPREADSHEET_ID=%s in .env and GitHub Secrets <<", sh.id)

    email = config.GOOGLE_SHARE_EMAIL
    if email:
        sh.share(email, perm_type="user", role="writer")
        log.info("Shared with %s", email)

    return sh


def get_or_create_worksheet(
    sh: gspread.Spreadsheet, tab_name: str
) -> gspread.Worksheet:
    """Return existing worksheet or create one with headers."""
    try:
        ws = sh.worksheet(tab_name)
        log.info("Opened existing tab: %s", tab_name)
        return ws
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab_name, rows=5000, cols=len(_HEADERS))
        ws.append_row(_HEADERS, value_input_option="RAW")
        log.info("Created new tab: %s", tab_name)
        return ws


# ── Read / Write ───────────────────────────────────────────────────────────────

def _listing_to_row(listing: Listing) -> list:
    return [
        listing.listing_id,
        listing.complex_id,
        listing.trade_type,
        listing.date,
        listing.price,
        listing.monthly_rent,
        listing.area_m2,
        listing.floor,
        listing.total_floors,
        listing.direction,
        listing.article_name,
        listing.agent_name,
        listing.confirmed_type,
        listing.description,
        listing.tags,
    ]


def write_listings(listings: list[Listing]) -> None:
    """Write all listings to today's tab in a single batch call."""
    gc = _get_client()
    sh = get_or_create_spreadsheet(gc)
    today = date.today().isoformat()
    ws = get_or_create_worksheet(sh, today)

    if not listings:
        log.info("No listings to write for %s", today)
        return

    # Clear existing rows (skip header row) to avoid duplicates on re-run
    existing = ws.get_all_values()
    if len(existing) > 1:
        ws.delete_rows(2, len(existing))
        log.info("Cleared %d existing data rows", len(existing) - 1)

    rows = [_listing_to_row(l) for l in listings]
    ws.append_rows(rows, value_input_option="RAW")
    log.info("Wrote %d listings to tab '%s'", len(rows), today)


def read_worksheet(sh: gspread.Spreadsheet, tab_name: str) -> list[dict]:
    """Read a named tab and return list of dicts. Returns [] if tab absent."""
    try:
        ws = sh.worksheet(tab_name)
        records = ws.get_all_records()
        log.info("Read %d records from tab '%s'", len(records), tab_name)
        return records
    except gspread.WorksheetNotFound:
        log.info("Tab '%s' not found — returning empty list", tab_name)
        return []


def read_yesterday(trade_type: str) -> list[dict]:
    """Load yesterday's tab rows for delta computation.

    Returns [] if yesterday's tab doesn't exist (first run).
    """
    gc = _get_client()
    sh = get_or_create_spreadsheet(gc)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    rows = read_worksheet(sh, yesterday)
    # Filter to matching trade_type
    return [r for r in rows if r.get("trade_type") == trade_type]


def get_spreadsheet() -> gspread.Spreadsheet:
    """Convenience: return the configured spreadsheet (used by main.py)."""
    gc = _get_client()
    return get_or_create_spreadsheet(gc)
