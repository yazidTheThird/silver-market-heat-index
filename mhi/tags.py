"""What's hot, not just how hot: tags every tracked product by theme, base coin,
size and metal (from its title), then ranks each group by how fast it sells out.

Output: data/hot_groups.csv, a section on the dashboard, and a weekly Telegram digest.

Two kinds of numbers per group:
  * launch stats  — products we saw launch (not baseline): how many sold out, and how
                    fast (hours when the fast checker timed it, otherwise days).
                    This is the real heat signal; it fills in over a few weeks.
  * snapshot      — share of ALL tracked products in the group that are sold out
                    right now (including baseline ones). Weaker (old items had more
                    time to sell), but useful from day one.

Rules live in config.yaml under `tags:` and can be edited there; the defaults below
are used for anything not set.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import statistics

import pandas as pd

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(ROOT, "data", "hot_groups.csv")

DEFAULT_RULES = {
    # A product can carry several themes (a "skull dragon" counts for both).
    "themes": {
        "Dragons": r"dragon|wyvern|drago\b",
        "Skulls & horror": r"skull|reaper|zombie|undead|horror|halloween|haunt|ghost|phantom|"
                           r"vampire|demon|devil|graveyard|muertos|day of the dead|calavera|"
                           r"grim|death|hell|sins?\b",
        "Mythology & gods": r"zeus|poseidon|hades|athena|medusa|odin|thor|loki|valkyr|norse|"
                            r"viking|anubis|osiris|horus|\bra\b|pharaoh|egypt|aztec|mayan|"
                            r"myth|gods?\b|goddess|titan|kraken|hydra|griffin|phoenix|pegasus|mermaid|"
                            r"unicorn|ouroboros|tutankh|cleopatra",
        "Patriotic & USA 250": r"\b250\b|semiquincentennial|independence|liberty bell|patriot|"
                               r"america|\busa?\b|flag|freedom|constitution|9/11|marines|navy|"
                               r"army|veteran|god bless",
        "Lunar & zodiac": r"lunar|zodiac|year of the|aries|taurus|gemini|cancer\b|leo\b|virgo|"
                          r"libra|scorpio|sagittarius|capricorn|aquarius|pisces",
        "Wildlife": r"wolf|lion|tiger|bear|grizzly|owl|eagle owl|horse|stag|elk|deer|bison|"
                    r"buffalo|shark|snake|rattlesnake|octopus|butterfly|bee\b|panda|koala|"
                    r"kangaroo|kookaburra|falcon|hawk|fox|elephant|rhino|leopard|jaguar|"
                    r"flamingo|chameleon|frog|turtle|whale|dolphin|spider|scarab|raven|"
                    r"orca|crane|cheetah|crab|fish|bird|parrot|peacock|gorilla|cat\b|dog\b",
        "Pop culture & brands": r"star wars|marvel|disney|batman|superman|dc comics|harry potter|"
                                r"deadpool|spider-?man|mickey|pokemon|coca-?cola|coke|"
                                r"looney|godzilla|transformers|anime|tarot|lord of the rings|"
                                r"stranger things|top gun|invincible|skybound|tonka|peppa|"
                                r"diablo|veefriends|silent films|movie|film|tv series|"
                                r"poster|comic|video game|bitcoin|alien|ufo",
        "Sports": r"football|basketball|baseball|soccer|tennis|golf|volleyball|hockey|"
                  r"\bmlb\b|\bnba\b|\bnfl\b|\bnhl\b|fifa|world cup|maradona|olympic|racing",
        "Art & history": r"botticelli|titian|da vinci|van gogh|monet|venus|primavera|mona lisa|"
                         r"art gallery|masterpiece|atlas|history|historic|tutankh|founding fathers|"
                         r"custer|napoleon|lighthouse|steam|locomotive",
        "Luck & fortune": r"luck|lucky|clover|leprechaun|fortune|horseshoe|four[- ]leaf",
        "Space & celestial": r"space|galaxy|cosmic|nebula|moon|celestial|planet|eclipse|"
                             r"astronaut|star(s|ry)?\b|supergiant|solar|voyager",
        "Faith": r"cross\b|angel|jesus|christ|saint|\bst\.|madonna|psalm|prayer|bible|"
                 r"archangel|michael|guadalupe|ganesha|buddha",
        "Holidays": r"christmas|navidad|santa|gingerbread|easter|valentine|thanksgiving|"
                    r"new year|holiday|tooth fairy",
        "Warriors": r"samurai|ninja|spartan|knight|warrior|gladiator|pirate|templar|"
                    r"crusader|legion",
        "Flowers & nature": r"rose\b|flower|floral|blossom|bloom|garden|forest|tree|"
                            r"four seasons|autumn|winter|spring|summer|lotus",
    },
    # One base coin per product; first match wins (order matters).
    "base_coins": {
        "Libertad": r"libertad",
        "Silver Eagle": r"silver eagle|american eagle|\base\b|u\.?s\.? eagle|walking liberty",
        "Maple Leaf": r"maple",
        "Britannia": r"britannia",
        "Kangaroo/Koala/Kookaburra": r"kangaroo|koala|kookaburra",
        "Panda": r"panda",
        "Krugerrand": r"krugerrand",
        "Philharmonic": r"philharmonic",
        "Perth Lunar": r"perth.*lunar|lunar.*perth|australia lunar|lunar series",
        "Half dollar": r"half dollar",
        "Bar": r"\bbar\b",
        "Round/medal": r"\bround\b|medal",
        "Other mint coins (Niue, Cook Is., Cameroon…)": r".",
    },
    # Finish / technique — the part closest to CCB's colorization work.
    "finishes": {
        "Diamond dust": r"diamond dust",
        "Gilded / gold-plated": r"gild|gold[- ]plated|gold accent|gold flakes|24k",
        "Black proof / ruthenium": r"black (proof|platinum|ruthenium)|ruthenium|black diamond|"
                                   r"triple black",
        "Antiqued / high relief": r"antiqu|high relief|ultra high relief|\buhr\b|smartminting",
        "Holographic / iridescent": r"holograph|iridesc|rainbow|prism",
        "Gem / crystal inlay": r"bejewel|crystal|swarovski|gem\b|gemstone|amethyst|sapphire|"
                               r"ruby|emerald|opal",
        "Glow / special ink": r"glow|uv ink|neon|luminous",
        "Plain colorized": r".",
    },
    "metals": {
        "Gold": r"\bgold\b(?! plated| gilded| accent| flakes)",
        "Copper": r"copper",
        "Silver": r"silver|\bag\b|\.999|half dollar|libertad|maple|britannia|eagle",
        "Base metal": r"base metal|nickel|dime|\$2 bill",
    },
}


# Bullion coins that are 1 oz unless the title says otherwise.
ONE_OZ_BY_DEFAULT = {"Silver Eagle", "Maple Leaf", "Libertad", "Britannia", "Krugerrand",
                     "Philharmonic", "Kangaroo/Koala/Kookaburra"}


# ------------------------------------------------------------------ tagging
def _rules(cfg: dict) -> dict:
    user = (cfg or {}).get("tags") or {}
    return {k: user.get(k) or v for k, v in DEFAULT_RULES.items()}


def size_of(title: str) -> str:
    t = title.lower().replace("½", "1/2").replace("¼", "1/4")
    if re.search(r"\bkilo\b|\b1\s?kg\b|\bkg\b", t):
        return "Kilo"
    if "half dollar" in t:
        return "Half dollar"
    m = re.search(r"(\d+\s?/\s?\d+|\d*\.\d+|\d+)\s*(?:-?\s*troy)?\s*-?\s*(?:oz|ounce|onza)", t)
    if m:
        v = m.group(1).replace(" ", "")
        oz = eval_fraction(v)
        if oz is None:
            return "Other"
        if oz < 0.5:
            return "Under 1/2 oz"
        if oz < 1:
            return "1/2 oz"
        if oz == 1:
            return "1 oz"
        if oz <= 3:
            return "2–3 oz"
        if oz <= 5:
            return "5 oz"
        return "10 oz+"
    g = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gram|grams)\b", t)
    if g:
        grams = float(g.group(1))
        if grams >= 900:
            return "Kilo"
        if grams >= 150:
            return "10 oz+" if grams >= 300 else "5 oz"
        if grams >= 28:
            return "1 oz"
        return "Under 1/2 oz" if grams < 15 else "1/2 oz"
    return "Other"


def eval_fraction(v: str) -> float | None:
    try:
        if "/" in v:
            a, b = v.split("/")
            return float(a) / float(b)
        return float(v)
    except (ValueError, ZeroDivisionError):
        return None


def tag(title: str, rules: dict) -> dict:
    t = (title or "").lower()
    themes = [name for name, rx in rules["themes"].items() if re.search(rx, t)]
    base = next((name for name, rx in rules["base_coins"].items() if re.search(rx, t)), "Other")
    metal = next((name for name, rx in rules["metals"].items() if re.search(rx, t)), "Unknown")
    finish = next((name for name, rx in rules["finishes"].items() if re.search(rx, t)),
                  "Plain colorized")
    size = size_of(t)
    if size == "Other" and base in ONE_OZ_BY_DEFAULT:
        size = "1 oz"          # "2026 Silver Eagle – Storm Edition" is a 1 oz coin
    return {"themes": themes or ["Other"], "base_coin": base, "size": size, "metal": metal,
            "finish": finish}


def tag_state(state: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    rules = _rules(cfg)
    tags = state["title"].fillna("").map(lambda s: tag(s, rules))
    d = state.copy()
    d["themes"] = tags.map(lambda x: x["themes"])
    d["base_coin"] = tags.map(lambda x: x["base_coin"])
    d["size"] = tags.map(lambda x: x["size"])
    d["metal"] = tags.map(lambda x: x["metal"])
    d["finish"] = tags.map(lambda x: x["finish"])
    return d


# ------------------------------------------------------------------ ranking
def _ts(s) -> pd.Timestamp | None:
    if s is None or (isinstance(s, float) and s != s) or str(s).strip() == "":
        return None
    t = pd.to_datetime(str(s), errors="coerce", utc=True)
    return None if pd.isnull(t) else t


def sellout_hours(row) -> float | None:
    """Hours from launch to sell-out, using the most precise timestamps we have."""
    if str(row.get("baseline", "")) == "1" and not (_ts(row.get("published_at"))
                                                     or _ts(row.get("published"))):
        return None   # was already on the store when tracking began: launch time unknown
    end = _ts(row.get("sold_out_at")) or _ts(row.get("sold_out_date"))
    start = (_ts(row.get("published_at")) or _ts(row.get("first_seen_at"))
             or _ts(row.get("published")) or _ts(row.get("first_seen")))
    if end is None or start is None:
        return None
    h = (end - start).total_seconds() / 3600
    return max(0.0, h)


def hot_groups(state: pd.DataFrame, cfg: dict, today: dt.date) -> pd.DataFrame:
    tcfg = (cfg or {}).get("hot_groups") or {}
    window = tcfg.get("window_days", 90)
    min_n = tcfg.get("min_launches", 3)
    fast_h = tcfg.get("fast_hours", 48)
    mature = tcfg.get("mature_days", 7)
    metals = [m.lower() for m in tcfg.get("metals", ["Silver"])]

    d = tag_state(state, cfg)
    d = d[d["metal"].str.lower().isin(metals)] if metals else d
    if d.empty:
        return pd.DataFrame()
    d = d.copy()
    d["sold"] = d["available"].astype(str) == "0"
    d["hours"] = [sellout_hours(r) for r in d.to_dict("records")]
    first = pd.to_datetime(d["first_seen"], errors="coerce").dt.date
    pub = pd.to_datetime(d["published"].astype(str).str[:10], errors="coerce").dt.date
    launch = pub.fillna(first)
    d["is_launch"] = (d["baseline"].astype(str) != "1") | pub.notnull()
    age = launch.map(lambda x: (today - x).days if pd.notnull(x) else None)
    d["recent"] = age.map(lambda a: a is not None and a <= window)
    # A launch only counts toward "share sold out" once it has had `mature_days` to sell;
    # otherwise brand-new launches make every group look cold.
    d["mature"] = age.map(lambda a: a is not None and a >= mature)

    rows = []
    dims = {"Theme": d.explode("themes").rename(columns={"themes": "group"}),
            "Base coin": d.rename(columns={"base_coin": "group"}),
            "Size": d.rename(columns={"size": "group"}),
            "Finish": d.rename(columns={"finish": "group"})}
    for dim, frame in dims.items():
        for grp, g in frame.groupby("group"):
            seen = g[g["is_launch"] & g["recent"]]
            launches = seen[seen["mature"]]
            # Timed sell-outs: any recent launch we watched sell out (young ones too).
            hours = [h for h in seen["hours"] if h is not None and h == h]
            n = len(launches)
            row = {
                "dimension": dim, "group": grp,
                "tracked": int(len(g)),
                "snapshot_soldout_share": round(float(g["sold"].mean()), 3),
                "launches": n,
                "launch_soldout_share": round(float(launches["sold"].mean()), 3) if n else None,
                "sellouts_timed": len(hours),
                "median_hours_to_sellout": round(statistics.median(hours), 1) if hours else None,
                "fast_share": round(sum(h <= fast_h for h in hours) / len(hours), 3) if hours else None,
            }
            row["heat"] = heat_score(row, min_n)
            rows.append(row)
    out = pd.DataFrame(rows)
    out["confidence"] = out.apply(lambda r: confidence(r, min_n), axis=1)
    out = out.sort_values(["dimension", "heat"], ascending=[True, False], na_position="last")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.to_csv(OUT, index=False)
    return out


def heat_score(r: dict, min_n: int) -> float | None:
    """0–100 per group. Uses launch stats when there are enough launches; otherwise
    falls back to the sold-out snapshot (marked low confidence)."""
    if r["launches"] >= min_n and r["launch_soldout_share"] is not None:
        parts = [r["launch_soldout_share"] * 100]
        if r["fast_share"] is not None and r["sellouts_timed"] >= 2:
            parts.append(r["fast_share"] * 100)
        if r["median_hours_to_sellout"] is not None and r["sellouts_timed"] >= 2:
            # 0 h -> 100, 1 week+ -> 0
            parts.append(max(0.0, 100 - r["median_hours_to_sellout"] / 168 * 100))
        return round(sum(parts) / len(parts), 1)
    if r["tracked"] >= 5:
        return round(r["snapshot_soldout_share"] * 100, 1)
    return None


def confidence(r, min_n: int) -> str:
    if r["launches"] >= min_n and r["sellouts_timed"] >= min_n:
        return "high"
    if r["launches"] >= min_n:
        return "medium"
    if r["tracked"] >= 5:
        return "low (snapshot)"
    return "too few"


def digest(groups: pd.DataFrame, top: int = 3) -> str:
    """Short weekly text for Telegram: hottest and coldest groups per dimension.
    Groups backed by real launch data are marked; snapshot-only guesses get a "~"."""
    if groups is None or groups.empty:
        return ""
    lines = ["What's hot (silver) — heat 0-100:"]
    cold_all = []
    for dim in ["Theme", "Base coin", "Size", "Finish"]:
        g = groups[(groups["dimension"] == dim) & groups["heat"].notnull()
                   & ~groups["group"].isin(["Other", "Plain colorized"])
                   & (groups["confidence"] != "too few")]
        if g.empty:
            continue
        g = g.assign(_real=g["confidence"].isin(["high", "medium"]))
        hot = g[g["heat"] >= 50].sort_values(["_real", "heat"], ascending=False).head(top)
        cold_all += [r for r in g[g["_real"] & (g["heat"] < 30)].itertuples()]
        if hot.empty:
            continue
        lines.append(f"{dim}: " + " · ".join(_fmt(r) for r in hot.itertuples()))
    if cold_all:
        cold_all.sort(key=lambda r: r.heat)
        lines.append("Cold: " + " · ".join(_fmt(r) for r in cold_all[:top]))
    if len(lines) == 1:
        return ""
    if not groups["confidence"].isin(["high", "medium"]).any():
        lines.append("(early read: ~ = based on what's sold out now, not timed launches yet)")
    else:
        lines.append("~ = early read from what's sold out now")
    return "\n".join(lines)


def _fmt(r) -> str:
    mark = "" if r.confidence in ("high", "medium") else "~"
    hrs = (f" ({r.median_hours_to_sellout:.0f}h)" if pd.notnull(r.median_hours_to_sellout)
           else "")
    return f"{mark}{r.group} {r.heat:.0f}{hrs}"
