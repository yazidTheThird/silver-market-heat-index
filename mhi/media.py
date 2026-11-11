"""Pictures for the new-releases gallery.

The tracker state (data/drops_state.csv) records what a store lists and when.
This module keeps the pictures that belong to recent launches in a separate
file, data/media.csv, so the availability evidence and its columns stay as
they are.

One row per product: store, product_id, thumb, images, presale, ships
  images   up to MAX_IMAGES full-size picture addresses, separated by a space
  thumb    a small version of the first picture, when the store offers one
  presale  1 when the store sells it ahead of shipping (pre-order / presale /
           backorder), as of the last time the product was read
  ships    the ship date the listing gives, as written ("Dec 15, 2026"), if any

Only addresses are saved. The gallery shows each picture straight from the
store's own server; nothing is downloaded or copied into this repository.
"""
from __future__ import annotations

import csv
import functools
import os
import re
from urllib.parse import urljoin, urlparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PATH = os.path.join(ROOT, "data", "media.csv")
COLS = ["store", "product_id", "thumb", "images", "presale", "ships"]
MAX_IMAGES = 3

# Stand-in pictures a store shows when a product has no photo yet.
_STAND_IN = re.compile(r"placeholder|no[-_]?image|image[-_]?coming|coming[-_]?soon|"
                       r"default[-_]?(image|product)", re.I)
_HAS_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)
# Some pages escape the "&" of an address inside their structured data.
_ESCAPED_AMP = re.compile(r"&(?:amp|#0*38|#x0*26);", re.I)
_ENCODE = {" ": "%20", '"': "%22", "'": "%27", "<": "%3C", ">": "%3E"}


def clean(url, base: str = "") -> str:
    """A usable absolute https picture address, or "" if there isn't one."""
    if not isinstance(url, str):
        return ""
    u = _ESCAPED_AMP.sub("&", url).strip()
    if not u or u.lower().startswith("data:"):
        return ""
    try:
        if u.startswith("//"):
            u = "https:" + u
        elif not _HAS_SCHEME.match(u):
            if not base:
                return ""
            u = urljoin(base, u)
        if u.lower().startswith("http://"):
            u = "https://" + u[7:]
        for char, code in _ENCODE.items():
            u = u.replace(char, code)
        if not u.lower().startswith("https://") or len(u) > 700 or re.search(r"\s", u):
            return ""
        parts = urlparse(u)
    except ValueError:          # malformed address
        return ""
    if not parts.netloc or _STAND_IN.search(parts.path):
        return ""
    return u


def pick(urls, base: str = "", limit: int = MAX_IMAGES) -> list[str]:
    """The first `limit` distinct usable addresses, in the order given."""
    out: list[str] = []
    for url in urls or []:
        u = clean(url, base)
        if u and u not in out:
            out.append(u)
            if len(out) >= limit:
                break
    return out


# ------------------------------------------------------------------ presale
# Words a store uses for "pay now, ships later". Checked in titles, tags,
# categories, stock labels and product descriptions.
PRESALE = re.compile(r"\bpre[- ]?order(?:s|ing)?\b|\bpre[- ]?sales?\b|\bpresales?\b|"
                     r"\bexpected (?:to )?ship|\bships? (?:on or )?(?:around|after|by|starting|beginning)\b|"
                     r"\bestimated (?:ship|shipping|delivery) date", re.I)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
SHIPS = re.compile(r"(?:expected (?:to )?ship(?:ping)?|ships?|shipping|estimated (?:ship|shipping|delivery)(?: date)?|"
                   r"release date|available)\s*(?:date)?\s*(?:on or )?(?:around|after|by|on|in|from|starting|beginning)?"
                   r"\s*[:\-]?\s*((?:early |mid[- ]?|late |end of )?" + _MONTH + r"(?:\s+\d{1,2}(?:st|nd|rd|th)?(?!\d))?(?:,?\s*\d{4})?"
                   r"|\d{1,2}/\d{1,2}/\d{2,4}|q[1-4]\s*\d{4})", re.I)
