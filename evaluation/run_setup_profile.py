"""Setup field guide: what does a base actually look like, and does its shape
(length, depth, tightness) change the odds of the breakout working?

This is the "layer 2" the user asked for — not a signal, but a general
understanding so that when a live setup deviates from the playbook you can judge
whether there's a good reason to stay in.

Reads events.csv (point-in-time base features + forward outcomes). For real
breakout entries in the momentum universe we report:
  1. the typical base shape: depth_20 (consolidation range %), tightness_10
     (10-bar close dispersion %), contraction_5v15 (recent vs older range).
  2. whether those shapes move the odds: success = reached +2R before the stop,
     plus median 20-day forward return — bucketed by each shape metric.
  3. a lateness control (early-of-move only) so the effect isn't just "early
     breakouts do better".

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_setup_profile
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "output")

BREAKOUTS = {"breakout20", "breakout50", "gap"}


def q(s, p):
    return round(float(np.nanpercentile(s, p)), 1)


def dist(s):
    s = pd.to_numeric(s, errors="coerce").dropna()
    return {"n": int(len(s)), "p25": q(s, 25), "median": q(s, 50), "p75": q(s, 75)}


def bucket_success(df, col, edges, labels):
    """Success (reached +2R before stop) and median fwd 20d return, by bucket."""
    x = pd.to_numeric(df[col], errors="coerce")
    out = []
    for lo, hi, lab in zip(edges[:-1], edges[1:], labels):
        m = (x >= lo) & (x < hi)
        sub = df[m]
        r2 = pd.to_numeric(sub["reach_2r_before_stop"].map(
            {True: 1, False: 0, "True": 1, "False": 0}), errors="coerce").dropna()
        fwd = pd.to_numeric(sub["fwd_ret_20"], errors="coerce").dropna()
        out.append({"bucket": lab, "n": int(m.sum()),
                    "hit_2R_pct": round(float(r2.mean() * 100), 1) if len(r2) else None,
                    "med_fwd20": round(float(fwd.median()), 1) if len(fwd) else None})
    return out


def main():
    ev = pd.read_csv(os.path.join(OUT, "events.csv"), low_memory=False)
    ev = ev[ev["event_type"].isin(BREAKOUTS)].copy()
    adr = pd.to_numeric(ev["adr_pct_20"], errors="coerce")
    dv = pd.to_numeric(ev["dollar_vol_20m"], errors="coerce")
    ev = ev[(adr.between(4, 8)) & (dv >= 5)]
    print(f"{len(ev):,} breakout entries in the momentum universe (ADR 4-8, >=$5M)\n")

    report = {"n": int(len(ev)), "typical_shape": {}, "predicts": {}, "early_only": {}}

    # 1. typical base shape
    report["typical_shape"] = {
        "depth_20_pct (consolidation range)": dist(ev["depth_20"]),
        "tightness_10_pct (10-bar dispersion)": dist(ev["tightness_10"]),
        "contraction_5v15 (recent/older range)": dist(ev["contraction_5v15"]),
    }
    print("=== TYPICAL BASE SHAPE (median [p25-p75]) ===")
    for k, v in report["typical_shape"].items():
        print(f"  {k:42} {v['median']}  [{v['p25']} - {v['p75']}]")

    # 2. does shape move the odds? bucket each metric
    specs = [
        ("depth_20", [0, 15, 25, 40, 1e9], ["<15% tight", "15-25%", "25-40%", "40%+ deep"]),
        ("tightness_10", [0, 3, 5, 8, 1e9], ["<3% v.tight", "3-5%", "5-8%", "8%+ loose"]),
        ("contraction_5v15", [0, 0.5, 0.8, 1.2, 1e9], ["<0.5 tight", "0.5-0.8", "0.8-1.2", "1.2+ expand"]),
    ]
    print("\n=== DOES BASE SHAPE MOVE THE ODDS?  (hit +2R before stop | median 20d fwd) ===")
    for col, edges, labels in specs:
        rows = bucket_success(ev, col, edges, labels)
        report["predicts"][col] = rows
        print(f"  {col}:")
        for r in rows:
            print(f"     {r['bucket']:14} n={r['n']:5}  hit2R={r['hit_2R_pct']}%   medFwd20={r['med_fwd20']}%")

    # 3. lateness control: early-of-move only (first third)
    early = ev[pd.to_numeric(ev["pct_through_move"], errors="coerce") <= 33]
    print(f"\n=== LATENESS CONTROL — early-of-move only ({len(early):,} events) ===")
    for col, edges, labels in specs:
        rows = bucket_success(early, col, edges, labels)
        report["early_only"][col] = rows
        print(f"  {col}:")
        for r in rows:
            print(f"     {r['bucket']:14} n={r['n']:5}  hit2R={r['hit_2R_pct']}%   medFwd20={r['med_fwd20']}%")

    with open(os.path.join(OUT, "setup_profile.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT, 'setup_profile.json')}")


if __name__ == "__main__":
    main()
