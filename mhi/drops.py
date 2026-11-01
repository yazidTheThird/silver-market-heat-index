"""Colorized drop tracker — works on any store platform.

For every store in config.yaml it finds the colorized products, records when each
one first appears (= launch) and the day it flips to sold out.

How it reads a store (chosen automatically, or set `platform:` per store):
  * shopify      — public feed at /products.json
  * woocommerce  — public feed at /wp-json/wc/store/v1/products
  * generic      — any other platform: collect product links from the category
                   page(s) you list (or the sitemap), open each product page and
                   read its stock status from the schema.org data that stores
                   embed for Google Shopping; falls back to "sold out" / "add to
                   cart" text. Set `render: true` for stores that only show
                   products after JavaScript runs (uses a headless browser).
"""
from __future__ import annotations

import datetime as dt
import html as html_lib
import json
import os
import re
import time
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

from .util import BROWSER_HEADERS, log

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATE = os.path.join(ROOT, "data", "drops_state.csv")
STATE_COLS = ["store", "product_id", "title", "url", "published", "first_seen",
              "baseline", "sold_out_date", "available", "last_checked",
              # Hour-level timing (UTC). The fast checker (run.py --fast) re-checks new
              # launches every few hours, so these tell a 2-hour sell-out from a 2-day one.
              "published_at", "first_seen_at", "sold_out_at",
              # Broad tracking: every collectible product, with colorized flagged.
              "colorized", "price", "mintage"]

SOLD_OUT_WORDS = re.compile(r"\b(sold[\s-]?out|out[\s-]of[\s-]stock|no longer available|"
                            r"currently unavailable)\b", re.I)
BUY_WORDS = re.compile(r"\b(add to cart|add to basket|buy now|pre-?order now)\b", re.I)
PRODUCT_PATH = re.compile(r"/(product|products|p|item|shop/[^/]+/[^/]+)/[^/?#]+", re.I)


# ----------------------------------------------------------------- fetching
class Fetcher:
    """requests by default; a shared headless Chromium for stores with render: true."""

    def __init__(self):
        self._pw = self._browser = None

    def get(self, url: str, render: bool = False, params: dict | None = None):
        if not render:
            r = requests.get(url, params=params, headers=BROWSER_HEADERS, timeout=30)
            return r.status_code, r.text
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch()
        if params:
            url += ("&" if "?" in url else "?") + "&".join(f"{k}={v}" for k, v in params.items())
        page = self._browser.new_page(user_agent=BROWSER_HEADERS["User-Agent"])
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=45000)
            page.wait_for_timeout(1500)
            return (resp.status if resp else 0), page.content()
        finally:
            page.close()

    def close(self):
        if self._browser:
            self._browser.close()
            self._pw.stop()


# ------------------------------------------------------------- platform readers
def read_shopify(base: str, f: Fetcher, cfg: dict) -> list[dict] | None:
    out = []
    for page in range(1, cfg["drops"].get("feed_max_pages", 20) + 1):
        code, text = f.get(f"{base}/products.json", params={"limit": 250, "page": page})
        try:
            batch = json.loads(text).get("products") if code == 200 else None
        except ValueError:
            batch = None
        if batch is None:
            return None if page == 1 else out
        for p in batch:
            tags = p.get("tags", [])
            tags = " ".join(tags) if isinstance(tags, list) else str(tags)
            text_all = f'{p.get("title","")} {p.get("product_type","")} {tags}'
            keep, colored = classify(text_all, cfg)
            if not keep:
                continue
            variants = p.get("variants") or [{}]
            body = _clean(p.get("body_html") or "")
            out.append({"product_id": str(p["id"]), "title": p.get("title", ""),
                        "url": f'{base}/products/{p.get("handle","")}',
                        "published": (p.get("published_at") or p.get("created_at") or "")[:10],
                        "published_at": p.get("published_at") or p.get("created_at") or "",
                        "available": any(v.get("available") for v in variants),
                        "colorized": colored, "price": _num(variants[0].get("price")),
                        "mintage": find_mintage(f'{p.get("title","")} {body}')})
        if len(batch) < 250:
            break
        time.sleep(1)
    return out


