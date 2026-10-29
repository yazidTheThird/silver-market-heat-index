"""Daily entry point: compute today's Market Heat Index, save it, rebuild the dashboard,
and (optionally) send a Telegram message.

    python run.py
"""
from __future__ import annotations

import logging
import os

import requests
import yaml

from mhi import dashboard
from mhi.index import compute, save

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("mhi")


def notify(row: dict) -> None:
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return
    parts = [f"{k.replace('score_', '')}: {round(v) if v is not None else 'n/a'}"
             for k, v in row.items() if k.startswith("score_")]
    text = (f"Market Heat Index {row['date']}\n"
            f"{row['index']} / 100 — {row['label']}\n" + "\n".join(parts))
    url = os.getenv("DASHBOARD_URL")
    if url:
        text += f"\n{url}"
    try:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=20)
    except Exception as e:  # noqa: BLE001
        log.warning("telegram: %s", e)


def main() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "config.yaml"), encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    out = compute(cfg)
    hist = save(out["row"])
    path = dashboard.build(hist, cfg)
    log.info("dashboard written to %s", path)
    notify(out["row"])


if __name__ == "__main__":
    main()
