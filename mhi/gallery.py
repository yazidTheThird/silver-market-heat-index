"""Writes docs/releases.html — the new-releases gallery (GitHub Pages serves /docs).

One screen that shows, as pictures, what just appeared at every store the
tracker reads. Built from the saved tracker state (data/drops_state.csv) and
the picture addresses in data/media.csv; this module never touches the network.

What counts as a release here
  * a product the store published inside the window (Shopify gives the hour), or
  * a product the tracker first saw inside the window at a store that gives no
    date — unless that store "revealed" a large batch that day, which is the
    tracker discovering old catalogue, not a launch.
The page keeps the two apart ("Listed" vs "First spotted"). As on the dashboard,
a listing is not a sale and "unavailable" is not "sold".
"""
from __future__ import annotations

import collections
import csv
import datetime as dt
import html
import json
import os
import re

from . import media, tags
from .util import log

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE = os.path.join(ROOT, "data", "drops_state.csv")
HEALTH = os.path.join(ROOT, "data", "collection_health.csv")
OUT = os.path.join(ROOT, "docs", "releases.html")

DEFAULTS = {
    "window_days": 90,               # how far back the page goes
    "bulk_first_seen": 25,           # this many undated products "appearing" at one store
                                     # in one day = old catalogue being discovered
    "keep_pictures_extra_days": 30,  # pictures are kept a little longer than the window
}


def settings(cfg: dict) -> dict:
    user = (cfg or {}).get("gallery") or {}
    out = {}
    for key, default in DEFAULTS.items():
        try:
            out[key] = max(1, int(user.get(key, default)))
        except (TypeError, ValueError):
            out[key] = default
    return out


# ------------------------------------------------------------------ launches
def _s(x) -> str:
    return "" if x is None or (isinstance(x, float) and x != x) else str(x).strip()


def _utc(text) -> dt.datetime | None:
    """A timestamp that carries an hour, in UTC. None for a bare date or junk."""
    text = _s(text)
    if "T" not in text or len(text) < 16:
        return None
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return when.astimezone(dt.timezone.utc)


def _day(text) -> dt.date | None:
    try:
        return dt.date.fromisoformat(_s(text)[:10])
    except ValueError:
        return None