_TAGS = re.compile(r"<[^>]+>")


def presale_in(*texts) -> tuple[bool, str]:
    """(is presale, ship date as written) from any number of text fields."""
    found, ships = False, ""
    for text in texts:
        if not isinstance(text, str) or not text:
            continue
        text = " ".join(_TAGS.sub(" ", text).split())
        if PRESALE.search(text):
            found = True
            m = SHIPS.search(text)
            if m and not ships:
                ships = m.group(1).strip(" ,.")[:24]
    return found, ships if found else ""


# ------------------------------------------------------------ reading a store
def _optional(reader):
    """Pictures are a convenience. Whatever a store sends, reading them must
    never cost the tracker a stock reading, so any surprise means "no picture"."""
    @functools.wraps(reader)
    def guarded(*args, **kwargs):
        try:
            return reader(*args, **kwargs)
        except Exception:  # noqa: BLE001
            return {"images": [], "thumb": ""}
    return guarded


@_optional
def from_shopify(product: dict) -> dict:
    """Pictures from one product of a Shopify /products.json feed. Shopify's
    image server resizes on request, so no separate small version is needed."""
    images = product.get("images")
    images = images if isinstance(images, list) else []
    urls = [i.get("src") if isinstance(i, dict) else i for i in images]
    if not urls and isinstance(product.get("image"), dict):
        urls = [product["image"].get("src")]
    return {"images": pick(urls), "thumb": ""}


def presale_shopify(product: dict) -> dict:
    """Presale from a Shopify product: title, tags and type; then the
    description, which may be ignored later if a store repeats it everywhere."""
    try:
        tags = product.get("tags")
        tags = " ".join(tags) if isinstance(tags, list) else str(tags or "")
        strong, ships = presale_in(product.get("title"), tags, product.get("product_type"))
        weak, ships2 = presale_in(product.get("body_html"))
        return {"presale": strong, "presale_text": weak and not strong, "ships": ships or ships2}
    except Exception:  # noqa: BLE001
        return {"presale": False, "presale_text": False, "ships": ""}


def _grid_size(srcset, least: int = 480, most: int = 1100) -> str:
    """From a srcset ("a.jpg 300w, b.jpg 600w"), the smallest version that is
    still sharp in the gallery grid."""
    best = None
    for part in str(srcset or "").split(","):
        bits = part.split()
        if len(bits) == 2 and bits[1][-1:] == "w" and bits[1][:-1].isdigit():
            width = int(bits[1][:-1])
            if least <= width <= most and (best is None or width < best[0]):
                best = (width, bits[0])
    return best[1] if best else ""


@_optional
def from_woocommerce(product: dict) -> dict:
    """Pictures from one product of a WooCommerce Store API feed. Originals can
    be several megabytes, so a grid-sized version is kept alongside the first."""
    images = product.get("images")
    images = [i for i in images if isinstance(i, dict)] if isinstance(images, list) else []
    full = pick(i.get("src") for i in images)
    thumb = ""
    if full and clean(images[0].get("src")) == full[0]:
        thumb = clean(_grid_size(images[0].get("srcset"))) or clean(images[0].get("thumbnail"))
    return {"images": full, "thumb": "" if full and thumb == full[0] else thumb}


def presale_woocommerce(product: dict) -> dict:
    """Presale from a WooCommerce product: a pre-order stock label, title,
    category or tag; then the description (weaker). "On backorder" is not
    presale: several stores use it for ordinary restocking."""
    try:
        label = (product.get("stock_availability") or {}).get("text", "")
        names = " ".join(x.get("name", "") for key in ("categories", "tags")
                         for x in (product.get(key) or []) if isinstance(x, dict))
        strong, ships = presale_in(product.get("name"), label, names)
        weak, ships2 = presale_in(product.get("short_description"), product.get("description"))
        return {"presale": strong, "presale_text": weak and not strong, "ships": ships or ships2}
    except Exception:  # noqa: BLE001
        return {"presale": False, "presale_text": False, "ships": ""}