def read_woocommerce(base: str, f: Fetcher, cfg: dict) -> list[dict] | None:
    out = []
    for page in range(1, cfg["drops"].get("feed_max_pages", 20) + 11):
        code, text = f.get(f"{base}/wp-json/wc/store/v1/products",
                           params={"per_page": 100, "page": page})
        try:
            batch = json.loads(text) if code == 200 else None
        except ValueError:
            batch = None
        if not isinstance(batch, list):
            return None if page == 1 else out
        for p in batch:
            cats = " ".join(c.get("name", "") for c in p.get("categories", []))
            tags = " ".join(t.get("name", "") for t in p.get("tags", []))
            keep, colored = classify(f'{p.get("name","")} {cats} {tags}', cfg)
            if not keep:
                continue
            prices = p.get("prices") or {}
            price = _num(prices.get("price"))
            if price is not None:
                price = price / (10 ** int(prices.get("currency_minor_unit", 2) or 0))
            desc = _clean(f'{p.get("short_description","")} {p.get("description","")}')
            out.append({"product_id": str(p["id"]), "title": _clean(p.get("name", "")),
                        "url": p.get("permalink", ""), "published": "",
                        "available": bool(p.get("is_in_stock")),
                        "colorized": colored, "price": price,
                        "mintage": find_mintage(f'{p.get("name","")} {desc}')})
        if len(batch) < 100:
            break
        time.sleep(1)
    return out


def read_generic(store: dict, f: Fetcher, cfg: dict, known: pd.DataFrame,
                 today: dt.date, fast: bool = False) -> list[dict] | None:
    base = store["url"].rstrip("/")
    render = bool(store.get("render"))
    links = discover_links(store, f, skip_sitemap=fast)
    if not links:
        return None
    dcfg = cfg["drops"]
    budget = (dcfg.get("fast_max_checks_per_store", 40) if fast
              else dcfg.get("max_product_checks_per_store", 150))
    fast_window = dcfg.get("fast_window_days", 7)
    recheck_soldout = dcfg.get("recheck_soldout_days", 7)
    known_by_url = {r.url: r for r in known.itertuples()} if not known.empty else {}
    ignore = _load_ignore()

    # Products we were tracking as in stock but that dropped off the category page
    # are often sold out — check them directly.
    for r in known.itertuples() if not known.empty else []:
        if str(r.available) == "1" and r.url and r.url not in links:
            links.append(r.url)

    out = []
    stats = {"fetched": 0, "http_errors": {}, "no_stock_info": 0, "not_colorized": 0}

    def keep(prev, url, available=None, checked=False):
        """Carry a known product forward without new information (or with a verdict)."""
        out.append({"product_id": url, "title": prev.title, "url": url,
                    "published": _s(prev.published),
                    "colorized": _s(getattr(prev, "colorized", "")) != "0",
                    "available": (str(prev.available) == "1") if available is None else available,
                    "checked": checked})

    for url in links:
        if url in ignore:
            continue
        prev = known_by_url.get(url)
        # Fast mode: only new products and recent launches still in stock get fetched;
        # everything else is carried forward unchanged until the daily run.
        if fast and prev is not None and not _is_recent_in_stock(prev, today, fast_window):
            keep(prev, url)
            continue
        # Known sold-out products are only re-checked (for restocks) every few days.
        if prev is not None and str(prev.available) == "0":
            last = pd.to_datetime(prev.last_checked, errors="coerce")
            if pd.notnull(last) and (today - last.date()).days < recheck_soldout:
                keep(prev, url)
                continue
        if budget <= 0:
            if prev is not None:
                keep(prev, url)
            continue
        budget -= 1
        try:
            code, html = f.get(url, render=render)
        except Exception as e:  # noqa: BLE001
            log.warning("drops: %s -> %s", url, e)
            if prev is not None:
                keep(prev, url)
            continue
        stats["fetched"] += 1
        if code != 200:
            stats["http_errors"][code] = stats["http_errors"].get(code, 0) + 1
        if code in (404, 410):
            if prev is not None:
                keep(prev, url, available=False, checked=True)   # page removed
            continue
        if code != 200:
            if prev is not None:
                keep(prev, url)
            continue
        info = parse_product_page(html)
        title = info["title"] or (prev.title if prev is not None else "")
        keep, colored = classify(f'{title} {info["category"]} {url}', cfg)
        if store.get("listing_is_colorized"):
            keep, colored = True, True
        elif store.get("listing_is_collectible"):
            keep = keep or not BULLION_ONLY.search(title)
        if prev is None and not keep:
            ignore.add(url)            # plain bullion / not collectible: never fetch again
            stats["not_colorized"] += 1
            continue
        if info["available"] is None:
            stats["no_stock_info"] += 1
            if prev is not None:
                keep(prev, url)
            continue
        out.append({"product_id": url, "title": title, "url": url,
                    "published": info["published"], "available": info["available"],
                    "checked": True, "colorized": colored, "price": info["price"],
                    "mintage": find_mintage(f'{title} {info["description"]}')})
        time.sleep(store.get("delay_seconds", 1.5))
    _save_ignore(ignore)
    log.info("drops: %s -> %d product links, %d pages fetched, HTTP errors %s, "
             "%d without readable stock status, %d skipped (plain bullion)",
             base, len(links), stats["fetched"], stats["http_errors"] or "none",
             stats["no_stock_info"], stats["not_colorized"])
    return out