def _stamp(when: dt.datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def launch_of(row: dict) -> tuple[str, bool] | None:
    """When a product launched, and whether the store itself gave that date.

    Returns ("2026-10-29T12:56:50Z" or "2026-10-29", dated_by_store), or None when
    the launch is unknown (it was already in the catalogue when tracking began).
    """
    when = _utc(row.get("published_at"))
    if when:
        return _stamp(when), True
    day = _day(row.get("published"))
    if day:
        return day.isoformat(), True
    if _s(row.get("baseline")) in ("1", "1.0"):
        return None
    when = _utc(row.get("first_seen_at"))
    if when:
        return _stamp(when), False
    day = _day(row.get("first_seen"))
    return (day.isoformat(), False) if day else None


def _first_seen(row: dict) -> str:
    when = _utc(row.get("first_seen_at"))
    if when:
        return _stamp(when)
    day = _day(row.get("first_seen"))
    return day.isoformat() if day else ""


def _launches(rows: list[dict], cfg: dict, today: dt.date, days: int):
    """(row, when, dated_by_store) for every launch in the last `days` days."""
    threshold = settings(cfg)["bulk_first_seen"]
    found, batch = [], collections.Counter()
    for row in rows:
        launch = launch_of(row)
        if not launch:
            continue
        found.append((row, launch[0], launch[1]))
        if not launch[1]:
            batch[(_s(row.get("store")), launch[0][:10])] += 1
    first, last = today - dt.timedelta(days=days), today + dt.timedelta(days=1)
    for row, when, dated in found:
        day = _day(when)
        if day is None or not first <= day <= last:
            continue
        if not dated and batch[(_s(row.get("store")), when[:10])] >= threshold:
            continue
        yield row, when, dated


def recent_keys(rows, cfg: dict, today: dt.date) -> set:
    """(store, product_id) of every product whose picture is worth keeping."""
    s = settings(cfg)
    days = s["window_days"] + s["keep_pictures_extra_days"]
    return {(_s(row.get("store")), _s(row.get("product_id")))
            for row, _, _ in _launches(list(rows), cfg, today, days)}


# A year in a title: "2026 Niue …", "1885-CC Morgan", "(1973)". Not "$2000",
# "1/2000 oz", ".9999", "2000 mintage".
_YEAR = re.compile(r"(?<![\d$#/.,])(1[5-9]\d\d|20\d\d)"
                   r"(?!\d|[.,]\d|\s?(?:oz|g|gram|grams|mm|pcs|pieces|mintage|minted)\b)", re.I)


def issue_year(title: str, today: dt.date) -> int | None:
    """The latest year named in the title (the coin's date), if any."""
    years = [int(y) for y in _YEAR.findall(title or "") if int(y) <= today.year + 1]
    return max(years) if years else None


def _number(x) -> float | None:
    try:
        v = float(_s(x).replace(",", ""))
    except ValueError:
        return None
    return v if v > 0 and v == v and v != float("inf") else None


def _health() -> dict:
    if not os.path.exists(HEALTH):
        return {}
    with open(HEALTH, newline="", encoding="utf-8") as fh:
        return {_s(r.get("store")).rstrip("/"): _s(r.get("ok")).lower() == "true"
                for r in csv.DictReader(fh)}


def releases(rows: list[dict], cfg: dict, today: dt.date,
             pictures: dict | None = None, health: dict | None = None
             ) -> tuple[list[dict], list[dict]]:
    """(items, stores) for the page, newest first. Empty values are left out."""
    pictures, health = pictures or {}, health or {}
    rules = tags._rules(cfg)
    stores, position = [], {}

    def store_index(url: str) -> int:
        url = url.rstrip("/")
        if url not in position:
            position[url] = len(stores)
            entry = {"n": re.sub(r"^https?://(www\.)?", "", url), "u": url, "cur": "USD"}
            if url in health:
                entry["ok"] = health[url]
            stores.append(entry)
        return position[url]

    for store in ((cfg or {}).get("drops") or {}).get("stores", []):
        stores[store_index(store["url"])]["cur"] = store.get("currency", "USD")

    items = []
    for row, when, dated in _launches(rows, cfg, today, settings(cfg)["window_days"]):
        store = _s(row.get("store"))
        title = " ".join(html.unescape(_s(row.get("title"))).split())[:160]
        if not store or not title:
            continue
        tag = tags.tag(title, rules)
        url = _s(row.get("url"))
        pics = pictures.get((store, _s(row.get("product_id")))) or {}
        mintage = _number(row.get("mintage"))
        status = _s(row.get("stock_status"))
        item = {
            "t": title,
            "u": url if url.lower().startswith(("https://", "http://")) else "",
            "s": store_index(store),
            "d": when,
            "k": 1 if dated else None,
            "n": _first_seen(row),
            "c": None if _s(row.get("colorized")) in ("0", "0.0") else 1,
            "p": _number(row.get("price")),
            "m": int(mintage) if mintage else None,
            "a": 1 if status == "available" else 0 if status == "unavailable" else None,
            "y": issue_year(title, today),
            "th": [t for t in tag["themes"] if t != "Other"],
            "b": "Other" if tag["base_coin"].startswith("Other") else tag["base_coin"],
            "z": tag["size"], "f": tag["finish"], "me": tag["metal"],
            "i": pics.get("images") or [],
            "h": pics.get("thumb") or "",
        }
        items.append({k: v for k, v in item.items() if v not in (None, "", [])})
    items.sort(key=lambda it: it["t"])
    items.sort(key=lambda it: (it["d"][:10], it["d"]), reverse=True)
    return items, stores


# --------------------------------------------------------------------- page
def _read_state() -> list[dict]:
    if not os.path.exists(STATE):
        return []
    with open(STATE, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build(cfg: dict, now: dt.datetime | None = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date()
    s = settings(cfg)
    items, stores = releases(_read_state(), cfg, today, media.load(), _health())
    payload = {
        "meta": {"generated": _stamp(now), "window": s["window_days"],
                 "min_year": today.year - 1,
                 "fx": {k: float(v) for k, v in ((cfg or {}).get("fx_to_usd") or {}).items()}},
        "stores": stores,
        "items": items,
    }
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    # Titles come from other people's websites: keep them inert inside <script>.
    data = data.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    temp = OUT + ".tmp"
    with open(temp, "w", encoding="utf-8") as fh:
        fh.write(TEMPLATE.replace("__DATA__", data))
    os.replace(temp, OUT)
    log.info("gallery: %d releases in the last %d days, %d with a picture -> docs/releases.html",
             len(items), s["window_days"], sum(1 for it in items if it.get("i")))
    return OUT


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#eceef1" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0f141a" media="(prefers-color-scheme: dark)">
<title>New releases | Blackbird</title>
<style>
:root {
  color-scheme: light dark;
  --frost: #eceef1;     /* page: frosted silver */
  --capsule: #ffffff;   /* chips, sheets */
  --ink: #131a22;       /* blue-black, like a mirror field */
  --ink-2: #465160;
  --ink-3: #5d6876;
  --rim: #d0d6dd;
  --bill: #f5b70a;      /* the blackbird's bill: marks what is new */
  --on-bill: #1d1700;
  --photo: #ffffff;     /* behind every picture, in both themes */
  --blank: #d0d6dd;
  --shade: rgba(19, 26, 34, .58);
  --alert: #a4281b;
  --bar-h: 56px;
}
@media (prefers-color-scheme: dark) {
  :root {
    --frost: #0f141a; --capsule: #1a212a; --ink: #e9edf1; --ink-2: #b4bdc8;
    --ink-3: #8a95a3; --rim: #2c3540; --shade: rgba(0, 0, 0, .66); --alert: #ff9b8e;
  }
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
html:has(dialog[open]) { overflow: hidden; }
body { margin: 0; background: var(--frost); color: var(--ink);
  font: 15px/1.4 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif; }
button { font: inherit; color: inherit; -webkit-tap-highlight-color: transparent; }
a { color: inherit; }
:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.wrap { max-width: 1400px; margin: 0 auto; padding-left: 14px; padding-right: 14px; }

.top { padding-top: 18px; padding-bottom: 10px; }
.top-row { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
h1 { font-size: 25px; line-height: 1.15; letter-spacing: -0.02em; font-weight: 650; margin: 0; }
.back { font-size: 13px; color: var(--ink-2); white-space: nowrap; }
.status { margin: 4px 0 0; font-size: 13px; color: var(--ink-2); }
.status.stale { color: var(--alert); }

.bar { position: sticky; top: 0; z-index: 5; background: var(--frost); border-bottom: 1px solid var(--rim); }
.bar-in { height: var(--bar-h); display: flex; align-items: center; gap: 8px;
  overflow-x: auto; scrollbar-width: none; }
.bar-in::-webkit-scrollbar { display: none; }
.chip, .seg { flex: none; height: 36px; border: 1px solid var(--rim); border-radius: 18px;
  background: var(--capsule); font-size: 13px; font-weight: 500; white-space: nowrap; }
.chip { display: inline-flex; align-items: center; gap: 6px; padding: 0 14px; cursor: pointer; }
.chip[aria-pressed="true"] { background: var(--ink); border-color: var(--ink); color: var(--frost); }
.seg { display: inline-flex; padding: 2px; }
.seg button { border: 0; background: none; border-radius: 16px; padding: 0 12px; cursor: pointer; font-weight: 500; }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--frost); }
.badge { display: inline-flex; align-items: center; justify-content: center; min-width: 19px; height: 19px;
  padding: 0 5px; border-radius: 10px; background: var(--bill); color: var(--on-bill);
  font-size: 11px; font-weight: 700; font-variant-numeric: tabular-nums; }
[hidden] { display: none !important; }

.sum { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; padding-top: 12px;
  font-size: 13px; color: var(--ink-2); min-height: 40px; }
.sum .on { height: 28px; padding: 0 6px 0 11px; border-radius: 14px; border: 1px solid var(--rim);
  background: var(--capsule); color: var(--ink); cursor: pointer; display: inline-flex; align-items: center; gap: 6px; }
.sum .on i { font-style: normal; color: var(--ink-3); font-size: 15px; line-height: 1; }
.link { border: 0; background: none; padding: 4px 2px; text-decoration: underline; cursor: pointer; color: var(--ink-2); }

main { padding-bottom: 28px; min-height: 50vh; }
.day { position: sticky; top: calc(var(--bar-h) + 1px); z-index: 3; background: var(--frost);
  display: flex; justify-content: space-between; align-items: baseline;
  margin: 0; padding: 14px 0 8px; font-size: 15px; font-weight: 650; letter-spacing: -0.01em; }
.day span { font-size: 13px; font-weight: 400; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 10px; padding-bottom: 6px; }
@media (min-width: 560px) { .grid { grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 20px 12px; } }
.tile { display: block; width: 100%; min-width: 0; padding: 0; border: 0; background: none; text-align: left;
  cursor: pointer; border-radius: 8px; }
.ph { position: relative; display: block; aspect-ratio: 1; background: var(--photo);
  border: 1px solid var(--rim); border-radius: 8px; overflow: hidden; }
.ph img { display: block; width: 100%; height: 100%; object-fit: contain; }
.blank { position: absolute; inset: 20%; border-radius: 50%; border: 2px solid var(--blank);
  box-shadow: inset 0 0 0 7px var(--photo), inset 0 0 0 8px var(--blank); }
.new-dot { position: absolute; top: 8px; right: 8px; width: 12px; height: 12px; border-radius: 50%;
  background: var(--bill); box-shadow: 0 0 0 2px var(--photo); }
.out { position: absolute; left: 6px; bottom: 6px; padding: 2px 8px; border-radius: 10px;
  background: var(--shade); color: #fff; font-size: 11px; font-weight: 500; }
.tt { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden;
  margin-top: 7px; font-size: 13px; line-height: 1.3; font-weight: 500; overflow-wrap: anywhere; }
.tm { display: flex; justify-content: space-between; gap: 8px; margin-top: 3px; font-size: 12px; color: var(--ink-3); }
.tm .st { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tm .pr { color: var(--ink); font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; }
body.wall .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 4px; }
@media (min-width: 560px) { body.wall .grid { grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); } }
body.wall .tt, body.wall .tm { display: none; }
body.wall .ph, body.wall .tile { border-radius: 3px; }
.more { display: block; margin: 18px auto 0; height: 44px; padding: 0 22px; border-radius: 22px;
  border: 1px solid var(--rim); background: var(--capsule); cursor: pointer; font-size: 14px; font-weight: 500; }
.empty { padding: 56px 0 40px; max-width: 34em; }
.empty p { margin: 0 0 12px; font-size: 16px; }
.empty .chip { height: 44px; border-radius: 22px; font-size: 14px; }
.foot { padding-top: 8px; padding-bottom: 40px; font-size: 12px; color: var(--ink-3); max-width: 1400px; }
.foot p { margin: 0 0 4px; max-width: 70em; }

dialog { border: 0; padding: 0; background: var(--capsule); color: var(--ink); max-width: none; max-height: none; }
dialog::backdrop { background: var(--shade); }
.x { width: 44px; height: 44px; border: 0; border-radius: 22px; background: none; cursor: pointer;
  font-size: 24px; line-height: 1; }
.x:disabled { opacity: .3; cursor: default; }

#filters { width: 100%; max-height: 88vh; max-height: 88dvh; margin: auto 0 0; border-radius: 16px 16px 0 0; }
#filters[open] { display: flex; flex-direction: column; }
@media (min-width: 720px) {
  #filters { width: 420px; height: 100vh; height: 100dvh; max-height: none; margin: 0 0 0 auto; border-radius: 0; }
}
.f-head { flex: none; display: flex; align-items: center; justify-content: space-between;
  padding: 6px 6px 6px 16px; border-bottom: 1px solid var(--rim); }
.f-head h2 { margin: 0; font-size: 17px; font-weight: 650; }
.f-body { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; padding: 14px 16px 18px; }
.f-body h3 { margin: 20px 0 8px; font-size: 13px; font-weight: 650; }
.f-body label { display: block; font-size: 13px; font-weight: 650; margin-bottom: 8px; }
.f-body input { width: 100%; height: 44px; padding: 0 12px; border: 1px solid var(--rim); border-radius: 10px;
  background: var(--frost); color: var(--ink); font: inherit; font-size: 16px; }
.opts { display: flex; flex-wrap: wrap; gap: 8px; }
.opts .chip b { font-weight: 400; color: var(--ink-3); font-variant-numeric: tabular-nums; }
.opts .chip[aria-pressed="true"] b { color: inherit; opacity: .72; }
.f-foot { flex: none; display: flex; gap: 10px; padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
  border-top: 1px solid var(--rim); }
.f-foot button { flex: 1; height: 46px; border-radius: 23px; border: 1px solid var(--rim); background: none;
  cursor: pointer; font-weight: 600; font-size: 14px; }
.f-foot .go { flex: 2; }
.go { background: var(--ink) !important; border-color: var(--ink) !important; color: var(--frost) !important; }

#detail { width: 100%; height: 100vh; height: 100dvh; margin: 0; }
#detail[open] { display: flex; flex-direction: column; }
@media (min-width: 900px) {
  #detail { width: min(1040px, 94vw); height: min(700px, 92vh); margin: auto; border-radius: 14px; overflow: hidden; }
}
.d-top { flex: none; display: flex; align-items: center; justify-content: space-between; padding: 4px 6px;
  border-bottom: 1px solid var(--rim); }
.d-top span { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.d-nav { display: flex; }
.d-scroll { flex: 1; min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
.d-photo { position: relative; display: block; width: 100%; aspect-ratio: 1; max-height: 62vh; padding: 0; border: 0;
  background: var(--photo); cursor: pointer; perspective: 900px; }
.d-photo[aria-disabled="true"] { cursor: default; }
.d-photo img { display: block; width: 100%; height: 100%; object-fit: contain; transition: transform .15s ease-in; }
.d-photo.turning img { transform: rotateY(90deg); }
.d-turn { margin: 0; padding: 8px 16px 0; min-height: 26px; font-size: 12px; color: var(--ink-3); text-align: center; }
.d-info { padding: 12px 16px 16px; }
.d-foot { flex: none; padding: 10px 16px calc(10px + env(safe-area-inset-bottom)); border-top: 1px solid var(--rim); }
.d-info h2 { margin: 0 0 14px; font-size: 19px; line-height: 1.25; font-weight: 650; letter-spacing: -0.01em;
  overflow-wrap: anywhere; }
.d-info dl { display: grid; grid-template-columns: max-content 1fr; gap: 8px 16px; margin: 0 0 18px; font-size: 14px; }
.d-info dt { color: var(--ink-3); }
.d-info dd { margin: 0; }
.d-info dd small { display: block; margin-top: 1px; font-size: 12px; color: var(--ink-3); }
.d-info h3 { margin: 0 0 8px; font-size: 13px; font-weight: 650; }
.d-info .opts { margin-bottom: 4px; }
.d-info .opts .chip { height: 32px; padding: 0 12px; }
a.go { display: flex; align-items: center; justify-content: center; height: 48px; border-radius: 24px;
  text-decoration: none; font-weight: 600; }
a.go[aria-disabled="true"] { opacity: .4; pointer-events: none; }
@media (min-width: 900px) {
  .d-scroll { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); overflow: hidden; }
  .d-left { display: flex; flex-direction: column; min-height: 0; background: var(--photo); }
  .d-photo { flex: 1; min-height: 0; max-height: none; aspect-ratio: auto; }
  .d-turn { background: var(--capsule); padding-bottom: 8px; }
  .d-info { overflow-y: auto; padding-top: 22px; }
  .d-foot { display: flex; justify-content: flex-end; }
  .d-foot .go { width: 340px; }
}
@media (prefers-reduced-motion: reduce) { .d-photo img { transition: none; } }
</style>
</head>
<body>
<header class="top wrap">
  <div class="top-row">
    <h1>New releases</h1>
    <a class="back" href="index.html">Market monitor</a>
  </div>
  <p class="status" id="status"></p>
</header>

<div class="bar">
  <div class="bar-in wrap">
    <button class="chip" type="button" id="open-filters">Filters <span class="badge" id="filter-count" hidden></span></button>
    <div class="seg" id="period" role="group" aria-label="How far back"></div>
    <button class="chip" type="button" id="only-new" aria-pressed="false" hidden>New <span class="badge" id="new-count"></span></button>
    <button class="chip" type="button" id="colorized" aria-pressed="false">Colorized</button>
    <button class="chip" type="button" id="wall-mode" aria-pressed="false">Photos only</button>
  </div>
</div>

<div class="sum wrap" id="sum" aria-live="polite"></div>
<main class="wrap" id="wall"></main>
<footer class="foot wrap" id="foot"></footer>

<dialog id="filters" aria-labelledby="f-title">
  <div class="f-head"><h2 id="f-title">Filters</h2><button class="x" type="button" data-close aria-label="Close filters">&times;</button></div>
  <div class="f-body">
    <label for="q">Search titles</label>
    <input id="q" type="search" autocomplete="off" enterkeyhint="search" placeholder="dragon, Niue, 2 oz">
    <div id="f-groups"></div>
  </div>
  <div class="f-foot"><button type="button" id="f-clear">Clear all</button><button type="button" class="go" id="f-done"></button></div>
</dialog>

<dialog id="detail" aria-labelledby="d-title">
  <div class="d-top">
    <button class="x" type="button" data-close aria-label="Close">&times;</button>
    <span id="d-pos"></span>
    <div class="d-nav">
      <button class="x" type="button" id="d-prev" aria-label="Previous listing">&lsaquo;</button>
      <button class="x" type="button" id="d-next" aria-label="Next listing">&rsaquo;</button>
    </div>
  </div>
  <div class="d-scroll" id="d-scroll">
    <div class="d-left">
      <button class="d-photo" type="button" id="d-photo" aria-label="Show the next picture"><img id="d-img" alt="" referrerpolicy="no-referrer"><span class="blank" id="d-blank" hidden></span></button>
      <p class="d-turn" id="d-turn" aria-live="polite"></p>
    </div>
    <div class="d-info">
      <h2 id="d-title"></h2>
      <dl id="d-facts"></dl>
      <h3>More like this</h3>
      <div class="opts" id="d-like"></div>
    </div>
  </div>
  <div class="d-foot"><a class="go" id="d-go" target="_blank" rel="noopener noreferrer"></a></div>
</dialog>

<script>
const D = __DATA__;
const DAY = 864e5, PAGE = 60;
const $ = id => document.getElementById(id);
function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}
// Remembered on this device only; the page works the same without it.
const saved = {
  get(key, fallback) {
    try { const v = localStorage.getItem("blackbird.releases." + key); return v === null ? fallback : JSON.parse(v); }
    catch (e) { return fallback; }
  },
  set(key, value) { try { localStorage.setItem("blackbird.releases." + key, JSON.stringify(value)); } catch (e) {} },
};

// ---------------------------------------------------------------- listings
const when = s => s.length > 10 ? Date.parse(s) : new Date(+s.slice(0, 4), +s.slice(5, 7) - 1, +s.slice(8, 10), 12).getTime();
// "New" means: appeared since the visit before this one. Reloads within half an
// hour count as the same visit, so the marks survive a trip to a store and back.
const lastVisit = (() => {
  const now = Date.now(), v = saved.get("visits", null);
  const since = v && typeof v.at === "number" ? (now - v.at < 30 * 6e4 ? +v.since || 0 : v.at) : 0;
  saved.set("visits", { at: now, since });
  return since;
})();
const ITEMS = D.items.map((raw, idx) => {
  const it = Object.assign({ u: "", n: "", th: [], i: [], h: "", k: 0, c: 0 }, raw);
  const cur = (D.stores[it.s] || {}).cur || "USD";
  it.idx = idx;
  it.ts = when(it.d);
  it.usd = it.p == null ? null : it.p * (cur === "USD" ? 1 : (D.meta.fx[cur] || 1));
  it.lc = it.t.toLowerCase();
  it.isNew = lastVisit > 0 && (it.n ? when(it.n) : it.ts) > lastVisit;
  return it;
});

const PERIODS = [7, 30, D.meta.window].filter((d, i, a) => d <= D.meta.window && a.indexOf(d) === i);
const SORTS = {
  new: ["Newest first", (a, b) => b.ts - a.ts || a.idx - b.idx],
  mintage: ["Lowest mintage", byNumber(it => it.m, 1)],
  cheap: ["Price, low to high", byNumber(it => it.usd, 1)],
  dear: ["Price, high to low", byNumber(it => it.usd, -1)],
};
function byNumber(get, dir) {
  return (a, b) => {
    const x = get(a), y = get(b);
    if (x == null || y == null) return (x == null) - (y == null) || a.idx - b.idx;
    return dir * (x - y) || a.idx - b.idx;
  };
}
const FACETS = [
  ["th", "Theme", it => it.th, v => v],
  ["s", "Store", it => [it.s], v => D.stores[v].n],
  ["b", "Base coin", it => it.b ? [it.b] : [], v => v === "Other" ? "Other coins" : v],
  ["me", "Metal", it => it.me ? [it.me] : [], v => v === "Unknown" ? "Metal not stated" : v],
  ["f", "Finish", it => it.f ? [it.f] : [], v => v],
  ["z", "Size", it => it.z ? [it.z] : [], v => v === "Other" ? "Size not stated" : v],
];
const SIZE_ORDER = ["Under 1/2 oz", "1/2 oz", "1 oz", "2–3 oz", "5 oz", "10 oz+", "Kilo", "Half dollar", "Other"];

const prefs = saved.get("prefs", {});
const S = {
  days: PERIODS.includes(prefs.days) ? prefs.days : PERIODS[0],
  sort: SORTS[prefs.sort] ? prefs.sort : "new",
  colorized: prefs.colorized === true, older: prefs.older === true,
  hideOut: prefs.hideOut === true, wall: prefs.wall === true,
  onlyNew: false, q: "",
};
const F = { s: new Set(), me: new Set(), b: new Set(), th: new Set(), f: new Set(), z: new Set() };
function remember() {
  saved.set("prefs", { days: S.days, sort: S.sort, colorized: S.colorized, older: S.older, hideOut: S.hideOut, wall: S.wall });
}

const isCurrent = it => it.y == null || it.y >= D.meta.min_year;
function inPeriod(skip) {           // period + switches; facet counts come from this
  const cutoff = Date.now() - S.days * DAY;
  return ITEMS.filter(it => it.ts >= cutoff
    && (!S.colorized || it.c)
    && (skip === "older" || S.older || isCurrent(it))
    && (!S.hideOut || it.a !== 0)
    && (skip === "new" || !S.onlyNew || it.isNew));
}
function matches(it) {
  const words = S.q ? S.q.split(/\s+/) : [];
  return FACETS.every(([key, , values]) => !F[key].size || values(it).some(v => F[key].has(v)))
    && words.every(w => it.lc.includes(w));
}
const facetCount = () => FACETS.reduce((n, [key]) => n + F[key].size, 0) + (S.q ? 1 : 0);

// -------------------------------------------------------------------- wall
const wall = $("wall");
let list = [], shown = 0, lastDay = null, grid = null, dayCounts = {};
const dayKey = ts => { const d = new Date(ts); return d.getFullYear() * 10000 + d.getMonth() * 100 + d.getDate(); };
const moreButton = el("button", "more"); moreButton.type = "button";
moreButton.addEventListener("click", more);
const watcher = "IntersectionObserver" in window
  ? new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) more(); }, { rootMargin: "900px" }) : null;

