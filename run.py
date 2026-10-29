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

_HERE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(_HERE, "data"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO, format="%(levelname)s %(message)s",
    handlers=[logging.StreamHandler(),
              # Saved in the repo so the latest run's details can be read any time.
              logging.FileHandler(os.path.join(_HERE, "data", "last_run_log.txt"),
                                  mode="w", encoding="utf-8")])
log = logging.getLogger("mhi")


def notify(row: dict) -> None:
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
