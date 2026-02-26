"""
Playwright stealth scraper for Naver Real Estate.

Uses page.evaluate(fetch(...)) inside the browser context to call Naver's
internal XHR API — avoids DOM parsing fragility and satisfies auth cookies.
"""

from __future__ import annotations

import asyncio
import json
import random
from datetime import date
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import stealth_async

import config
from models import Listing
from utils import async_random_sleep, get_logger

log = get_logger("scraper")

# Trade-type human labels
TRADE_LABELS = {"A1": "매매", "B1": "전세", "B2": "월세"}

# User-agent pool
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]


# ── Price parsing ──────────────────────────────────────────────────────────────

def _parse_korean_price(s: str) -> int:
    """Convert Korean price string to 만원 integer.

    Examples:
        '15억'      → 150000
        '15억 5000' → 155000
        '5,000'     → 5000
        '5000'      → 5000
    """
    s = s.strip().replace(",", "").replace(" ", "")
    if not s:
        return 0
    if "억" in s:
        parts = s.split("억")
        eok = int(parts[0]) * 10000
        remainder = int(parts[1]) if parts[1].isdigit() and parts[1] else 0
        return eok + remainder
    try:
        return int(s)
    except ValueError:
        return 0


def _parse_price_field(raw: str, trade_type: str) -> tuple[int, int]:
    """Return (price_만원, monthly_rent_만원).

    B2 format: '5,000/50'  → deposit=5000, monthly=50
    A1/B1:     '15억5000'  → price=155000, monthly=0
    """
    raw = (raw or "").strip()
    if trade_type == "B2" and "/" in raw:
        parts = raw.split("/", 1)
        deposit = _parse_korean_price(parts[0])
        monthly = _parse_korean_price(parts[1])
        return deposit, monthly
    return _parse_korean_price(raw), 0


# ── Browser setup ──────────────────────────────────────────────────────────────

async def build_browser_context(browser: Browser) -> BrowserContext:
    """Create a stealth Chromium context with randomised UA."""
    ua = random.choice(_USER_AGENTS)
    kwargs: dict = dict(
        user_agent=ua,
        viewport={"width": 1366 + random.randint(0, 200), "height": 768 + random.randint(0, 100)},
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        extra_http_headers={
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
    )
    if config.PROXY_URL:
        kwargs["proxy"] = {"server": config.PROXY_URL}
        log.info("Using proxy: %s", config.PROXY_URL)
    context = await browser.new_context(**kwargs)
    return context


async def warm_up_session(page: Page, complex_id: str) -> None:
    """Navigate complex page to set Naver cookies before XHR calls."""
    url = f"https://new.land.naver.com/complexes/{complex_id}"
    log.info("Warming up session for complex %s", complex_id)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await async_random_sleep(2.0, 4.0)
    except Exception as exc:
        log.warning("Warm-up navigation failed (non-fatal): %s", exc)


# ── XHR fetch via page.evaluate ───────────────────────────────────────────────

_NAVER_API = "https://new.land.naver.com/api/articles/complex/{complex_id}"
_NAVER_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://new.land.naver.com/",
}

_MAX_RETRIES = 3