function render() {
  const fresh = inPeriod("new").filter(matches).filter(it => it.isNew).length;
  if (!fresh) S.onlyNew = false;
  list = inPeriod().filter(matches).sort(SORTS[S.sort][1]);
  dayCounts = {};
  for (const it of list) { const k = dayKey(it.ts); dayCounts[k] = (dayCounts[k] || 0) + 1; }
  wall.textContent = ""; shown = 0; lastDay = null; grid = null;
  drawBar(fresh); drawSummary();
  if (list.length) more(); else wall.append(emptyState());
}
function more() {
  moreButton.remove();
  const end = Math.min(list.length, shown + PAGE), byDay = S.sort === "new";
  for (; shown < end; shown++) {
    const it = list[shown], day = byDay ? dayKey(it.ts) : 0;
    if (!grid || day !== lastDay) {
      lastDay = day;
      if (byDay) { const h = el("h2", "day", dayLabel(it.ts)); h.append(el("span", "", count(dayCounts[day]))); wall.append(h); }
      grid = el("div", "grid"); wall.append(grid);
    }
    grid.append(tile(it, shown));
  }
  if (shown < list.length) {
    moreButton.textContent = "Show more (" + count(list.length - shown) + " left)";
    wall.append(moreButton);
    if (watcher) { watcher.unobserve(moreButton); watcher.observe(moreButton); }
  }
}
function tile(it, pos) {
  const b = el("button", "tile"); b.type = "button"; b.dataset.pos = pos; b.setAttribute("aria-label", it.t);
  const ph = el("span", "ph"), src = thumbOf(it);
  if (src) {
    const img = new Image(); img.loading = "lazy"; img.decoding = "async"; img.alt = "";
    img.referrerPolicy = "no-referrer";
    if (it.i[0] && it.i[0] !== src) img.dataset.alt = it.i[0];
    img.src = src; ph.append(img);
  } else ph.append(el("span", "blank"));
  if (it.isNew) { const dot = el("span", "new-dot"); dot.title = "New since your last visit"; ph.append(dot); }
  if (it.a === 0) ph.append(el("span", "out", "Unavailable"));
  const meta = el("span", "tm");
  meta.append(el("span", "st", D.stores[it.s].n));
  if (it.p != null) meta.append(el("span", "pr", money(it.p, D.stores[it.s].cur)));
  b.append(ph, el("span", "tt", it.t), meta);
  return b;
}
wall.addEventListener("click", e => { const t = e.target.closest(".tile"); if (t) openDetail(+t.dataset.pos); });
wall.addEventListener("error", e => {                 // a picture that will not load
  const img = e.target;
  if (!(img instanceof HTMLImageElement)) return;
  if (img.dataset.alt) { const alt = img.dataset.alt; delete img.dataset.alt; img.src = alt; return; }
  img.replaceWith(el("span", "blank"));
}, true);

