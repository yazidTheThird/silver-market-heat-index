"""Combines source scores into the Market Heat Index and keeps the history."""
from __future__ import annotations

import datetime as dt
import os

import pandas as pd

from . import sources
from .util import log

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
HISTORY = os.path.join(ROOT, "data", "history.csv")
COMPETING = os.path.join(ROOT, "data", "competing_releases.csv")

COMPONENTS = ["drops", "ebay", "attention", "silver", "calendar"]


def load_history() -> pd.DataFrame:
    if os.path.exists(HISTORY):
        return pd.read_csv(HISTORY)
    return pd.DataFrame()


def label(index: float, cfg: dict) -> str:
    t = cfg["thresholds"]
    if index >= t["hot"]:
        return "HOT"
    if index < t["dead"]:
        return "DEAD"
    return "NORMAL"


def combine(results: dict, cfg: dict) -> tuple[float | None, float]:
    """Weighted mean of the components that returned a score.
    Returns (index, coverage) where coverage = share of total weight that had data."""
    w = cfg["weights"]
    total_w = sum(w[c] for c in COMPONENTS)
    got = [(results[c]["score"], w[c]) for c in COMPONENTS if results[c]["score"] is not None]
    if not got:
        return None, 0.0
    used_w = sum(wt for _, wt in got)
    index = sum(s * wt for s, wt in got) / used_w
    return round(index, 1), round(used_w / total_w, 2)


def compute(cfg: dict, today: dt.date | None = None) -> dict:
    today = today or dt.datetime.utcnow().date()
    hist = load_history()
    if not hist.empty:
        hist = hist[hist["date"] != today.isoformat()]  # re-runs replace the day
    competing = pd.read_csv(COMPETING) if os.path.exists(COMPETING) else None

    results = {}
    results["drops"] = sources.drops(cfg, hist, today)
    results["silver"] = sources.silver(cfg, hist)
    spot = results["silver"]["raw"].get("silver_spot")
    results["ebay"] = sources.ebay(cfg, hist, spot)
    results["attention"] = sources.attention(cfg, hist)
    new_drops = results["drops"]["raw"].get("drops_new_7d", 0) or 0
    results["calendar"] = sources.calendar(cfg, today, competing, auto_new_drops=new_drops)

    index, coverage = combine(results, cfg)
    if index is None:
        lab = "NO DATA"
    elif coverage < cfg.get("min_coverage", 0.5):
        lab = "LOW DATA"   # too few sources answered today to trust a verdict
    else:
        lab = label(index, cfg)
    row = {"date": today.isoformat(), "index": index, "label": lab, "coverage": coverage}
    for c in COMPONENTS:
        row[f"score_{c}"] = results[c]["score"]
        row.update(results[c]["raw"])
    for c in COMPONENTS:
        log.info("%-9s %6s  %s", c, results[c]["score"], results[c]["note"])
    log.info("INDEX %s (%s), coverage %.0f%%", index, row["label"], coverage * 100)
    return {"row": row, "results": results}


def save(row: dict) -> pd.DataFrame:
    hist = load_history()
    if not hist.empty:
        hist = hist[hist["date"] != row["date"]]
    hist = pd.concat([hist, pd.DataFrame([row])], ignore_index=True)
    hist = hist.sort_values("date")
    os.makedirs(os.path.dirname(HISTORY), exist_ok=True)
    hist.to_csv(HISTORY, index=False)
    return hist
