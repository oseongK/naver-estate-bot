"""
Notion dashboard handler.

Creates/updates a Notion database with daily per-complex summaries.
One row per complex × trade_type × date.
"""

from __future__ import annotations

import time

from notion_client import Client

import config
from models import ComplexSummary
from utils import get_logger

log = get_logger("notion")

_RATE_LIMIT_SLEEP = 0.35  # 350ms between API calls


# ── Database schema definition ─────────────────────────────────────────────────

def _db_properties_schema() -> dict:
    return {
        "Name": {"title": {}},
        "Complex ID": {"rich_text": {}},
        "Date": {"date": {}},
        "Trade Type": {
            "select": {
                "options": [
                    {"name": "A1", "color": "blue"},
                    {"name": "B1", "color": "green"},
                    {"name": "B2", "color": "orange"},
                ]
            }
        },
        "Total Listings": {"number": {"format": "number"}},
        "New Listings": {"number": {"format": "number"}},
        "Removed Listings": {"number": {"format": "number"}},
        "Avg Price (만원)": {"number": {"format": "number"}},
        "Avg Price Change": {"number": {"format": "number"}},
        "Avg Price Change %": {"number": {"format": "number"}},
        "Min Price (만원)": {"number": {"format": "number"}},
        "Min Price Change": {"number": {"format": "number"}},
        "Lowest Listing": {"rich_text": {}},
    }


# ── Database setup ─────────────────────────────────────────────────────────────

def get_or_create_database(notion: Client) -> str:
    """Return existing DB ID or create a new one under NOTION_PARENT_PAGE_ID.

    Logs newly created DB ID so user can set NOTION_DATABASE_ID in .env.
    """
    db_id = config.NOTION_DATABASE_ID
    if db_id:
        log.info("Using existing Notion database: %s", db_id)
        return db_id

    parent_id = config.NOTION_PARENT_PAGE_ID
    if not parent_id:
        raise ValueError("Set NOTION_PARENT_PAGE_ID in .env")

    resp = notion.databases.create(
        parent={"type": "page_id", "page_id": parent_id},
        title=[{"type": "text", "text": {"content": "Naver Real Estate Dashboard"}}],
        properties=_db_properties_schema(),
    )
    new_id: str = resp["id"]
    log.info("Created new Notion database. ID: %s", new_id)
    log.info(">> Set NOTION_DATABASE_ID=%s in .env and GitHub Secrets <<", new_id)
    return new_id


# ── Page property builders ─────────────────────────────────────────────────────

def _build_properties(summary: ComplexSummary) -> dict:
    name = f"{summary.complex_id} - {summary.date} - {summary.trade_type}"
    return {
        "Name": {"title": [{"text": {"content": name}}]},
        "Complex ID": {"rich_text": [{"text": {"content": summary.complex_id}}]},
        "Date": {"date": {"start": summary.date}},
        "Trade Type": {"select": {"name": summary.trade_type}},
        "Total Listings": {"number": summary.total_listings},
        "New Listings": {"number": summary.new_listings},
        "Removed Listings": {"number": summary.removed_listings},
        "Avg Price (만원)": {"number": round(summary.avg_price, 0)},
        "Avg Price Change": {"number": round(summary.avg_price_change, 0)},
        "Avg Price Change %": {"number": round(summary.avg_price_change_pct, 1)},
        "Min Price (만원)": {"number": summary.min_price},
        "Min Price Change": {"number": summary.min_price_change},
        "Lowest Listing": {
            "rich_text": [{"text": {"content": summary.lowest_listing[:2000]}}]
        },
    }


# ── Upsert logic ───────────────────────────────────────────────────────────────

def upsert_summary(notion: Client, db_id: str, summary: ComplexSummary) -> None:
    """Query for existing page with same complex_id + date + trade_type.

    Creates a new page if not found, otherwise updates the existing one.
    """
    # Query for existing row
    query_resp = notion.databases.query(
        database_id=db_id,
        filter={
            "and": [
                {
                    "property": "Complex ID",
                    "rich_text": {"equals": summary.complex_id},
                },
                {
                    "property": "Date",
                    "date": {"equals": summary.date},
                },
                {
                    "property": "Trade Type",
                    "select": {"equals": summary.trade_type},
                },
            ]
        },
    )

    properties = _build_properties(summary)
    results = query_resp.get("results", [])

    if results:
        page_id = results[0]["id"]
        notion.pages.update(page_id=page_id, properties=properties)
        log.info(
            "Updated Notion page: complex=%s date=%s trade=%s",
            summary.complex_id, summary.date, summary.trade_type,
        )
    else:
        notion.pages.create(
            parent={"database_id": db_id},
            properties=properties,
        )
        log.info(
            "Created Notion page: complex=%s date=%s trade=%s",
            summary.complex_id, summary.date, summary.trade_type,
        )


# ── Top-level entry point ─────────────────────────────────────────────────────

def write_summaries(summaries: list[ComplexSummary]) -> None:
    """Write all summaries to Notion with rate-limit throttling."""
    token = config.NOTION_TOKEN
    if not token:
        raise ValueError("Set NOTION_TOKEN in .env")

    notion = Client(auth=token)
    db_id = get_or_create_database(notion)

    if not summaries:
        log.info("No summaries to write")
        return

    for summary in summaries:
        upsert_summary(notion, db_id, summary)
        time.sleep(_RATE_LIMIT_SLEEP)

    log.info("Wrote %d summaries to Notion", len(summaries))
