"""Shared helpers."""
from __future__ import annotations

import logging
from typing import Iterable, Optional

log = logging.getLogger("mhi")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def percentile(value: float, history: Iterable[float]) -> Optional[float]:
    """Where `value` sits in `history`, 0 (coldest ever) .. 100 (hottest ever)."""
    vals = [h for h in history if h is not None and h == h]  # drop None/NaN
    if not vals or value is None or value != value:
        return None
    below = sum(1 for h in vals if h < value)
    equal = sum(1 for h in vals if h == value)
    return round(100.0 * (below + 0.5 * equal) / len(vals), 1)


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))
