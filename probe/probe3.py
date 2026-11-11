"""One-off: run the real collector against each new store, a few pages each."""
import json, sys, time, yaml, datetime as dt
sys.path.insert(0, ".")
import pandas as pd
from mhi import drops
cfg = yaml.safe_load(open("config.yaml"))
cfg["drops"]["max_product_checks_per_store"] = 6
cfg["drops"]["feed_max_pages"] = 2
NEW = [s for s in cfg["drops"]["stores"] if s["url"].split("//")[1].replace("www.", "").split("/")[0] in open("probe/new.txt").read().split()]
f = drops.Fetcher(); out = []
for st in NEW:
    base = st["url"].rstrip("/"); t = time.time(); r = {"store": base, "platform": st.get("platform")}
    try:
        if st.get("platform") == "shopify":
            items = drops.read_shopify(base, f, cfg)
        elif st.get("platform") == "woocommerce":
            items = drops.read_woocommerce(base, f, cfg)
        else:
            links = drops.discover_links(st, f)
            r["links"] = len(links); r["first_links"] = links[:3]
            st2 = dict(st, delay_seconds=0.5)
            items = drops.read_generic(st2, f, cfg, pd.DataFrame(), dt.date.today())
        items = items or []
        r.update(items=len(items), readable=sum(1 for i in items if i.get("available") is not None),
                 pictures=sum(1 for i in items if i.get("images")), presale=sum(1 for i in items if i.get("presale")),
                 presale_text=sum(1 for i in items if i.get("presale_text")),
                 sample=[(i.get("title", "")[:60], i.get("available"), bool(i.get("images")), i.get("presale"), i.get("ships")) for i in items[:4]],
                 presale_examples=[(i.get("title", "")[:60], i.get("ships")) for i in items if i.get("presale")][:4])
    except Exception as e:
        r["error"] = repr(e)[:200]
    r["seconds"] = round(time.time() - t)
    out.append(r); print(r["store"], r.get("items"), r.get("readable"), r.get("error", ""), flush=True)
json.dump(out, open("probe/results3.json", "w"), indent=1)