def _ld_urls(value) -> list:
    """schema.org `image` can be an address, an ImageObject, or a list of either."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return _ld_urls(value.get("contentUrl") or value.get("url"))
    if isinstance(value, list):
        return [u for v in value for u in _ld_urls(v)]
    return []


@_optional
def from_page(soup, objects: list, base: str = "") -> dict:
    """Pictures from a product page: the schema.org Product data stores embed
    for Google Shopping, otherwise the share-preview picture (og:image)."""
    urls: list = []
    for obj in objects or []:
        if not isinstance(obj, dict):
            continue
        types = obj.get("@type")
        types = types if isinstance(types, list) else [types]
        if "Product" in types or "ProductGroup" in types:
            urls += _ld_urls(obj.get("image"))
    found = pick(urls, base)
    if not found:
        for key in ("og:image:secure_url", "og:image", "twitter:image"):
            tags = soup.find_all("meta", attrs={"property": key})
            tags += soup.find_all("meta", attrs={"name": key})
            found = pick([t.get("content") for t in tags], base, limit=1)
            if found:
                break
    return {"images": found, "thumb": ""}


# ------------------------------------------------------------------ the file
def load(path: str | None = None) -> dict:
    """{(store, product_id): {"thumb": str, "images": [str, ...]}}"""
    path = path or PATH
    media: dict = {}
    if not os.path.exists(path):
        return media
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            images = pick((row.get("images") or "").split())
            presale = (row.get("presale") or "").strip() == "1"
            if row.get("store") and row.get("product_id") and (images or presale):
                media[(row["store"], row["product_id"])] = {
                    "thumb": clean(row.get("thumb") or ""), "images": images,
                    "presale": presale, "ships": (row.get("ships") or "").strip()[:24]}
    return media


def save(media: dict, path: str | None = None) -> None:
    path = path or PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = path + ".tmp"
    with open(temp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(COLS)
        for (store, product_id), m in sorted(media.items()):
            writer.writerow([store, product_id, m.get("thumb", ""), " ".join(m.get("images") or []),
                             "1" if m.get("presale") else "", m.get("ships", "") if m.get("presale") else ""])
    os.replace(temp, path)


def update(media: dict, store: str, items: list[dict], keep: set | None = None) -> int:
    """Record the pictures a store read just returned; returns how many changed.

    Products the read did not cover, or returned without a picture, keep what
    was saved before. With `keep`, only those (store, product_id) are recorded.
    """
    items = [it for it in items or [] if keep is None or (store, str(it.get("product_id", ""))) in keep]
    # A presale phrase found only in descriptions counts unless the store puts it
    # in most of its descriptions (shipping boilerplate), where it means nothing.
    text_only = [it for it in items if it.get("presale_text")]
    trust_text = len(text_only) < max(3, 0.4 * len(items))
    changed = 0
    for it in items:
        key = (store, str(it.get("product_id", "")))
        if not it.get("checked", True):
            continue
        old = media.get(key)
        if "presale" in it:
            presale = bool(it.get("presale")) or (trust_text and bool(it.get("presale_text")))
            ships = (it.get("ships") or "")[:24] if presale else ""
        else:                       # carried forward without a fresh read: keep what we knew
            presale, ships = bool((old or {}).get("presale")), (old or {}).get("ships", "")
        images = pick(it.get("images")) or (old or {}).get("images") or []
        thumb = clean(it.get("thumb") or "") if pick(it.get("images")) else (old or {}).get("thumb", "")
        if not images and not presale:
            if old:
                del media[key]
                changed += 1
            continue
        entry = {"thumb": thumb, "images": images, "presale": presale, "ships": ships}
        if old != entry:
            media[key] = entry
            changed += 1
    return changed


def prune(media: dict, keep: set) -> int:
    """Drop pictures of products that are no longer recent launches."""
    old = [key for key in media if key not in keep]
    for key in old:
        del media[key]
    return len(old)