function emptyState() {
  const box = el("div", "empty");
  if (!ITEMS.length) {
    box.append(el("p", "", "No releases recorded yet. This page fills in after the tracker's next run."));
    return box;
  }
  const filtered = facetCount() || S.colorized || S.hideOut || S.onlyNew;
  box.append(el("p", "", filtered ? "Nothing matches these filters in the last " + S.days + " days."
                                 : "Nothing new in the last " + S.days + " days."));
  if (filtered) {
    const b = el("button", "chip", "Clear filters"); b.type = "button";
    b.addEventListener("click", () => { clearAll(); render(); });
    box.append(b);
  } else {
    const longer = PERIODS.find(d => d > S.days);
    if (longer) {
      const b = el("button", "chip", "Show the last " + longer + " days"); b.type = "button";
      b.addEventListener("click", () => { S.days = longer; remember(); render(); });
      box.append(b);
    }
  }
  return box;
}

// ----------------------------------------------------------- bar + summary
function drawBar(fresh) {
  for (const b of $("period").children) b.setAttribute("aria-pressed", String(+b.dataset.days === S.days));
  $("colorized").setAttribute("aria-pressed", String(S.colorized));
  $("wall-mode").setAttribute("aria-pressed", String(S.wall));
  document.body.classList.toggle("wall", S.wall);
  $("only-new").hidden = !fresh;
  $("only-new").setAttribute("aria-pressed", String(S.onlyNew));
  $("new-count").textContent = count(fresh);
  const active = facetCount() + (S.older ? 1 : 0) + (S.hideOut ? 1 : 0) + (S.sort !== "new" ? 1 : 0);
  $("filter-count").hidden = !active;
  $("filter-count").textContent = active;
  $("f-done").textContent = "Show " + count(list.length) + (list.length === 1 ? " listing" : " listings");
}
function drawSummary() {
  const sum = $("sum"); sum.textContent = "";
  const stores = new Set(list.map(it => it.s)).size;
  sum.append(el("span", "", list.length
    ? count(list.length) + (list.length === 1 ? " listing from " : " listings from ") + stores + (stores === 1 ? " store" : " stores")
    : "No listings"));
  const chip = (label, undo) => {
    const b = el("button", "on", label); b.type = "button"; b.setAttribute("aria-label", "Remove filter: " + label);
    b.append(el("i", "", "×"));
    b.addEventListener("click", () => { undo(); render(); });
    sum.append(b);
  };
  for (const [key, , , name] of FACETS) for (const v of F[key]) chip(name(v), () => F[key].delete(v));
  if (S.q) chip("“" + S.q + "”", () => { S.q = ""; $("q").value = ""; });
  if (S.sort !== "new") chip(SORTS[S.sort][0], () => { S.sort = "new"; remember(); });
  if (facetCount() > 1) {
    const b = el("button", "link", "Clear all"); b.type = "button";
    b.addEventListener("click", () => { clearAll(); render(); });
    sum.append(b);
  }
}
function clearAll() {
  for (const key in F) F[key].clear();
  S.q = ""; $("q").value = ""; S.onlyNew = false;
  S.colorized = false; S.hideOut = false; S.older = false; S.sort = "new";
  remember();
}

