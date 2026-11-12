"""New-release news for the gallery, from coin news sites (config: news.sources).

Reads a WordPress site's public post list (/wp-json/wp/v2/posts) and keeps the
last `window_days` of posts in data/news.csv: source, id, date, title, link, image.
Falls back to the site's RSS feed (/feed/) when the post list is closed.
News never enters the tracker state or the market index.
"""
from __future__ import annotations

import csv
import datetime as dt
import html
import json
import os
import re

from . import media
from .util import BROWSER_HEADERS, log

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PATH = os.path.join(ROOT, "data", "news.csv")
COLS = ["source", "id", "date", "title", "link", "image"]
FIELDS = "id,date_gmt,link,title,yoast_head_json.og_image,jetpack_featured_media_url"


def _text(s) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", str(s or ""))).split())[:200]


def _utc(text: str) -> str:
    """A WordPress/RSS time as 2026-11-12T13:21:21Z, or ""."""
    text = (text or "").strip()
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            from email.utils import parsedate_to_datetime
            when = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_wp_posts(posts) -> list[dict]:
    out = []
    for p in posts if isinstance(posts, list) else []:
        if not isinstance(p, dict):
            continue
        og = ((p.get("yoast_head_json") or {}).get("og_image") or [{}])
        image = media.clean((og[0] or {}).get("url") if isinstance(og, list) and og else "") \
            or media.clean(p.get("jetpack_featured_media_url"))
        title = _text((p.get("title") or {}).get("rendered") if isinstance(p.get("title"), dict) else p.get("title"))
        when = _utc(str(p.get("date_gmt") or "") + ("Z" if p.get("date_gmt") else ""))
        link = str(p.get("link") or "")
        if title and when and link.startswith("https://"):
            out.append({"id": str(p.get("id", link)), "date": when, "title": title, "link": link, "image": image})
    return out


def from_rss(xml: str) -> list[dict]:
    out = []
    for block in re.findall(r"<item>(.*?)</item>", xml or "", re.S):
        def tag(name):
            m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", block, re.S)
            return re.sub(r"^<!\[CDATA\[|\]\]>$", "", m.group(1).strip()) if m else ""
        link = tag("link").strip()
        img = re.search(r"<img[^>]+src=[\"']([^\"']+)", html.unescape(tag("content:encoded") or tag("description")))
        title, when = _text(tag("title")), _utc(tag("pubDate"))
        if title and when and link.startswith("https://"):
            out.append({"id": link, "date": when, "title": title, "link": link,
                        "image": media.clean(img.group(1)) if img else ""})
    return out


def read_source(src: dict, get) -> list[dict]:
    base = src["url"].rstrip("/")
    try:
        code, text = get(f"{base}/wp-json/wp/v2/posts", params={"per_page": 50, "_fields": FIELDS})
        if code == 200:
            posts = from_wp_posts(json.loads(text))
            if posts:
                return posts
        log.info("news: %s post list -> HTTP %s, trying the RSS feed", base, code)
    except Exception as e:  # noqa: BLE001
        log.info("news: %s post list unreadable (%s), trying the RSS feed", base, e)
    code, text = get(f"{base}/feed/")
    if code != 200:
        raise RuntimeError(f"RSS feed HTTP {code}")
    return from_rss(text)


def load(path: str | None = None) -> list[dict]:
    path = path or PATH
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("title") and r.get("date")]


def save(rows: list[dict], path: str | None = None) -> None:
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["source"], r["date"]), reverse=True):
            w.writerow(r)
    os.replace(temp, path)


def collect(cfg: dict, get=None, now: dt.datetime | None = None, path: str | None = None) -> int:
    """Refresh data/news.csv from every configured source. Returns posts kept."""
    news_cfg = (cfg or {}).get("news") or {}
    sources = news_cfg.get("sources") or []
    if not sources:
        return 0
    if get is None:
        import requests

        def get(url, params=None):
            r = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=30)
            return r.status_code, r.text
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = (now - dt.timedelta(days=int(news_cfg.get("window_days", 90)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = {(r["source"], r["id"]): r for r in load(path)}
    for src in sources:
        name = src["url"].rstrip("/")
        try:
            posts = read_source(src, get)
            for p in posts:
                kept[(name, p["id"])] = {"source": name, **p}
            log.info("news: %s -> %d posts", name, len(posts))
        except Exception as e:  # noqa: BLE001
            log.warning("news: %s skipped — %s", name, e)
    rows = [r for r in kept.values() if r["date"] >= cutoff]
    save(rows, path)
    return len(rows)