IGNORE = os.path.join(ROOT, "data", "drops_ignore.txt")


def _load_ignore() -> set[str]:
    if not os.path.exists(IGNORE):
        return set()
    with open(IGNORE, encoding="utf-8") as fh:
        return {line.strip() for line in fh if line.strip()}


def _save_ignore(ignore: set[str]) -> None:
    os.makedirs(os.path.dirname(IGNORE), exist_ok=True)
    with open(IGNORE, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(ignore)) + ("\n" if ignore else ""))


def _is_recent_in_stock(prev, today: dt.date, days: int) -> bool:
    if str(prev.available) != "1" or str(getattr(prev, "baseline", "")) == "1":
        return False
    d = pd.to_datetime(_s(prev.published) or _s(prev.first_seen), errors="coerce")
    return pd.notnull(d) and (today - d.date()).days <= days


def discover_links(store: dict, f: Fetcher, skip_sitemap: bool = False) -> list[str]:
    base = store["url"].rstrip("/")
    host = urlparse(base).netloc.replace("www.", "")
    pattern = re.compile(store["product_link_pattern"], re.I) if store.get(
        "product_link_pattern") else PRODUCT_PATH
    links: list[str] = []

    def add(u: str):
        u = urljoin(base + "/", u.split("#")[0])
        if urlparse(u).netloc.replace("www.", "") != host:
            return
        if pattern.search(urlparse(u).path) and u not in links:
            links.append(u)

    for listing in store.get("listing_urls", []):
        for page in range(1, store.get("max_pages", 3) + 1):
            params = {store["page_param"]: page} if store.get("page_param") and page > 1 else None
            if page > 1 and not params:
                break
            try:
                code, html = f.get(listing, render=bool(store.get("render")), params=params)
            except Exception as e:  # noqa: BLE001
                log.warning("drops: listing %s -> %s", listing, e)
                break
            if code != 200:
                log.warning("drops: listing %s -> HTTP %s", listing, code)
                break
            before = len(links)
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                add(a["href"])
            for obj in _jsonld(soup):                  # ItemList on category pages
                elements = obj.get("itemListElement", [])
                for el in elements if isinstance(elements, list) else []:
                    if not isinstance(el, dict):
                        continue
                    item = el.get("item")
                    u = el.get("url") or (item.get("url") if isinstance(item, dict)
                                          else item if isinstance(item, str) else "")
                    if u:
                        add(u)
            if len(links) == before:
                if page == 1:
                    log.warning("drops: listing %s loaded (%d chars) but no product links "
                                "matched — page may need render: true or a product_link_pattern",
                                listing, len(html))
                break
            time.sleep(1)

    if store.get("sitemap_url") and not (skip_sitemap and links):
        links.extend(u for u in read_sitemap(store["sitemap_url"], f, pattern) if u not in links)
    return links


def read_sitemap(url: str, f: Fetcher, pattern: re.Pattern, depth: int = 0) -> list[str]:
    try:
        code, xml = f.get(url)
    except Exception as e:  # noqa: BLE001
        log.warning("drops: sitemap %s -> %s", url, e)
        return []
    if code != 200:
        log.warning("drops: sitemap %s -> HTTP %s", url, code)
        return []
    locs = [html_lib.unescape(u) for u in re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)]
    if "<sitemapindex" in xml and depth < 2:
        out = []
        for sm in locs:
            if re.search(r"product|\bitems?\b|shop", sm, re.I):
                out.extend(read_sitemap(sm, f, pattern, depth + 1))
        return out
    return [u for u in locs if pattern.search(urlparse(u).path)]