for (const d of PERIODS) {
  const b = el("button", "", d + " days"); b.type = "button"; b.dataset.days = d;
  b.addEventListener("click", () => { S.days = d; remember(); render(); scrollTo(0, 0); });
  $("period").append(b);
}
const flip = (id, key) => $(id).addEventListener("click", () => { S[key] = !S[key]; remember(); render(); });
flip("colorized", "colorized"); flip("wall-mode", "wall"); flip("only-new", "onlyNew");

// ----------------------------------------------------------------- filters
const filters = $("filters");
function drawFilters() {
  const box = $("f-groups"); box.textContent = "";
  const group = (title, options) => {
    if (!options.length) return;
    box.append(el("h3", "", title));
    const row = el("div", "opts");
    for (const [label, n, on, toggle] of options) {
      const b = el("button", "chip", label); b.type = "button"; b.setAttribute("aria-pressed", String(on));
      b.dataset.k = title + "/" + label;
      if (n != null) { b.append(" "); b.append(el("b", "", count(n))); }
      b.addEventListener("click", () => {
        toggle(); render(); drawFilters();
        const again = [...box.querySelectorAll("button")].find(x => x.dataset.k === b.dataset.k);
        if (again) again.focus({ preventScroll: true });
      });
      row.append(b);
    }
    box.append(row);
  };
  const older = inPeriod("older").filter(it => !isCurrent(it)).length;
  group("Show", [
    ["Older-dated coins too", older, S.older, () => { S.older = !S.older; remember(); }],
    ["Hide unavailable", null, S.hideOut, () => { S.hideOut = !S.hideOut; remember(); }],
  ]);
  const pool = inPeriod();
  for (const [key, title, values, name] of FACETS) {
    const counts = new Map();
    for (const it of pool) for (const v of values(it)) counts.set(v, (counts.get(v) || 0) + 1);
    for (const v of F[key]) if (!counts.has(v)) counts.set(v, 0);
    let keys = [...counts.keys()].sort((a, b) => counts.get(b) - counts.get(a) || String(name(a)).localeCompare(String(name(b))));
    if (key === "z") keys = keys.sort((a, b) => SIZE_ORDER.indexOf(a) - SIZE_ORDER.indexOf(b));
    group(title, keys.map(v => [name(v), counts.get(v), F[key].has(v),
      () => { F[key].has(v) ? F[key].delete(v) : F[key].add(v); }]));
  }
  group("Sort", Object.keys(SORTS).map(k => [SORTS[k][0], null, S.sort === k, () => { S.sort = k; remember(); }]));
}
$("open-filters").addEventListener("click", () => { drawFilters(); openDialog(filters); });
$("f-done").addEventListener("click", () => filters.close());
$("f-clear").addEventListener("click", () => { clearAll(); render(); drawFilters(); });
let typing = 0;
$("q").addEventListener("input", e => {
  clearTimeout(typing);
  typing = setTimeout(() => { S.q = e.target.value.trim().toLowerCase(); render(); }, 180);
});
$("q").addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); e.target.blur(); } });

