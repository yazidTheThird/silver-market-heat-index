"""Checks which signals actually predicted your sellout speed, and suggests new weights.

Fill data/releases.csv after every release (yours, and competitors' when you know
how fast they sold), then run:

    python calibrate.py

Needs at least 8 releases to say anything; 15-20+ before trusting the suggested weights.
"""
from __future__ import annotations

import math
import os

import numpy as np
import pandas as pd
import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
COMPONENTS = ["drops", "ebay", "attention", "silver", "calendar"]


def spearman(a: pd.Series, b: pd.Series) -> float | None:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < 5:
        return None
    r = df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank())
    return None if r != r else float(r)


def main() -> None:
    rel = pd.read_csv(os.path.join(ROOT, "data", "releases.csv"))
    hist = pd.read_csv(os.path.join(ROOT, "data", "history.csv"))
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))

    rel = rel.dropna(subset=["launch_date", "hours_to_sellout"])
    if len(rel) < 8:
        print(f"Only {len(rel)} releases logged — need at least 8 (ideally 15-20).")
        return

    rel["launch_date"] = pd.to_datetime(rel["launch_date"])
    hist["date"] = pd.to_datetime(hist["date"])
    merged = pd.merge_asof(rel.sort_values("launch_date"), hist.sort_values("date"),
                           left_on="launch_date", right_on="date", direction="backward")
    # Speed: bigger = sold faster. Log scale so 1h vs 3h matters as much as 1wk vs 3wk.
    merged["speed"] = -np.log1p(merged["hours_to_sellout"].astype(float))
    if "waitlist" in merged and "mintage" in merged:
        merged["waitlist_ratio"] = merged["waitlist"] / merged["mintage"]

    print(f"\n{len(merged)} releases matched to index history\n")
    print(f"{'signal':<22}{'correlation with speed':>24}")
    print("-" * 46)
    corr = {}
    for col in ["index"] + [f"score_{c}" for c in COMPONENTS] + ["waitlist_ratio"]:
        if col in merged:
            r = spearman(merged[col], merged["speed"])
            corr[col] = r
            print(f"{col:<22}{('n/a' if r is None else f'{r:+.2f}'):>24}")

    print("\n+1.00 = perfectly predicts fast sellouts, 0 = no relationship, negative = misleading.")

    useful = {c: max(0.0, corr.get(f"score_{c}") or 0.0) for c in COMPONENTS}
    if sum(useful.values()) == 0:
        print("\nNo component shows a positive relationship yet — keep logging releases.")
        return
    total = sum(useful.values())
    current = cfg["weights"]
    cur_total = sum(current.values())
    print("\nSuggested weights (blend 50/50 with current to avoid over-fitting a small sample):")
    for c in COMPONENTS:
        data_w = 100 * useful[c] / total
        cur_w = 100 * current[c] / cur_total
        print(f"  {c:<10} current {cur_w:5.1f}  ->  suggested {0.5 * data_w + 0.5 * cur_w:5.1f}")
    wr = corr.get("waitlist_ratio")
    if wr is not None and wr > (corr.get("index") or 0):
        print("\nNote: your waitlist/mintage ratio predicts sellout speed better than the market "
              "index. Use the index to pick the launch window, and the waitlist to size mintage.")
    print("\nEdit the weights in config.yaml if you agree.")


if __name__ == "__main__":
    main()
