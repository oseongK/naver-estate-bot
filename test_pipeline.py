"""
Mock pipeline test — bypasses the scraper and runs Sheets + Notion
with synthetic Listing data.

Usage:
    python test_pipeline.py
"""

from __future__ import annotations

from datetime import date, timedelta

import config
import notion_handler
import sheets_handler
from main import compute_summary
from models import ComplexSummary, Listing
from utils import get_logger

log = get_logger("test_pipeline")

TODAY = date.today().isoformat()


def make_mock_listings() -> dict[str, list[Listing]]:
    """Generate a small set of synthetic listings for each complex × trade type."""
    complexes = config.COMPLEX_IDS
    trade_types = config.TRADE_TYPES

    sample_data = {
        "A1": [
            {"price": 120000, "monthly_rent": 0, "area_m2": 84.9, "floor": 5,
             "total_floors": 15, "direction": "남향", "article_name": "래미안", "agent_name": "하나부동산"},
            {"price": 135000, "monthly_rent": 0, "area_m2": 101.2, "floor": 10,
             "total_floors": 15, "direction": "동향", "article_name": "래미안", "agent_name": "미래부동산"},
            {"price": 98000,  "monthly_rent": 0, "area_m2": 59.9, "floor": 2,
             "total_floors": 15, "direction": "남서향", "article_name": "래미안", "agent_name": "한국부동산"},
        ],
        "B1": [
            {"price": 60000,  "monthly_rent": 0, "area_m2": 84.9, "floor": 7,
             "total_floors": 15, "direction": "남향", "article_name": "전세매물", "agent_name": "하나부동산"},
            {"price": 55000,  "monthly_rent": 0, "area_m2": 59.9, "floor": 3,
             "total_floors": 15, "direction": "북향", "article_name": "전세매물", "agent_name": "미래부동산"},
        ],
        "B2": [
            {"price": 10000,  "monthly_rent": 80, "area_m2": 59.9, "floor": 4,
             "total_floors": 15, "direction": "남향", "article_name": "월세매물", "agent_name": "한국부동산"},
            {"price": 5000,   "monthly_rent": 120, "area_m2": 84.9, "floor": 8,
             "total_floors": 15, "direction": "동향", "article_name": "월세매물", "agent_name": "하나부동산"},
        ],
    }

    results: dict[str, list[Listing]] = {}
    listing_counter = 1

    for idx, complex_id in enumerate(complexes):
        results[complex_id] = []
        for trade_type in trade_types:
            if trade_type not in sample_data:
                continue
            for i, d in enumerate(sample_data[trade_type]):
                listing = Listing(
                    listing_id=f"MOCK{listing_counter:04d}",
                    complex_id=complex_id,
                    trade_type=trade_type,
                    date=TODAY,
                    price=d["price"] + idx * 5000,   # slight variation per complex
                    monthly_rent=d["monthly_rent"],
                    area_m2=d["area_m2"],
                    floor=d["floor"],
                    total_floors=d["total_floors"],
                    direction=d["direction"],
                    article_name=d["article_name"],
                    agent_name=d["agent_name"],
                    confirmed_type="중개사확인",
                    description="테스트 매물입니다.",
                    tags="테스트,mock",
                )
                results[complex_id].append(listing)
                listing_counter += 1

    total = sum(len(v) for v in results.values())
    log.info("Generated %d mock listings across %d complexes", total, len(complexes))
    return results


def run_test() -> None:
    complex_ids = config.COMPLEX_IDS
    trade_types = config.TRADE_TYPES

    log.info("=== Mock Pipeline Test Start ===")
    log.info("Complexes: %s  Trade types: %s", complex_ids, trade_types)

    # Step 1 — generate mock listings (no scraping)
    results = make_mock_listings()

    # Step 2 — write to Google Sheets
    all_listings = [l for listings in results.values() for l in listings]
    log.info("Writing %d mock listings to Google Sheets...", len(all_listings))
    sheets_handler.write_listings(all_listings)
    log.info("Sheets write OK")

    # Step 3 — compute summaries (no yesterday data on first run — that's fine)
    sh = sheets_handler.get_spreadsheet()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    summaries: list[ComplexSummary] = []
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
                "Summary: complex=%s trade=%s total=%d new=%d avg=%.0f min=%d",
                complex_id, trade_type,
                summary.total_listings, summary.new_listings,
                summary.avg_price, summary.min_price,
            )

    # Step 4 — write summaries to Notion
    log.info("Writing %d summaries to Notion...", len(summaries))
    notion_handler.write_summaries(summaries)
    log.info("Notion write OK")

    log.info("=== Mock Pipeline Test Complete ===")


if __name__ == "__main__":
    run_test()