// ------------------------------------------------------------------ detail
const detail = $("detail");
let cur = -1, pic = 0;
const calm = matchMedia("(prefers-reduced-motion: reduce)");
const press = matchMedia("(hover: hover) and (pointer: fine)").matches ? "Click" : "Tap";
function sized(u, w) {             // Shopify's image server resizes on request
  try {
    const url = new URL(u);
    if (url.hostname === "cdn.shopify.com" || url.pathname.includes("/cdn/shop/")) { url.searchParams.set("width", w); return url.href; }
  } catch (e) {}
  return u;
}
const thumbOf = it => it.h || (it.i[0] ? sized(it.i[0], 480) : "");

function openDetail(pos) { showListing(pos); openDialog(detail); }
function showListing(pos) {
  if (pos < 0 || pos >= list.length) return;
  cur = pos;
  const it = list[pos], st = D.stores[it.s];
  $("d-pos").textContent = count(pos + 1) + " of " + count(list.length);
  $("d-prev").disabled = pos === 0;
  $("d-next").disabled = pos === list.length - 1;
  $("d-title").textContent = it.t;
  $("d-photo").classList.remove("turning");
  showPicture(it, 0);

  const facts = $("d-facts"); facts.textContent = "";
  const fact = (name, value, note) => {
    const dd = el("dd", "", value);
    if (note) dd.append(el("small", "", note));
    facts.append(el("dt", "", name), dd);
  };
  fact("Store", st.n);
  fact(it.k ? "Listed" : "First spotted", stamp(it),
       it.k ? "" : "This store gives no release date, so this is when the tracker first saw it.");
  fact("Price", it.p == null ? "Not shown" : money(it.p, st.cur) + (st.cur !== "USD" && it.usd ? " (about " + money(it.usd, "USD") + " US)" : ""));
  if (it.m) fact("Mintage", count(it.m), "Read from the listing text. Check the store page.");
  fact("Status", it.a === 1 ? "Available" : it.a === 0 ? "Unavailable at this store" : "Not checked recently");

  const like = $("d-like"); like.textContent = "";
  const suggest = (label, apply) => {
    const b = el("button", "chip", label); b.type = "button";
    b.addEventListener("click", () => { for (const key in F) F[key].clear(); apply(); detail.close(); render(); scrollTo(0, 0); });
    like.append(b);
  };
  for (const t of it.th) suggest(t, () => F.th.add(t));
  if (it.b && it.b !== "Other") suggest(it.b, () => F.b.add(it.b));
  if (it.f && it.f !== "Standard finish") suggest(it.f, () => F.f.add(it.f));
  if (it.z && it.z !== "Other") suggest(it.z, () => F.z.add(it.z));
  if (it.me && it.me !== "Unknown") suggest(it.me, () => F.me.add(it.me));
  suggest("Everything at " + st.n, () => F.s.add(it.s));

  const go = $("d-go"), ok = /^https?:\/\//i.test(it.u);
  go.textContent = "Open at " + st.n;
  if (ok) { go.href = it.u; go.removeAttribute("aria-disabled"); }
  else { go.removeAttribute("href"); go.setAttribute("aria-disabled", "true"); }
  $("d-scroll").scrollTop = 0;
  const info = detail.querySelector(".d-info"); if (info) info.scrollTop = 0;
  if (pos + 6 > shown && shown < list.length) more();
}
function showPicture(it, n) {
  pic = n;
  const img = $("d-img"), box = $("d-photo"), total = it.i.length;
  $("d-blank").hidden = total > 0;
  img.hidden = !total;
  box.setAttribute("aria-disabled", String(total < 2));
  $("d-turn").textContent = !total ? "No picture yet. It is picked up the next time the tracker reads this store."
    : total > 1 ? "Picture " + (n + 1) + " of " + total + ". " + press + " the coin to turn it over." : "";
  if (!total) { img.removeAttribute("src"); return; }
  const big = sized(it.i[n], 1200), small = n === 0 ? thumbOf(it) : "";
  if (big !== it.i[n] || (small && small !== it.i[n])) img.dataset.alt = it.i[n]; else delete img.dataset.alt;
  img.dataset.n = n;
  if (small && small !== big) {              // show the small one at once, then sharpen
    img.src = small;
    const full = new Image(); full.referrerPolicy = "no-referrer";
    full.onload = () => { if (list[cur] === it && pic === n) img.src = big; };
    full.src = big;
  } else img.src = big;
}
$("d-img").addEventListener("error", e => {
  const img = e.target;
  if (img.dataset.alt) { const alt = img.dataset.alt; delete img.dataset.alt; img.src = alt; return; }
  img.hidden = true; $("d-blank").hidden = false;
  $("d-turn").textContent = "This picture did not load. Open the store page to see it.";
});
$("d-photo").addEventListener("click", () => {
  const it = list[cur], box = $("d-photo");
  if (!it || it.i.length < 2 || box.classList.contains("turning")) return;
  const next = (pic + 1) % it.i.length;
  if (calm.matches) { showPicture(it, next); return; }
  box.classList.add("turning");                 // edge-on, swap, turn back
  setTimeout(() => { if (list[cur] === it) showPicture(it, next); box.classList.remove("turning"); }, 150);
});
const step = by => showListing(cur + by);
$("d-prev").addEventListener("click", () => step(-1));
$("d-next").addEventListener("click", () => step(1));
detail.addEventListener("keydown", e => {
  if (e.key === "ArrowLeft") { e.preventDefault(); step(-1); }
  if (e.key === "ArrowRight") { e.preventDefault(); step(1); }
});
let touch = null;
detail.addEventListener("touchstart", e => {
  touch = e.touches.length === 1 ? { x: e.touches[0].clientX, y: e.touches[0].clientY, t: Date.now() } : null;
}, { passive: true });
detail.addEventListener("touchend", e => {
  if (!touch) return;
  const dx = e.changedTouches[0].clientX - touch.x, dy = e.changedTouches[0].clientY - touch.y;
  if (Date.now() - touch.t < 700 && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.8) step(dx < 0 ? 1 : -1);
  touch = null;
}, { passive: true });