# ------------------------------------------------------------- product pages
def parse_product_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title, available, published, category = "", None, "", ""
    price, description = None, ""

    for obj in _jsonld(soup):
        if not isinstance(obj, dict):
            continue
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" not in types and "ProductGroup" not in types:
            continue
        title = title or _clean(obj.get("name", ""))
        category = category or str(obj.get("category", ""))
        description = description or _clean(str(obj.get("description", "") or ""))[:2000]
        published = published or str(obj.get("releaseDate", "") or "")[:10]
        offers = obj.get("offers") or []
        if isinstance(offers, dict):
            offers = offers.get("offers", [offers]) if offers.get("@type") == "AggregateOffer" else [offers]
        if obj.get("hasVariant"):
            for v in obj["hasVariant"]:
                o = v.get("offers") if isinstance(v, dict) else None
                offers += o if isinstance(o, list) else ([o] if o else [])
        for o in offers:
            if isinstance(o, dict) and price is None:
                price = _num(o.get("price") or o.get("lowPrice"))
        states = [str(o.get("availability", "")) for o in offers if isinstance(o, dict)]
        states = [s for s in states if s]
        if states:
            avail = any(re.search(r"InStock|PreOrder|BackOrder|LimitedAvailability|OnlineOnly",
                                  s, re.I) for s in states)
            available = avail if available is None else (available or avail)

    if available is None:  # OpenGraph / microdata
        meta = soup.find("meta", attrs={"property": re.compile(r"(product|og):availability", re.I)})
        if meta and meta.get("content"):
            available = bool(re.search(r"in ?stock|instock|preorder", meta["content"], re.I))
        else:
            itemprop = soup.find(attrs={"itemprop": "availability"})
            val = itemprop and (itemprop.get("href") or itemprop.get("content") or "")
            if val:
                available = bool(re.search(r"InStock|PreOrder", val, re.I))

    if available is None:  # last resort: the buy button itself
        for tag in soup.find_all(["header", "footer", "nav"]):
            tag.decompose()
        buy_area = soup.find_all(["button", "input"])
        buy_area += soup.find_all(class_=re.compile(r"add-?to-?cart|buy|product-form|stock|availability", re.I))
        texts = []
        for b in buy_area:
            t = b.get_text(" ", strip=True) if b.name != "input" else b.get("value", "")
            texts.append((t, b.has_attr("disabled")))
        if any(BUY_WORDS.search(t) and not dis for t, dis in texts):
            available = True
        elif any(SOLD_OUT_WORDS.search(t) for t, _ in texts):
            available = False

    if not title:
        h1 = soup.find("h1")
        og = soup.find("meta", attrs={"property": "og:title"})
        title = _clean(h1.get_text(" ", strip=True) if h1 else (og.get("content", "") if og else ""))
    if not description:
        meta = soup.find("meta", attrs={"name": "description"})
        description = meta.get("content", "") if meta else ""
    return {"title": title[:150], "available": available, "published": published,
            "category": category, "price": price, "description": description}


def _jsonld(soup: BeautifulSoup) -> list:
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or tag.get_text() or "")
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                out.append(d)
                if "@graph" in d:
                    stack.extend(d["@graph"] if isinstance(d["@graph"], list) else [d["@graph"]])
    return out


# --------------------------------------------------------------------- helpers
def is_colorized(text: str, cfg: dict) -> bool:
    return re.search(cfg["colorized_pattern"], text or "", re.I) is not None


# Plain bullion that isn't a collectible release (random-year coins, generic bars…).
BULLION_ONLY = re.compile(
    r"random year|varied year|any year|\bbu\b.*\btube\b|monster box|generic|secondary market|"
    r"\bjunk\b|90% silver|\bbag\b|\bscrap\b|\(random|backdated|sprue", re.I)


