"""Data sources. Every function returns a dict:

    {"score": 0-100 or None, "raw": {metric: value}, "note": "short status"}

A source that fails returns score=None and the index is computed from the rest.
`hist` is the past history as a pandas DataFrame (one row per day).

The index is built around COLORIZED collectibles. Plain silver price is only a
background factor.
"""
from __future__ import annotations

import base64
import datetime as dt
import os
import re
import statistics
import time

import pandas as pd
import requests

from .util import BROWSER_HEADERS, clamp, log, percentile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _hist_pct(value, hist: pd.DataFrame, col: str, cfg: dict, fallback=None):
    """Percentile of today's value against the same metric over the lookback window."""
    if value is None or hist is None or col not in hist.columns:
        return fallback
    series = hist[col].dropna().tail(cfg["lookback_days"])
    if len(series) < cfg["min_history_days"]:
        return fallback
    return percentile(value, series.tolist())


def _fail(note: str) -> dict:
    log.warning(note)
    return {"score": None, "raw": {}, "note": note}


def _is_colorized(text: str, cfg: dict) -> bool:
    return re.search(cfg["colorized_pattern"], text or "", re.I) is not None


# ============================================================ 1. COLORIZED DROPS
def drops(cfg: dict, hist: pd.DataFrame, today: dt.date) -> dict:
    """How fast colorized launches sell out at the stores you track (any platform —
    see mhi/drops.py). The most direct measure of colorized demand."""
    from . import drops as tracker

    try:
        state, stores_ok, _ = tracker.run_tracker(cfg, today)
    except Exception as e:  # noqa: BLE001
        return _fail(f"drops: {e}")
    if stores_ok == 0:
        return _fail("drops: no store could be read — see the log and README")
    return _drop_metrics(state, cfg, hist, today, stores_ok, tracker)


def _drop_metrics(state, cfg, hist, today, stores_ok, tracker) -> dict:
    from .evidence import availability
    report = availability(state, cfg, today)
    return {"score": None, "raw": {"drops_tracked_all": len(state),
            "drops_stores_ok": stores_ok, "drops_fresh_listings": report["fresh_listings"]},
            "note": "Availability cohorts only; no inferred unit sales or composite score"}


# =============================================================== 2. eBay COLORIZED
def _ebay_token(client_id: str, secret: str) -> str:
    auth = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={"Authorization": f"Basic {auth}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials",
              "scope": "https://api.ebay.com/oauth/api_scope"},
        timeout=30,
    )
    if r.status_code != 200:
        try:
            body = r.json()
            why = f'{body.get("error")}: {body.get("error_description")}'
        except ValueError:
            why = r.text[:200]
        # 401 invalid_client = wrong App ID / Cert ID pair, or the Production keyset
        # isn't enabled yet (eBay disables it until the account-deletion
        # notification step is completed or an exemption is filed).
        raise RuntimeError(f"eBay rejected the keys (HTTP {r.status_code}) — {why}")
    return r.json()["access_token"]