// ----------------------------------------------------------------- dialogs
// The phone's back button closes an open sheet instead of leaving the page.
try { history.scrollRestoration = "manual"; } catch (e) {}
function openDialog(d) {
  if (d.open) return;
  d.showModal();
  try { history.pushState({ sheet: d.id }, ""); } catch (e) {}
}
for (const d of [filters, detail]) {
  d.addEventListener("close", () => { if (history.state && history.state.sheet === d.id) history.back(); });
  d.addEventListener("click", e => { if (e.target === d || e.target.closest("[data-close]")) d.close(); });
}
addEventListener("popstate", () => { for (const d of document.querySelectorAll("dialog[open]")) d.close(); });

// ----------------------------------------------------------------- wording
function count(n) { return Number(n || 0).toLocaleString("en-US"); }
function money(v, cur) {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: cur || "USD",
      maximumFractionDigits: v >= 1000 ? 0 : 2, minimumFractionDigits: v >= 1000 ? 0 : 2 }).format(v);
  } catch (e) { return (cur || "") + " " + v; }
}
function dayLabel(ts) {
  const d = new Date(ts), now = new Date();
  const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / DAY);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
}
function stamp(it) {
  const d = new Date(it.ts), date = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  return it.d.length > 10 ? date + ", " + d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : date;
}
function ago(ms) {
  const m = Math.max(0, Math.round(ms / 6e4));
  if (m < 2) return "just now";
  if (m < 90) return m + " minutes ago";
  const h = Math.round(m / 60);
  if (h < 36) return h + " hours ago";
  return Math.round(h / 24) + " days ago";
}
(function status() {
  const age = Date.now() - Date.parse(D.meta.generated), p = $("status");
  if (age > 12 * 36e5) { p.className = "status stale"; p.textContent = "Last updated " + ago(age) + ". The tracker may have stopped."; }
  else p.textContent = "Updated " + ago(age) + ".";
  const foot = $("foot");
  const down = D.stores.filter(s => s.ok === false).map(s => s.n);
  foot.append(el("p", "", "Listings first seen in the last " + D.meta.window + " days at the stores the tracker reads. A listing is not a sale, and unavailable does not mean sold."));
  if (down.length) foot.append(el("p", "", "Not readable on the last check: " + down.join(", ") + "."));
  foot.append(el("p", "", "Pictures load from each store's own site."));
})();

render();
</script>
</body>
</html>
"""
