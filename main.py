"""
CLI orchestrator: scrape → sheets → notion.

Usage:
    python main.py                        # Full pipeline
    python main.py --complex-ids 8928     # Override complex IDs
    python main.py --scrape-only          # Skip Sheets & Notion writes
    python main.py --sheets-only          # Use cached scrape (not yet implemented)
    python main.py --notion-only          # Skip scrape and sheets
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta

import config
import notion_handler
import sheets_handler
from models import ComplexSummary, Listing
from utils import get_logger

log = get_logger("main")


# ── Delta computation ─────────────────────────────────────────────────────────

def compute_summary(
    complex_id: str,
    trade_type: str,
    today_listings: list[Listing],
    yesterday_rows: list[dict],
) -> ComplexSummary:
    """Compute ComplexSummary with delta stats vs yesterday."""
    today = date.today().isoformat()

    today_ids = {l.listing_id for l in today_listings}
    yesterday_ids = {str(r.get("listing_id", "")) for r in yesterday_rows if r.get("listing_id")}

    new_listings = len(today_ids - yesterday_ids)
    removed_listings = len(yesterday_ids - today_ids)

    # Price computation — use 'price' field (deposit for B2)
    today_prices = [l.price for l in today_listings if l.price > 0]
    avg_price = sum(today_prices) / len(today_prices) if today_prices else 0.0
    min_price = min(today_prices) if today_prices else 0

    # Yesterday averages
    y_prices = [
        int(r.get("price", 0))
        for r in yesterday_rows
        if r.get("price") and str(r["price"]).isdigit() and int(r["price"]) > 0
    ]
    y_avg = sum(y_prices) / len(y_prices) if y_prices else 0.0
    y_min = min(y_prices) if y_prices else 0

    avg_change = avg_price - y_avg
    avg_change_pct = (avg_change / y_avg * 100) if y_avg else 0.0
    min_change = min_price - y_min

    # Build lowest listing description
    lowest: Listing | None = None
    for l in today_listings:
        if l.price > 0 and (lowest is None or l.price < lowest.price):
            lowest = l

    lowest_str = ""
    if lowest:
        price_label = (
            f"{lowest.price}만원/{lowest.monthly_rent}만원"
            if trade_type == "B2"
            else f"{lowest.price}만원"
        )
        lowest_str = (
            f"{lowest.floor}층 / {lowest.area_m2}㎡ / {price_label} / {lowest.agent_name}"
        )

    return ComplexSummary(
        complex_id=complex_id,
        date=today,
        trade_type=trade_type,
        total_listings=len(today_listings),
        new_listings=new_listings,
        removed_listings=removed_listings,
        avg_price=avg_price,
        avg_price_change=avg_change,
        avg_price_change_pct=round(avg_change_pct, 1),
        min_price=min_price,
        min_price_change=min_change,
        lowest_listing=lowest_str,
    )


# ── CLI argument parsing ───────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Naver Real Estate pipeline")
    parser.add_argument(
        "--complex-ids",
        nargs="+",
        default=None,
        help="Override COMPLEX_IDS from config (space-separated)",
    )
    parser.add_argument(
        "--trade-types",
        nargs="+",
        default=None,
        help="Override TRADE_TYPES from config",
    )
    parser.add_argument(
        "--scrape-only",
        action="store_true",
        help="Only scrape — skip Sheets and Notion writes",
    )
    parser.add_argument(
        "--sheets-only",
        action="store_true",
        help="Skip scrape and Notion — only write to Sheets (requires --listings-file)",
    )
    parser.add_argument(
        "--notion-only",
        action="store_true",
        help="Skip scrape and Sheets — only write summaries to Notion",
    )
    return parser.parse_args()


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run(args: argparse.Namespace) -> None:
    complex_ids = args.complex_ids or config.COMPLEX_IDS
    trade_types = args.trade_types or config.TRADE_TYPES

    log.info(
        "Pipeline start — complexes=%s trade_types=%s",
        complex_ids, trade_types,
    )

    # ── Step 1: Scrape ─────────────────────────────────────────────────────────
    results: dict[str, list[Listing]] = {}
    if not args.sheets_only and not args.notion_only:
        from scraper import run_scraper
        results = await run_scraper(complex_ids, trade_types)
    else:
        log.info("Skipping scrape step")

    if args.scrape_only:
        log.info("--scrape-only: done.")
        return

    # ── Step 2: Write to Google Sheets ────────────────────────────────────────
    if not args.notion_only:
        all_listings = [l for listings in results.values() for l in listings]
        log.info("Writing %d total listings to Google Sheets", len(all_listings))
        sheets_handler.write_listings(all_listings)

    # ── Step 3: Compute summaries & write to Notion ───────────────────────────
    summaries: list[ComplexSummary] = []

    # Need spreadsheet handle for reading yesterday
    sh = sheets_handler.get_spreadsheet()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    for complex_id in complex_ids:
        complex_listings = results.get(complex_id, [])

        for trade_type in trade_types:
            type_listings = [l for l in complex_listings if l.trade_type == trade_type]

            yesterday_rows = sheets_handler.read_worksheet(sh, yesterday)
            yesterday_rows = [
                r for r in yesterday_rows
                if str(r.get("complex_id")) == complex_id
                and r.get("trade_type") == trade_type
            ]

            summary = compute_summary(complex_id, trade_type, type_listings, yesterday_rows)
            summaries.append(summary)
            log.info(
                "Summary: complex=%s trade=%s total=%d new=%d removed=%d avg=%.0f",
                complex_id, trade_type,
                summary.total_listings, summary.new_listings,
                summary.removed_listings, summary.avg_price,
            )

    notion_handler.write_summaries(summaries)
    log.info("Pipeline complete.")


def main() -> None:
    args = parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