def classify(text: str, cfg: dict) -> tuple[bool, bool]:
    """(keep, colorized). Track mode `colorized` keeps only colorized products;
    `collectible` (default) keeps every collectible / limited release and drops plain
    bullion (random-year coins, generic rounds and bars, tubes, junk silver)."""
    colored = is_colorized(text, cfg)
    if colored:
        return True, True
    tcfg = cfg.get("tracking") or {}
    if tcfg.get("mode", "collectible") == "colorized":
        return False, False
    if re.search(tcfg.get("exclude_pattern", "$^"), text or "", re.I) or BULLION_ONLY.search(text or ""):
        return False, False
    pat = tcfg.get("collectible_pattern",
                   r"proof|reverse proof|high relief|\buhr\b|antiqu|gild|limited|mintage|"
                   r"privy|shaped|colou?r|enamel|hologra|black|ruthenium|diamond|series|"
                   r"edition|set\b|lunar|zodiac|niue|cook islands|cameroon|chad|tuvalu|"
                   r"samoa|ghana|liberia|fiji|barbados|solomon|mongolia|pamp|germania|"
                   r"first strike|ngc|pcgs|ms ?70|pf ?70|pr ?70|coa\b|box\b|capsule|"
                   r"anniversary|commemorative|collector|numismatic|figurine|art\b")
    return bool(re.search(pat, text or "", re.I)), False


MINTAGE = re.compile(
    r"(?:mintage(?: of| limit(?:ed)?(?: to)?| is| :)?|limited to|only|max(?:imum)? mintage(?: of)?)"
    r"\s*:?\s*(\d{1,3}(?:[,. ]\d{3})+|\d{2,6})\b(?!\s*(?:oz|g\b|gram|mm|%))", re.I)
MINTAGE_AFTER = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{2,6})\s*(?:pieces|pcs|coins)?\s*"
                           r"(?:mintage|minted|worldwide)\b", re.I)


def find_mintage(text: str) -> int | None:
    for rx in (MINTAGE, MINTAGE_AFTER):
        m = rx.search(text or "")
        if m:
            n = int(re.sub(r"[,. ]", "", m.group(1)))
            if 10 <= n <= 2_000_000:
                return n
    return None


