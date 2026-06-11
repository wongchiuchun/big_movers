"""Run the vault-informed engine across winner-train / winner-test / control.

For every collected_stocks ticker we detect point-in-time triggers, apply the
momentum universe + the two robust filters (early, not-extended) + volume, then
bucket each signal:
  * winner_train / winner_test  -- inside a recorded winning window, by symbol split
  * control                     -- every qualifying signal OUTSIDE the windows
                                   (the false-positive proxy)
Each signal is run through a fixed grid of strategy configs (entry x trail x
hold x stop x free-roll). We report avg R per (bucket, config).

The decision rule:
  - SELECT the config on winner_train.
  - It is robust only if it also holds on winner_test AND stays positive on
    control (i.e. the edge is not pure survivorship).

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_engine [N]
  (optional N = limit number of tickers, for a quick smoke test)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classifier.indicators import compute_all_indicators, load_spy_benchmark, load_ticker_bars
from evaluation.extract import enrich
from evaluation.engine import (entries_since_low, find_entry, make_arrays,
                               run_trade, signal_bars)
from evaluation.split import split_symbol

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")

ADR_LO, ADR_HI = 4.0, 8.0
MIN_DOLVOL_M = 5.0
MAX_ORDINAL = 3
MAX_EXT = 50.0
MIN_RELVOL = 1.5
ENTRY_COOLDOWN = 5

# (name, entry_style, trail_col, min_hold, stop_mode, free_roll)
CONFIGS = [
    ("BO_E10_h0_SW",    "breakout", "ema10", 0, "SW",  False),
    ("BO_E10_h3_SW",    "breakout", "ema10", 3, "SW",  False),
    ("BO_E20_h3_SW",    "breakout", "ema20", 3, "SW",  False),
    ("BO_E50_h0_SW",    "breakout", "sma50", 0, "SW",  False),
    ("BO_E50_h3_SW",    "breakout", "sma50", 3, "SW",  False),
    ("BO_E50_h0_LOD",   "breakout", "sma50", 0, "LOD", False),
    ("BO_E10_h3_SW_FR", "breakout", "ema10", 3, "SW",  True),
    ("BO_E50_h3_SW_FR", "breakout", "sma50", 3, "SW",  True),
    ("PB_E10_h3_SW",    "pullback", "ema10", 3, "SW",  False),
    ("PB_E20_h3_SW",    "pullback", "ema20", 3, "SW",  False),
    ("PB_E50_h3_SW",    "pullback", "sma50", 3, "SW",  False),
    ("BO_E50_h3_ATR",   "breakout", "sma50", 3, "ATR", False),
]


def stats(rs: list[float], days: list[int]) -> dict:
    if not rs:
        return {"n": 0}
    a = np.array(rs, float)
    cap = np.quantile(a, 0.99)
    return {"n": len(a), "win": round(float((a > 0).mean() * 100), 1),
            "avgR": round(float(a.mean()), 2),
            "avgRw99": round(float(np.minimum(a, cap).mean()), 2),
            "medR": round(float(np.median(a)), 2),
            "R30d": round(float(a.mean() / max(np.mean(days), 1) * 30), 2)}


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))

    # winning windows per symbol: list of (low_date, high_date, year)
    windows: dict[str, list] = {}
    for r in results.itertuples(index=False):
        windows.setdefault(str(r.symbol), []).append(
            (pd.Timestamp(r.low_date), pd.Timestamp(r.high_date), int(r.year)))

    tickers = sorted({f[:-4] for f in os.listdir(os.path.join(ROOT, "collected_stocks"))
                      if f.endswith(".csv")})
    if limit:
        tickers = tickers[:limit]

    # acc[bucket][config] -> {"r": [], "d": [], "yr": []}
    buckets = ["winner_train", "winner_test", "control"]
    acc = {b: {c[0]: {"r": [], "d": [], "yr": []} for c in CONFIGS} for b in buckets}
    n_sig = {b: 0 for b in buckets}
    processed = 0

    for sym in tickers:
        try:
            ind = enrich(compute_all_indicators(
                load_ticker_bars(sym, os.path.join(ROOT, "collected_stocks")), benchmark=spy))
        except Exception:
            continue
        if len(ind) < 120:
            continue
        arr = make_arrays(ind)
        sb = signal_bars(ind)
        ordn = entries_since_low(sb["raw"], arr["low"])
        idx = ind.index
        wins = windows.get(sym, [])
        fold = split_symbol(sym)
        processed += 1

        last_entry = -10_000
        raw_idx = np.flatnonzero(sb["raw"])
        for t in raw_idx:
            if t - last_entry < ENTRY_COOLDOWN:
                continue
            # universe + robust filters + volume (all point-in-time at bar t)
            adr, dv, ext, rv = sb["adr"][t], sb["dolvol_m"][t], sb["ext"][t], sb["relvol20"][t]
            if not (np.isfinite(adr) and ADR_LO <= adr <= ADR_HI and dv >= MIN_DOLVOL_M):
                continue
            if not (ordn[t] <= MAX_ORDINAL and np.isfinite(ext) and ext < MAX_EXT
                    and np.isfinite(rv) and rv >= MIN_RELVOL):
                continue
            # bucket: inside a winning window?
            ts = idx[t]
            in_win = any(lo <= ts <= hi for lo, hi, _ in wins)
            bucket = ("winner_" + fold) if in_win else "control"
            yr = ts.year
            last_entry = t
            n_sig[bucket] += 1
            for name, style, trail, hold, stop_mode, fr in CONFIGS:
                ei = find_entry(arr, int(t), style)
                if ei is None:
                    continue
                tr = run_trade(arr, ei, trail, hold, stop_mode, fr)
                if tr is not None:
                    acc[bucket][name]["r"].append(tr["r"])
                    acc[bucket][name]["d"].append(tr["days"])
                    acc[bucket][name]["yr"].append(yr)

    print(f"processed {processed} tickers | signals: "
          + "  ".join(f"{b}={n_sig[b]}" for b in buckets))

    report = {"configs": [c[0] for c in CONFIGS], "n_signals": n_sig, "table": {}}
    hdr = f"{'config':16} | " + " | ".join(f"{b:^34}" for b in buckets)
    print("\n" + hdr)
    print(f"{'':16} | " + " | ".join(f"{'n':>5} {'win':>5} {'avgR':>6} {'w99':>6} {'R30d':>6}"
                                      for _ in buckets))
    for c in CONFIGS:
        name = c[0]
        row = {}
        cells = []
        for b in buckets:
            s = stats(acc[b][name]["r"], acc[b][name]["d"])
            row[b] = s
            if s["n"]:
                cells.append(f"{s['n']:>5} {s['win']:>5} {s['avgR']:>6} {s['avgRw99']:>6} {s['R30d']:>6}")
            else:
                cells.append(f"{'-':>5} {'-':>5} {'-':>6} {'-':>6} {'-':>6}")
        report["table"][name] = row
        print(f"{name:16} | " + " | ".join(cells))

    # --- per-year consistency for the finalists, on the realistic blended
    #     stream (all winners + control together, as you'd actually trade it) ---
    FINALISTS = ["BO_E50_h3_SW", "BO_E50_h3_SW_FR", "BO_E10_h3_SW_FR", "PB_E50_h3_SW"]
    print("\n=== PER-YEAR CONSISTENCY (blended winners+control stream) ===")
    print(f"{'config':16} {'years':>6} {'negYrs':>7} {'yrStd':>6} {'medYr':>6} {'worstYr':>8}")
    cons = {}
    for name in FINALISTS:
        rs, yrs = [], []
        for b in buckets:
            rs += acc[b][name]["r"]
            yrs += acc[b][name]["yr"]
        d = pd.DataFrame({"r": rs, "yr": yrs})
        yr = d.groupby("yr").filter(lambda g: len(g) >= 10).groupby("yr")["r"].mean()
        c = {"years": int(len(yr)), "neg_years": int((yr <= 0).sum()),
             "yr_std": round(float(yr.std()), 2) if len(yr) > 1 else None,
             "median_year": round(float(yr.median()), 2) if len(yr) else None,
             "worst_year": round(float(yr.min()), 2) if len(yr) else None}
        cons[name] = c
        print(f"{name:16} {c['years']:>6} {c['neg_years']:>7} {str(c['yr_std']):>6} "
              f"{str(c['median_year']):>6} {str(c['worst_year']):>8}")
    report["consistency_finalists"] = cons

    with open(os.path.join(OUT_DIR, "engine_results.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT_DIR, 'engine_results.json')}")


if __name__ == "__main__":
    main()
