"""Daily entry point: compute today's Market Heat Index, save it, rebuild the dashboard,
and (optionally) send a Telegram message.

    python run.py          # daily run
    python run.py --fast   # every few hours: re-check new launches only, for hour-level
                           # sell-out timing (no index, no Telegram)
"""
from __future__ import annotations

import datetime as dt
import logging
import os
import sys

import requests
import yaml

import pandas as pd

from mhi import dashboard, tags
from mhi.index import compute, load_history, save

_HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(_HERE, "data"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              # Saved in the repo so the latest run's details can be read any time.
              logging.FileHandler(os.path.join(_HERE, "data", "last_run_log.txt"),
                                  mode="w", encoding="utf-8")])
log = logging.getLogger("mhi")


def notify(row: dict, extra: str = "") -> None:
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and chat):
        log.info("telegram: skipped — secret missing (TELEGRAM_BOT_TOKEN set: %s, "
                 "TELEGRAM_CHAT_ID set: %s)", bool(token), bool(chat))
        return
    parts = [f"{k.replace('score_', '')}: {round(v) if v is not None else 'n/a'}"
             for k, v in row.items() if k.startswith("score_")]
    text = (f"Market Heat Index {row['date']}\n"
            f"{row['index']} / 100 — {row['label']}\n" + "\n".join(parts))
    if extra:
        text += "\n\n" + extra
    url = os.getenv("DASHBOARD_URL")
    if url:
        text += f"\n{url}"
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=20)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 200 and body.get("ok"):
            log.info("telegram: message sent")
        else:
            # Telegram's own explanation, e.g. "Unauthorized" (wrong token) or
            # "Bad Request: chat not found" (wrong chat id / never pressed Start).
            log.warning("telegram: NOT sent — HTTP %s: %s", r.status_code,
                        body.get("description", r.text[:200]))
    except Exception as e:  # noqa: BLE001
        log.warning("telegram: NOT sent — %s", type(e).__name__)


def latest_spot() -> float | None:
    h = load_history()
    if h.empty or "silver_spot" not in h.columns:
        return None
    v = h["silver_spot"].dropna()
    return float(v.iloc[-1]) if len(v) else None


def refresh_groups(cfg: dict, today: dt.date) -> pd.DataFrame:
    """Re-rank themes / base coins / sizes from the tracker state."""
    from mhi.drops import STATE
    if not os.path.exists(STATE):
        return pd.DataFrame()
    try:
        groups = tags.hot_groups(pd.read_csv(STATE, dtype=str), cfg, today, latest_spot())
        log.info("hot groups: %d groups ranked -> data/hot_groups.csv", len(groups))
        return groups
    except Exception as e:  # noqa: BLE001
        log.warning("hot groups: failed — %s", e)
        return pd.DataFrame()


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    today = dt.datetime.utcnow().date()

    if "--fast" in sys.argv:
        from mhi.drops import run_tracker
        _, ok, _ = run_tracker(cfg, today, fast=True)
        log.info("fast check: %d stores read", ok)
        groups = refresh_groups(cfg, today)
        hist = load_history()
        if not hist.empty:
            dashboard.build(hist, cfg, groups)
        return

    out = compute(cfg)
    hist = save(out["row"])
    groups = refresh_groups(cfg, today)
    path = dashboard.build(hist, cfg, groups)
    log.info("dashboard written to %s", path)
    weekday = (cfg.get("hot_groups") or {}).get("digest_weekday", 0)   # 0 = Monday
    extra = tags.digest(groups) if today.weekday() == weekday else ""
    notify(out["row"], extra)


if __name__ == "__main__":
    main()