def _num(x) -> float | None:
    try:
        v = float(str(x).replace(",", "").replace("$", "").strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", re.sub(r"&amp;", "&", s or "")).strip()


def _flag(x) -> str:
    return "1" if x else "0"


def _s(x) -> str:
    return "" if x is None or (isinstance(x, float) and x != x) else str(x)


# ------------------------------------------------------------------ main entry
def run_tracker(cfg: dict, today: dt.date, fast: bool = False
                ) -> tuple[pd.DataFrame, int, list[str]]:
    """Reads every store, updates data/drops_state.csv. Returns (state, stores_ok, notes).
    fast=True: the every-few-hours check — feeds are read in full (cheap), other stores
    only re-check new and recent launches."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = pd.read_csv(STATE, dtype=str) if os.path.exists(STATE) else pd.DataFrame(columns=STATE_COLS)
    for c in STATE_COLS:
        if c not in state.columns:
            state[c] = ""
    f = Fetcher()
    stores_ok, notes = 0, []
    broad = _read_set(BROAD)
    try:
        for store in cfg["drops"]["stores"]:
            base = store["url"].rstrip("/")
            known = state[state["store"] == base]
            platform = store.get("platform", "auto")
            items, used = None, platform
            try:
                if platform in ("auto", "shopify"):
                    items, used = read_shopify(base, f, cfg), "shopify"
                if items is None and platform in ("auto", "woocommerce"):
                    items, used = read_woocommerce(base, f, cfg), "woocommerce"
                if items is None and platform in ("auto", "generic"):
                    if store.get("listing_urls") or store.get("sitemap_url"):
                        items, used = read_generic(store, f, cfg, known, today, fast), "generic"
            except Exception as e:  # noqa: BLE001
                log.warning("drops: %s -> %s", base, e)
                items = None
            if items is None:
                msg = (f"{base}: could not read products — add listing_urls (colorized "
                       f"category page) or sitemap_url for this store, or try render: true")
                log.warning("drops: %s", msg)
                notes.append(msg)
                continue
            stores_ok += 1
            n_col = sum(1 for it in items if it.get("colorized", True))
            log.info("drops: %s via %s -> %d collectible products (%d colorized)",
                     base, used, len(items), n_col)
            # The first broad run at a store finds its existing non-colorized catalog:
            # those are old products, not launches, so they join the baseline.
            first_broad = base not in broad
            state = _merge(state, base, items, today, first_run=known.empty, now=now,
                           baseline_noncolor=first_broad)
            broad.add(base)
    finally:
        f.close()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    state[STATE_COLS].to_csv(STATE, index=False)
    _write_set(BROAD, broad)
    return state, stores_ok, notes


BROAD = os.path.join(ROOT, "data", "broad_stores.txt")


def _read_set(path: str) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {line.strip() for line in fh if line.strip()}


def _write_set(path: str, items: set[str]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(items)) + ("\n" if items else ""))


def _merge(state: pd.DataFrame, base: str, items: list[dict], today: dt.date,
           first_run: bool, now: str = "", baseline_noncolor: bool = False) -> pd.DataFrame:
    t = today.isoformat()
    now = now or f"{t}T00:00:00Z"
    for c in STATE_COLS:
        if c not in state.columns:
            state[c] = ""
    state = state.copy()
    pos = {(r.store, r.product_id): i for i, r in state.iterrows()}
    new_rows = []
    for it in items:
        k = (base, it["product_id"])
        avail = "1" if it["available"] else "0"
        if k not in pos:
            new_rows.append({
                "store": base, "product_id": it["product_id"], "title": it["title"],
                "url": it.get("url", ""), "published": it.get("published", ""),
                "first_seen": t,
                # Products already on the store the first time we look are the
                # "baseline": we don't know when they launched, so they don't count
                # as new launches (unless the store tells us the publish date).
                "baseline": "1" if (first_run or (baseline_noncolor and not it.get(
                    "colorized", True))) else "0",
                "sold_out_date": "", "available": avail, "last_checked": t,
                "published_at": it.get("published_at", ""), "first_seen_at": now,
                "sold_out_at": "", "colorized": _flag(it.get("colorized", True)),
                "price": _s(it.get("price")), "mintage": _s(it.get("mintage"))})
            continue
        i = pos[k]
        if it.get("checked", True) is False:
            continue
        was = state.at[i, "available"]
        state.at[i, "available"] = avail
        state.at[i, "title"] = it["title"] or state.at[i, "title"]
        state.at[i, "last_checked"] = t
        if not _s(state.at[i, "published"]) and it.get("published"):
            state.at[i, "published"] = it["published"]
        if not _s(state.at[i, "published_at"]) and it.get("published_at"):
            state.at[i, "published_at"] = it["published_at"]
        if not _s(state.at[i, "colorized"]):
            # Tracked before broad tracking began = it passed the colorized filter then.
            state.at[i, "colorized"] = "1"
        if it.get("price") and not _s(state.at[i, "price"]):
            state.at[i, "price"] = _s(it["price"])        # launch price, kept as first seen
        if it.get("mintage") and not _s(state.at[i, "mintage"]):
            state.at[i, "mintage"] = _s(it["mintage"])
        if str(was) == "1" and avail == "0" and not _s(state.at[i, "sold_out_date"]):
            state.at[i, "sold_out_date"] = t
            state.at[i, "sold_out_at"] = now
        if avail == "1":
            state.at[i, "sold_out_date"] = ""
            state.at[i, "sold_out_at"] = ""
    # Feed-based stores (Shopify/WooCommerce): a tracked in-stock product that has
    # vanished from the feed was removed — almost always because it sold out.
    seen_ids = {it["product_id"] for it in items}
    in_stock_known = int(((state["store"] == base) & (state["available"].astype(str) == "1")).sum())
    if in_stock_known >= 10 and len(items) < 0.5 * in_stock_known:
        # Today's read returned far fewer products than we know are in stock — that's a
        # partial/failed read, not a wave of sell-outs. Don't mark anything as sold.
        log.warning("drops: %s returned only %d products vs %d known in stock — "
                    "skipping sold-out detection today", base, len(items), in_stock_known)
        seen_ids = None
    for i, r in (state.iterrows() if seen_ids is not None else []):
        if r["store"] == base and r["product_id"] not in seen_ids and str(r["available"]) == "1":
            state.at[i, "available"] = "0"
            state.at[i, "last_checked"] = t
            if not _s(r["sold_out_date"]):
                state.at[i, "sold_out_date"] = t
                state.at[i, "sold_out_at"] = now
    if new_rows:
        state = pd.concat([state, pd.DataFrame(new_rows)], ignore_index=True)
    return state


def launch_dates(state: pd.DataFrame) -> pd.Series:
    """Best known launch date per product: the store's publish date if it gives one,
    otherwise the day we first saw it — except for baseline products (unknown)."""
    pub = pd.to_datetime(state["published"].map(_s).replace("", None), errors="coerce")
    seen = pd.to_datetime(state["first_seen"], errors="coerce")
    seen = seen.where(state["baseline"].map(_s) != "1")
    return pub.fillna(seen).dt.date
