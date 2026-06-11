"""Consistency comparison: which configuration is steadiest, and what can we
borrow from the Adaptive SuperTrend to trade R-efficiency for consistency?

Metrics per config (1R risked per trade, trades sequenced by entry date):
  - avg R (winsorized), R/30d  — the return engine
  - yearly avg-R series (years with n>=3): mean, std, worst, share <= 0
  - cumulative-R equity curve: max drawdown (in R), longest underwater (days)

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.consistency_compare
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from evaluation.strategy_opt import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")


def universe(df):
    return df[df["adr_pct_20"].between(4.0, 8.0) & (df["dollar_vol_20m"] >= 5.0)]


def fresh(df, vol_gate=True):
    m = (df["entry_ordinal"] <= 3) & (df["gain_from_move_start"] < 50) \
        & (df["spy_above_50sma"] == True)  # noqa: E712
    if vol_gate and "event_rel_vol20" in df.columns:
        m &= df["event_rel_vol20"] >= 1.5
    return df[m.fillna(False)]


def consistency(df: pd.DataFrame) -> dict:
    df = df.sort_values("date")
    r = df["r"].to_numpy(float)
    dates = pd.to_datetime(df["date"])
    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = eq - peak
    max_dd = float(dd.min()) if len(dd) else 0.0
    # longest underwater stretch in calendar days
    longest = 0
    start = None
    for i in range(len(eq)):
        if dd[i] < 0:
            if start is None:
                start = dates.iloc[i]
            longest = max(longest, (dates.iloc[i] - start).days)
        else:
            start = None
    yr = df.groupby(df["year"])["r"].agg(["mean", "count"])
    yr3 = yr[yr["count"] >= 3]
    return {
        "trade_std_r": round(float(np.std(r)), 2) if len(r) else None,
        "yearly_mean": round(float(yr3["mean"].mean()), 2) if len(yr3) else None,
        "yearly_std": round(float(yr3["mean"].std()), 2) if len(yr3) > 1 else None,
        "yearly_worst": round(float(yr3["mean"].min()), 2) if len(yr3) else None,
        "yearly_neg_share_pct": round(float((yr3["mean"] <= 0).mean() * 100), 1) if len(yr3) else None,
        "years_covered_n3": int(len(yr3)),
        "max_dd_r": round(max_dd, 1),
        "longest_underwater_days": int(longest),
        "total_r": round(float(eq[-1]), 1) if len(eq) else 0.0,
    }


def main() -> None:
    ours = pd.read_csv(os.path.join(OUT_DIR, "trades.csv"))
    events = pd.read_csv(os.path.join(OUT_DIR, "events.csv"))
    feat = events[["move_key", "date", "event_type", "adr_pct_20", "dollar_vol_20m",
                   "event_rel_vol20", "gain_from_move_start", "spy_above_50sma"]] \
        .drop_duplicates(subset=["move_key", "date", "event_type"])
    ours = ours.merge(feat, on=["move_key", "date", "event_type"], how="left")
    ours["spy_above_50sma"] = ours["spy_above_50sma"].map(
        {True: True, False: False, "True": True, "False": False})

    sa = pd.read_csv(os.path.join(OUT_DIR, "superalt_trades.csv"))
    sa["spy_above_50sma"] = sa["spy_above_50sma"].map(
        {True: True, False: False, "True": True, "False": False})
    sa_state = sa[sa["kind"] == "ours_sa_exit"][["move_key", "date", "sa_uptrend"]] \
        .drop_duplicates(subset=["move_key", "date"])
    ours = ours.merge(sa_state, on=["move_key", "date"], how="left")

    def cfg(stop, exit_):
        return fresh(universe(ours[(ours["stop"] == stop) & (ours["exit"] == exit_)]))

    configs = {
        "A  LOD/E50 (headline)": cfg("LOD", "E50"),
        "B  SW10C/E50": cfg("SW10C", "E50"),
        "C  ATR10/E50": cfg("ATR10", "E50"),
        "F  LOD/P3_E20 (bank 1/3 at 3R)": cfg("LOD", "P3_E20"),
        "H  SW10C/P3_E20": cfg("SW10C", "P3_E20"),
        "D  ours entries + SA flip exit": fresh(universe(sa[sa["kind"] == "ours_sa_exit"])),
        "E  SuperAlt full system": fresh(universe(sa[sa["kind"] == "sa_system"]), vol_gate=False),
        "G1 LOD/E50 + SA-uptrend gate": cfg("LOD", "E50").pipe(
            lambda d: d[d["sa_uptrend"] == True]),  # noqa: E712
        "G2 SW10C/E50 + SA-uptrend gate": cfg("SW10C", "E50").pipe(
            lambda d: d[d["sa_uptrend"] == True]),  # noqa: E712
        "G3 SW10C/P3_E20 + SA-uptrend gate": cfg("SW10C", "P3_E20").pipe(
            lambda d: d[d["sa_uptrend"] == True]),  # noqa: E712
    }

    results = {}
    print(f"{'config':36} {'n':>5} {'win':>6} {'Rw99':>6} {'R/30d':>6} | "
          f"{'yrStd':>6} {'yrWorst':>8} {'neg%':>5} {'maxDD':>7} {'underwtr':>9} {'totR':>7}")
    for name, df in configs.items():
        s = stats(df)
        c = consistency(df)
        results[name] = {"stats": s, "consistency": c}
        print(f"{name:36} {s['n']:5} {s['win_pct']:5}% {s['avg_r_w99']:6} {s['r_per_30d']:6} | "
              f"{c['yearly_std']!s:>6} {c['yearly_worst']!s:>8} {c['yearly_neg_share_pct']!s:>5} "
              f"{c['max_dd_r']:7} {c['longest_underwater_days']:8}d {c['total_r']:7}")

    with open(os.path.join(OUT_DIR, "consistency_results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT_DIR, 'consistency_results.json')}")


if __name__ == "__main__":
    main()