def _ebay_search(token: str, q: str, ecfg: dict) -> tuple[int, list]:
    r = requests.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers={"Authorization": f"Bearer {token}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
        params={"q": q, "category_ids": ecfg["category_id"],
                "limit": min(200, ecfg["max_items_per_query"]),
                "filter": "buyingOptions:{FIXED_PRICE}"},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    items = []
    for it in data.get("itemSummaries", []):
        try:
            items.append((it.get("title", ""), float(it["price"]["value"])))
        except (KeyError, ValueError):
            pass
    return int(data.get("total", 0)), items


def ebay(cfg: dict, hist: pd.DataFrame, spot: float | None) -> dict:
    """Collect asking-price and active-supply context; never infer purchases."""
    ecfg = cfg["ebay"]
    cid = (os.getenv("EBAY_CLIENT_ID") or "").strip()
    sec = (os.getenv("EBAY_CLIENT_SECRET") or "").strip()
    raw, parts = {}, []
    if not (cid and sec):
        log.info("ebay api: skipped — EBAY_CLIENT_ID set: %s, EBAY_CLIENT_SECRET set: %s",
                 bool(cid), bool(sec))

    if cid and sec:
        try:
            token = _ebay_token(cid, sec)
            ratios, supply = [], 0
            for pair in ecfg["pairs"]:
                n_col, col = _ebay_search(token, pair["colorized"], ecfg)
                _, plain = _ebay_search(token, pair["plain"], ecfg)
                col_p = [p for t, p in col if _is_colorized(t, cfg)]
                plain_p = [p for t, p in plain if not _is_colorized(t, cfg)]
                supply += n_col
                if len(col_p) >= 5 and len(plain_p) >= 5:
                    ratios.append(statistics.median(col_p) / statistics.median(plain_p))
                time.sleep(0.5)
            if ratios:
                prem = statistics.median(ratios)
                raw.update({"ebay_collector_premium": round(prem, 3),
                            "ebay_colorized_listings": supply})
        except Exception as e:  # noqa: BLE001
            log.warning("ebay api: %s", e)

    return {"score": None, "raw": raw,
            "note": "Asking prices/listing supply only; completed purchases are reported separately"}



# ============================================== 3. ATTENTION (colorized chatter)
def attention(cfg: dict, hist: pd.DataFrame) -> dict:
    acfg = cfg["attention"]
    raw, parts = {}, []

    # Reddit: posts mentioning colorized coins in the past week, and their comments.
    try:
        posts, comments = _reddit_colorized(acfg["subreddits"], acfg["reddit_query"])
        activity = posts + 0.2 * comments
        raw.update({"reddit_colorized_posts_7d": posts,
                    "reddit_colorized_activity": round(activity, 1)})
        parts.append(_hist_pct(activity, hist, "reddit_colorized_activity", cfg, fallback=None))
    except Exception as e:  # noqa: BLE001
        log.warning("reddit: %s", e)

    # Google Trends: niche terms are noisy, so it counts for less than Reddit.
    try:
        from pytrends.request import TrendReq

        tr = TrendReq(hl="en-US", tz=0, timeout=(10, 30))  # no retries arg: breaks on urllib3 v2
        tr.build_payload(acfg["trends_keywords"], timeframe="today 12-m", geo=acfg["trends_geo"])
        df = tr.interest_over_time()
        if df is not None and not df.empty:
            series = df[acfg["trends_keywords"]].mean(axis=1)
            if series.sum() > 0:
                recent = float(series.tail(2).mean())
                raw["trends_colorized_interest"] = round(recent, 1)
                parts.append(percentile(recent, series.tolist()))
    except Exception as e:  # noqa: BLE001
        log.warning("google trends: %s", e)

    parts = [p for p in parts if p is not None]
    if not parts:
        return {"score": None, "raw": raw, "note": "attention: building history"}
    # Reddit first in the list when present: weight it 2:1 over Trends.
    score = parts[0] if len(parts) == 1 else (2 * parts[0] + parts[1]) / 3
    return {"score": round(score, 1), "raw": raw, "note": "ok"}


def _reddit_colorized(subreddits: list[str], query: str) -> tuple[int, int]:
    cid, sec = os.getenv("REDDIT_CLIENT_ID"), os.getenv("REDDIT_CLIENT_SECRET")
    headers = {"User-Agent": "market-heat-index/1.1 (personal research script)"}
    base = "https://www.reddit.com"
    if cid and sec:
        tok = requests.post(f"{base}/api/v1/access_token", auth=(cid, sec),
                            data={"grant_type": "client_credentials"},
                            headers=headers, timeout=30).json()["access_token"]
        headers["Authorization"] = f"bearer {tok}"
        base = "https://oauth.reddit.com"
    posts = comments = 0
    for sub in subreddits:
        r = requests.get(f"{base}/r/{sub}/search.json",
                         params={"q": query, "restrict_sr": 1, "sort": "new",
                                 "t": "week", "limit": 100},
                         headers=headers, timeout=30)
        r.raise_for_status()
        for child in r.json()["data"]["children"]:
            posts += 1
            comments += int(child["data"].get("num_comments", 0))
        time.sleep(1)
    return posts, comments


# ======================================================= 4. SILVER (background)
def silver(cfg: dict, hist: pd.DataFrame) -> dict:
    """Silver price momentum & volatility — background mood of the buyer pool."""
    try:
        import yfinance as yf

        df = yf.download(cfg["silver"]["ticker"], period="18mo", interval="1d",
                         progress=False, auto_adjust=False)
        if df is None or df.empty:
            return _fail("silver: no price data returned")
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return silver_from_prices(close.dropna())
    except Exception as e:  # noqa: BLE001
        return _fail(f"silver: {e}")


def silver_from_prices(close: pd.Series) -> dict:
    rets = close.pct_change()
    ret7 = close.pct_change(5)
    ret30 = close.pct_change(21)
    vol30 = rets.rolling(21).std() * (252 ** 0.5)
    window = 252
    s_abs7 = percentile(abs(ret7.iloc[-1]), ret7.abs().tail(window).tolist())
    s_vol = percentile(vol30.iloc[-1], vol30.tail(window).tolist())
    s_ret30 = percentile(ret30.iloc[-1], ret30.tail(window).tolist())
    if None in (s_abs7, s_vol, s_ret30):
        return _fail("silver: not enough price history")
    return {
        "score": round(0.4 * s_abs7 + 0.3 * s_vol + 0.3 * s_ret30, 1),
        "raw": {
            "silver_spot": round(float(close.iloc[-1]), 2),
            "silver_ret7_pct": round(100 * float(ret7.iloc[-1]), 2),
            "silver_ret30_pct": round(100 * float(ret30.iloc[-1]), 2),
            "silver_vol30_pct": round(100 * float(vol30.iloc[-1]), 1),
        },
        "note": "ok",
    }


# ===================================================================== 5. CALENDAR
def calendar(cfg: dict, today: dt.date, competing: pd.DataFrame | None,
             auto_new_drops: int = 0, hist: pd.DataFrame | None = None) -> dict:
    """Paydays, season, weekday, and how crowded the release calendar is.
    Competing drops = ones you log by hand + new colorized launches the tracker saw."""
    ccfg = cfg["calendar"]
    days_since_payday = today.day - 15 if today.day >= 15 else today.day - 1
    payday = clamp(100 - days_since_payday * 6)
    season = float(ccfg["season"][today.month])
    weekday = float(ccfg["weekday"][today.weekday()])
    n_manual = 0
    if competing is not None and not competing.empty:
        d = pd.to_datetime(competing["date"], errors="coerce").dt.date.dropna()
        win = ccfg["competing_window_days"]
        n_manual = int(sum(abs((x - today).days) <= win for x in d))
    # Auto-detected launches only count as "crowded" when this week has more than
    # usual for the stores you track (their own median, once 14+ days are logged).
    usual = None
    if hist is not None and "drops_new_7d" in hist.columns:
        past = pd.to_numeric(hist["drops_new_7d"], errors="coerce").dropna().tail(90)
        if len(past) >= cfg["min_history_days"]:
            usual = float(past.median())
    extra = max(0.0, auto_new_drops - usual) if usual is not None else 0.0
    crowding = n_manual + 0.5 * extra
    score = clamp(0.4 * payday + 0.35 * season + 0.25 * weekday
                  - crowding * ccfg["competing_penalty"])
    return {
        "score": round(score, 1),
        "raw": {"cal_payday": payday, "cal_season": season, "cal_weekday": weekday,
                "competing_drops_manual": n_manual},
        "note": "ok",
    }
