"""Shared utilities: logger, sleep helpers."""

import asyncio
import logging
import random
import time

import config

# ── Logger ─────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


# ── Sleep helpers ──────────────────────────────────────────────────────────────

def random_sleep(min_s: float | None = None, max_s: float | None = None) -> None:
    """Synchronous random sleep to avoid rate-limit detection."""
    lo = min_s if min_s is not None else config.SLEEP_MIN
    hi = max_s if max_s is not None else config.SLEEP_MAX
    duration = random.uniform(lo, hi)
    get_logger("utils").debug("Sleeping %.2fs", duration)
    time.sleep(duration)


async def async_random_sleep(
    min_s: float | None = None, max_s: float | None = None
) -> None:
    """Async random sleep (non-blocking)."""
    lo = min_s if min_s is not None else config.SLEEP_MIN
    hi = max_s if max_s is not None else config.SLEEP_MAX
    duration = random.uniform(lo, hi)
    get_logger("utils").debug("Async sleeping %.2fs", duration)
    await asyncio.sleep(duration)
