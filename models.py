"""Dataclasses for Naver Real Estate scraping pipeline."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Listing:
    """Represents a single apartment listing from Naver Real Estate."""

    listing_id: str          # articleNo from Naver API
    complex_id: str          # complex (danji) ID
    trade_type: str          # A1=매매, B1=전세, B2=월세
    date: str                # ISO date YYYY-MM-DD

    # Price fields (all in 만원)
    price: int               # sale price (A1/B1) or deposit (B2)
    monthly_rent: int        # monthly rent 만원 (B2 only, else 0)

    # Property details
    area_m2: float           # exclusive area ㎡
    floor: int               # floor number
    total_floors: int        # total floors in building
    direction: str           # e.g. 남향, 동향

    # Listing metadata
    article_name: str        # listing title
    agent_name: str          # 중개사명
    confirmed_type: str      # e.g. '중개사확인'

    # Optional extras
    description: str = ""
    tags: str = ""           # comma-joined tags


@dataclass
class ComplexSummary:
    """Aggregated daily summary for one complex + trade type, written to Notion."""

    complex_id: str
    date: str
    trade_type: str

    total_listings: int = 0
    new_listings: int = 0
    removed_listings: int = 0

    avg_price: float = 0.0
    avg_price_change: float = 0.0
    avg_price_change_pct: float = 0.0

    min_price: int = 0
    min_price_change: int = 0
    lowest_listing: str = ""   # "{floor}층 / {area}㎡ / {price}만원 / {agent}"
