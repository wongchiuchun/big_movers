"""Strategy optimization over the simulated policy grid.

Goal (user-specified): maximize expectancy (avg R per trade) subject to a
top-trader win-rate band of ~25-45%, with ADR in the 4-8% sweet spot.
NOT optimizing win rate — optimizing total R with acceptable trade frequency.

Anti-overfit discipline:
  - candidate filters are pre-registered from the myth study's CONFIRMED signals
    (close-in-range, entry ordinal/extension, tightness, volume, regime) — no
    free-form mining
  - every reported config carries per-year stats and an odd/even-year split
  - expectancies are reported both raw and winsorized at the 99th percentile

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.strategy_opt
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")

ADR_LO, ADR_HI = 4.0, 8.0
MIN_DOLLAR_VOL_M = 5.0  # $5M/day 20d avg — liquidity floor that still keeps the 2000s data
WIN_BAND = (25.0, 45.0)


def load() -> pd.DataFrame:
    trades = pd.read_csv(os.path.join(OUT_DIR, "trades.csv"))
    events = pd.read_csv(os.path.join(OUT_DIR, "events.csv"))
    feat_cols = ["move_key", "date", "event_type", "close_in_range", "adr_pct_20",
                 "dollar_vol_20m", "tightness_10", "spy_above_50sma", "ema_stack_bull",
                 "trail60_ema10_adh", "pct_off_52wk_high", "event_rel_vol20",
                 "prior_gain_3m", "gain_from_move_start", "depth_20", "trail60_sma50_touches"]
    ev = events[feat_cols].drop_duplicates(subset=["move_key", "date", "event_type"])
    df = trades.merge(ev, on=["move_key", "date", "event_type"], how="left")
    for c in ("spy_above_50sma", "ema_stack_bull"):
        df[c] = df[c].map({True: True, False: False, "True": True, "False": False})
    return df


def stats(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {"n": 0}
    r = df["r"].to_numpy(float)
    cap = np.quantile(r, 0.99)
    return {
        "n": int(len(df)),
        "win_pct": round(float((r > 0).mean() * 100), 1),
        "avg_r": round(float(r.mean()), 3),
        "avg_r_w99": round(float(np.minimum(r, cap).mean()), 3),
        "med_r": round(float(np.median(r)), 2),
        "p90_r": round(float(np.quantile(r, 0.90)), 2),
        "pct_ge_5r": round(float((r >= 5).mean() * 100), 1),
        "worst_r": round(float(r.min()), 2),
        "avg_days": round(float(df["days"].mean()), 1),
        "r_per_30d": round(float(r.mean() / max(df["days"].mean(), 1) * 30), 2),
    }


def per_year(df: pd.DataFrame) -> dict:
    return {int(y): {"n": int(len(s)), "win_pct": round(float((s["r"] > 0).mean() * 100), 1),
                     "avg_r": round(float(s["r"].mean()), 2)}
            for y, s in df.groupby("year")}


def year_split(df: pd.DataFrame) -> dict:
    odd = df[df["year"] % 2 == 1]
    even = df[df["year"] % 2 == 0]
    early = df[df["year"] <= 2012]
    late = df[df["year"] >= 2013]
    return {"odd_years": stats(odd), "even_years": stats(even),
            "2000-2012": stats(early), "2013-2026": stats(late)}


def base_universe(df: pd.DataFrame) -> pd.DataFrame:
    """User-specified momentum universe: ADR 4-8%, liquid enough to trade."""
    return df[df["adr_pct_20"].between(ADR_LO, ADR_HI)
              & (df["dollar_vol_20m"] >= MIN_DOLLAR_VOL_M)]


def policy_league(df: pd.DataFrame) -> list[dict]:
    rows = []
    for (sk, ek), sub in df.groupby(["stop", "exit"]):
        s = stats(sub)
        s.update({"stop": sk, "exit": ek,
                  "in_band": WIN_BAND[0] <= (s.get("win_pct") or 0) <= WIN_BAND[1]})
        rows.append(s)
    rows.sort(key=lambda x: -(x.get("avg_r_w99") or -99))
    return rows


FILTERS = {
    "ordinal_le3": lambda d: d["entry_ordinal"] <= 3,
    "extension_lt50": lambda d: d["gain_from_move_start"] < 50,
    "cir_gt75_gaps": lambda d: (d["event_type"] != "gap") | (d["close_in_range"] > 75),
    "relvol_ge15": lambda d: d["event_rel_vol20"] >= 1.5,
    "tight_lt5": lambda d: d["tightness_10"] < 5,
    "spy_above_50": lambda d: d["spy_above_50sma"] == True,  # noqa: E712
    "near_high_25": lambda d: d["pct_off_52wk_high"] >= -25,
    "stack_bull": lambda d: d["ema_stack_bull"] == True,  # noqa: E712
}


def filter_marginals(df: pd.DataFrame) -> dict:
    out = {}
    for name, fn in FILTERS.items():
        try:
            mask = fn(df).fillna(False)
        except Exception:
            continue
        out[name] = {"pass": stats(df[mask]), "fail": stats(df[~mask])}
    return out


def apply_filters(df: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    m = pd.Series(True, index=df.index)
    for n in names:
        m &= FILTERS[n](df).fillna(False)
    return df[m]


def regime_split(df: pd.DataFrame) -> dict:
    up = df[df["spy_above_50sma"] == True]   # noqa: E712
    dn = df[df["spy_above_50sma"] == False]  # noqa: E712
    return {"spy_above_50sma": stats(up), "spy_below_50sma": stats(dn)}


def main() -> None:
    df = load()
    print(f"loaded {len(df):,} trades over {df.groupby(['move_key','date']).ngroups:,} entries")

    uni = base_universe(df)
    print(f"after ADR {ADR_LO}-{ADR_HI}% + ${MIN_DOLLAR_VOL_M}M liquidity: "
          f"{len(uni):,} trades / {uni.groupby(['move_key','date']).ngroups:,} entries")

    league = policy_league(uni)
    in_band = [p for p in league if p["in_band"]]
    print("\n=== POLICY LEAGUE (win-rate band 25-45%, by winsorized avg R) ===")
    for p in in_band[:10]:
        print(f"  {p['stop']:8}{p['exit']:8} n={p['n']:6} win={p['win_pct']:5}% "
              f"avgR={p['avg_r']:6.2f} (w99 {p['avg_r_w99']:5.2f}) med={p['med_r']:5.2f} "
              f"p90={p['p90_r']:5.1f} ge5R={p['pct_ge_5r']:4}% days={p['avg_days']:5} r/30d={p['r_per_30d']}")

    # pick top 3 in-band policies for filter work; if the band is empty,
    # fall back to the policies closest to the band's center
    top = in_band[:3]
    if not top:
        league_sorted = sorted(league, key=lambda p: abs((p.get("win_pct") or 0) - 35))
        top = league_sorted[:3]
        print("  (no policy inside the 25-45% band — using nearest-band fallback)")
    # always include the realistic long-hold variant for the playbook comparison
    if not any(p["stop"] == "SW10C" and p["exit"] == "E50" for p in top):
        extra = next((p for p in league if p["stop"] == "SW10C" and p["exit"] == "E50"), None)
        if extra:
            top.append(extra)
    results = {"universe": {"adr": [ADR_LO, ADR_HI], "min_dollar_vol_m": MIN_DOLLAR_VOL_M,
                            "base_stats": stats(uni)},
               "policy_league": league, "top_policies": []}

    for p in top:
        sub = uni[(uni["stop"] == p["stop"]) & (uni["exit"] == p["exit"])]
        marg = filter_marginals(sub)
        print(f"\n=== FILTER MARGINALS for {p['stop']}/{p['exit']} ===")
        keep = []
        for name, m in marg.items():
            dpass, dfail = m["pass"], m["fail"]
            edge = (dpass.get("avg_r_w99") or 0) - (dfail.get("avg_r_w99") or 0)
            print(f"  {name:18} pass: n={dpass.get('n',0):5} win={dpass.get('win_pct')}% "
                  f"avgRw={dpass.get('avg_r_w99')} | fail: n={dfail.get('n',0):5} "
                  f"avgRw={dfail.get('avg_r_w99')} | edge={edge:+.2f}")
            if edge >= 0.15 and (dpass.get("n") or 0) >= 300:
                keep.append((name, edge))
        keep.sort(key=lambda x: -x[1])
        kept_names = [k for k, _ in keep[:4]]
        filtered = apply_filters(sub, kept_names)
        entry = {
            "stop": p["stop"], "exit": p["exit"], "base": stats(sub),
            "filter_marginals": marg, "kept_filters": kept_names,
            "filtered": stats(filtered),
            "filtered_year_split": year_split(filtered),
            "filtered_per_year": per_year(filtered),
            "filtered_regime": regime_split(filtered),
            "exit_by_regime": {},
        }
        # regime-dependent exit comparison on the filtered entries WITHOUT the
        # SPY regime filter (otherwise the below-50SMA bucket is empty)
        kept_nospy = [k for k in kept_names if k != "spy_above_50"]
        filtered_nospy = apply_filters(sub, kept_nospy)
        keys = filtered_nospy[["move_key", "date"]].drop_duplicates()
        same_entries = uni.merge(keys, on=["move_key", "date"])
        for ek in ("E10", "E20", "CH25", "BE_E20", "P3_E20", "E50"):
            alt = same_entries[(same_entries["stop"] == p["stop"]) & (same_entries["exit"] == ek)]
            entry["exit_by_regime"][ek] = regime_split(alt)
        entry["filtered_nospy_regime"] = regime_split(
            filtered_nospy if p["exit"] != "FIX" else filtered_nospy)
        results["top_policies"].append(entry)
        print(f"  kept: {kept_names} -> filtered: {entry['filtered']}")

    # headline = best filtered time-efficiency (R per 30 days), realistic exits first
    results["top_policies"].sort(
        key=lambda e: -((e["filtered"].get("r_per_30d") or -99)
                        - (5 if e["exit"] == "FIX" else 0)))

    with open(os.path.join(OUT_DIR, "strategy_results.json"), "w") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT_DIR, 'strategy_results.json')}")


if __name__ == "__main__":
    main()