async def fetch_articles_page(
    page: Page,
    complex_id: str,
    trade_type: str,
    page_num: int,
) -> dict[str, Any]:
    """Fetch one page of articles from Naver's XHR API.

    Uses page.evaluate so the request carries session cookies.
    Retries up to _MAX_RETRIES times on 429 / network errors.
    """
    url = _NAVER_API.format(complex_id=complex_id)
    params = {
        "realEstateType": "APT",
        "tradeType": trade_type,
        "page": str(page_num),
        "pageSize": "20",
        "complexNo": complex_id,
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{qs}"

    js = f"""
    async () => {{
        const resp = await fetch({json.dumps(full_url)}, {{
            method: 'GET',
            credentials: 'include',
            headers: {json.dumps(_NAVER_HEADERS)},
        }});
        if (!resp.ok) {{
            return {{ _status: resp.status, _error: resp.statusText }};
        }}
        const data = await resp.json();
        data._status = resp.status;
        return data;
    }}
    """

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result: dict = await page.evaluate(js)
        except Exception as exc:
            log.warning("Attempt %d/%d: evaluate error: %s", attempt, _MAX_RETRIES, exc)
            if attempt == _MAX_RETRIES:
                return {}
            await async_random_sleep(2.0 * attempt, 4.0 * attempt)
            continue

        status = result.get("_status", 200)
        if status == 429:
            wait = 5.0 * attempt
            log.warning("Rate-limited (429) on attempt %d — waiting %.0fs", attempt, wait)
            await asyncio.sleep(wait)
            continue
        if status and status >= 400:
            log.error("HTTP %d on %s", status, full_url)
            return {}
        return result

    return {}


# ── Article → Listing parser ───────────────────────────────────────────────────

def parse_article(article: dict, complex_id: str, today: str, trade_type: str) -> Listing | None:
    """Map a Naver API article dict to a Listing dataclass."""
    try:
        listing_id = str(article.get("articleNo", ""))
        if not listing_id:
            return None

        price_raw = article.get("dealOrWarrantPrc", "") or article.get("rentPrc", "")
        price, monthly = _parse_price_field(str(price_raw), trade_type)

        area_str = str(article.get("area2", article.get("area1", "0"))).replace("㎡", "").strip()
        try:
            area_m2 = float(area_str)
        except ValueError:
            area_m2 = 0.0

        floor_str = str(article.get("floorInfo", "0/0"))
        floor_parts = floor_str.split("/")
        try:
            floor = int(floor_parts[0].strip())
        except ValueError:
            floor = 0
        try:
            total_floors = int(floor_parts[1].strip()) if len(floor_parts) > 1 else 0
        except ValueError:
            total_floors = 0

        tags = article.get("tagList", [])
        tags_str = ",".join(tags) if isinstance(tags, list) else str(tags)

        return Listing(
            listing_id=listing_id,
            complex_id=complex_id,
            trade_type=trade_type,
            date=today,
            price=price,
            monthly_rent=monthly,
            area_m2=area_m2,
            floor=floor,
            total_floors=total_floors,
            direction=article.get("direction", ""),
            article_name=article.get("articleName", ""),
            agent_name=article.get("realtorName", ""),
            confirmed_type=article.get("articleConfirmYmd", ""),
            description=article.get("articleFeatureDesc", ""),
            tags=tags_str,
        )
    except Exception as exc:
        log.warning("parse_article failed for %s: %s", article.get("articleNo"), exc)
        return None


# ── Paginated scrape for one complex × trade_type ─────────────────────────────

async def scrape_complex(
    page: Page,
    complex_id: str,
    trade_type: str,
    today: str,
) -> list[Listing]:
    """Scrape all pages for one complex + trade type."""
    listings: list[Listing] = []
    page_num = 1
    max_listings = config.MAX_LISTINGS_PER_COMPLEX

    while len(listings) < max_listings:
        log.info(
            "Fetching complex=%s trade=%s page=%d (collected=%d)",
            complex_id, trade_type, page_num, len(listings),
        )
        data = await fetch_articles_page(page, complex_id, trade_type, page_num)

        articles: list[dict] = data.get("articleList", [])
        if not articles:
            log.info("No more articles at page %d — stopping", page_num)
            break

        for article in articles:
            listing = parse_article(article, complex_id, today, trade_type)
            if listing:
                listings.append(listing)

        # Check if there are more pages
        is_more = data.get("isMoreData", False)
        if not is_more:
            break

        page_num += 1
        await async_random_sleep()

    log.info(
        "complex=%s trade=%s → %d listings", complex_id, trade_type, len(listings)
    )
    return listings


# ── Top-level entry point ─────────────────────────────────────────────────────

async def run_scraper(
    complex_ids: list[str] | None = None,
    trade_types: list[str] | None = None,
) -> dict[str, list[Listing]]:
    """Scrape all complexes × trade types.

    Returns:
        dict mapping complex_id → list[Listing]  (all trade types combined)
    """
    ids = complex_ids or config.COMPLEX_IDS
    types = trade_types or config.TRADE_TYPES
    today = date.today().isoformat()

    results: dict[str, list[Listing]] = {cid: [] for cid in ids}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=config.HEADLESS)
        context = await build_browser_context(browser)

        try:
            page = await context.new_page()
            await stealth_async(page)

            for complex_id in ids:
                # Warm up once per complex
                await warm_up_session(page, complex_id)

                for trade_type in types:
                    try:
                        listings = await scrape_complex(page, complex_id, trade_type, today)
                        results[complex_id].extend(listings)
                    except Exception as exc:
                        log.error(
                            "Error scraping complex=%s trade=%s: %s",
                            complex_id, trade_type, exc,
                        )
                    await async_random_sleep()

        finally:
            await context.close()
            await browser.close()

    total = sum(len(v) for v in results.values())
    log.info("Scraping complete — total listings: %d", total)
    return results
