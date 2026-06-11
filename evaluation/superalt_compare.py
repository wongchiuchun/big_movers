"""Head-to-head: Adaptive SuperTrend vs our strategy, risk-normalized (R-based).

Three comparisons, all on the same universe (ADR 4-8%, >=$5M dollar vol):
  1. complete systems, unfiltered: SA flips/ST-stop/flip-exit  vs  LOD/E50
  2. complete systems, freshness-filtered (ordinal<=3, extension<50%,
     relvol>=1.5, SPY>50SMA applied to BOTH)
  3. exit duel on identical entries + identical LOD stop: SA flip-exit vs E50

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.superalt_compare
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluation.strategy_opt import stats, per_year

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")


def universe(df):
    return df[df["adr_pct_20"].between(4.0, 8.0) & (df["dollar_vol_20m"] >= 5.0)]


def fresh(df):
    m = (df["entry_ordinal"] <= 3) & (df["gain_from_move_start"] < 50) \
        & (df["event_rel_vol20"] >= 1.5) & (df["spy_above_50sma"] == True)  # noqa: E712
    return df[m.fillna(False)]


def fresh_no_vol(df):
    """SA flips are not volume events; volume filter would be unfair to it.
    Variant without the relvol gate for sensitivity."""
    m = (df["entry_ordinal"] <= 3) & (df["gain_from_move_start"] < 50) \
        & (df["spy_above_50sma"] == True)  # noqa: E712
    return df[m.fillna(False)]


def main() -> None:
    sa = pd.read_csv(os.path.join(OUT_DIR, "superalt_trades.csv"))
    sa["spy_above_50sma"] = sa["spy_above_50sma"].map(
        {True: True, False: False, "True": True, "False": False})
    ours = pd.read_csv(os.path.join(OUT_DIR, "trades.csv"))
    events = pd.read_csv(os.path.join(OUT_DIR, "events.csv"))
    feat = events[["move_key", "date", "event_type", "adr_pct_20", "dollar_vol_20m",
                   "event_rel_vol20", "gain_from_move_start", "spy_above_50sma"]] \
        .drop_duplicates(subset=["move_key", "date", "event_type"])
    ours = ours.merge(feat, on=["move_key", "date", "event_type"], how="left")
    ours["spy_above_50sma"] = ours["spy_above_50sma"].map(
        {True: True, False: False, "True": True, "False": False})

    lod_e50 = universe(ours[(ours["stop"] == "LOD") & (ours["exit"] == "E50")])
    sa_sys = universe(sa[sa["kind"] == "sa_system"]).copy()
    sa_sys["event_rel_vol20"] = sa_sys["event_rel_vol20"]  # present from features_at
    ours_sa = universe(sa[sa["kind"] == "ours_sa_exit"]).copy()
    # exit-duel needs the volume feature; ours_sa carries it from features_at
    # restrict the duel to the SAME (move_key, date) set on both sides
    f_lod = fresh(lod_e50)
    f_oursa = fresh(ours_sa)
    keys = f_lod[["move_key", "date"]].drop_duplicates().merge(
        f_oursa[["move_key", "date"]].drop_duplicates(), on=["move_key", "date"])
    duel_e50 = f_lod.merge(keys, on=["move_key", "date"])
    duel_sa = f_oursa.merge(keys, on=["move_key", "date"])

    out = {
        "1_systems_unfiltered": {
            "ours_LOD_E50": stats(lod_e50),
            "superalt": stats(sa_sys),
        },
        "2_systems_freshness_filtered": {
            "ours_LOD_E50": stats(fresh(lod_e50)),
            "superalt": stats(fresh(sa_sys)),
            "superalt_no_vol_filter": stats(fresh_no_vol(sa_sys)),
        },
        "3_exit_duel_same_entries_same_stop": {
            "n_common_entries": int(len(keys)),
            "E50_exit": stats(duel_e50),
            "superalt_flip_exit": stats(duel_sa),
        },
        "per_year": {
            "ours_filtered": per_year(fresh(lod_e50)),
            "superalt_filtered": per_year(fresh_no_vol(sa_sys)),
        },
        "notes": [
            "R-normalized: each trade's R uses its own system's natural stop "
            "(ours: entry-day low; SuperAlt: the ST line ~3 adaptive-ATR below price).",
            "SuperAlt's wide stop means a much smaller position for the same $ risk; "
            "R comparison fully accounts for that.",
            "Winners-only bank: both systems' absolute numbers are inflated equally; "
            "the comparison is the meaningful part.",
        ],
    }
    with open(os.path.join(OUT_DIR, "superalt_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)

    for section, data in out.items():
        if section in ("per_year", "notes"):
            continue
        print(f"\n=== {section} ===")
        for name, s in data.items():
            if isinstance(s, dict) and "n" in s:
                print(f"  {name:24} n={s['n']:6} win={s['win_pct']:5}% avgR={s['avg_r']:6.2f} "
                      f"(w99 {s['avg_r_w99']:5.2f}) med={s['med_r']:5.2f} p90={s['p90_r']:5.1f} "
                      f"days={s['avg_days']:6} R/30d={s['r_per_30d']}")
            else:
                print(f"  {name}: {s}")
    yrs_ours = out["per_year"]["ours_filtered"]
    yrs_sa = out["per_year"]["superalt_filtered"]
    pos_o = sum(1 for v in yrs_ours.values() if v["n"] >= 5 and v["avg_r"] > 0)
    tot_o = sum(1 for v in yrs_ours.values() if v["n"] >= 5)
    pos_s = sum(1 for v in yrs_sa.values() if v["n"] >= 5 and v["avg_r"] > 0)
    tot_s = sum(1 for v in yrs_sa.values() if v["n"] >= 5)
    print(f"\nyear consistency (n>=5): ours {pos_o}/{tot_o} positive, superalt {pos_s}/{tot_s} positive")


if __name__ == "__main__":
    main()
