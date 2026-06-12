"""How much does the entry signal decay AFTER the first base — and is it different
in the 2023+ regime of long, multi-base 10-baggers?

The "enter early / not extended" edge was measured across the whole 2000-2026
databank, where most moves are single-leg. The user's point: 2023->now produced
names that ran 1-2 years with several bases, and the 2nd/3rd base breakouts were
very tradeable. An early-only rule sits those out.

This script:
  1. Detects BASES deterministically: a breakout to a new 20-day closing high
     AFTER a pause of >= GAP bars with no new high (i.e. it broke out of a
     consolidation). Bases are numbered 1, 2, 3, ... in sequence within a move.
  2. Measures forward R per base number (Mode A runner: 50-MA trail, structural
     stop, 3-bar hold) on held-out winner tickers and on the control group.
  3. Splits everything pre-2023 vs 2023+.
  4. Reports the pause/consolidation length and ADR by base number (do later
     bases consolidate shorter / drift out of the ADR 4-8 band?).
  5. Per-move (2023+): share of captured R in base 1 vs later bases.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_bases
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
from evaluation.engine import make_arrays, run_trade, signal_bars
from evaluation.split import split_symbol

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "output")

GAP = 8                  # bars with no new 20d high before a breakout counts as a base
NEWHIGH_LB = 20
MIN_DOLVOL_M = 5.0       # liquidity floor only — ADR band reported, not enforced, so we can
ADR_LO, ADR_HI = 4.0, 8.0  # see whether later bases drift out of it
# Mode A runner: capture the bulk of a long move
TRAIL, HOLD, STOP, FREE_ROLL = "sma50", 3, "SW", False


def detect_bases(close: np.ndarray, a: int, b: int) -> list[tuple[int, int]]:
    """Return [(bar_index, pause_len)] of base breakouts within [a, b]."""
    n = len(close)
    prior_high = pd.Series(close).rolling(NEWHIGH_LB).max().shift(1).to_numpy()
    legs = []
    last_nh = -10 ** 9
    for i in range(max(a, NEWHIGH_LB), min(b, n - 1) + 1):
        if np.isfinite(prior_high[i]) and close[i] > prior_high[i]:
            if i - last_nh >= GAP:
                legs.append((i, min(i - last_nh, 250) if last_nh > -10 ** 8 else -1))
            last_nh = i
    return legs


def stats(rs):
    if not rs:
        return {"n": 0}
    arr = np.array(rs, float)
    cap = np.quantile(arr, 0.99) if len(arr) > 5 else arr.max()
    return {"n": len(arr), "win": round(float((arr > 0).mean() * 100), 1),
            "avgR": round(float(arr.mean()), 2),
            "avgRw99": round(float(np.minimum(arr, cap).mean()), 2)}


def ord_bucket(o: int) -> str:
    return {1: "base 1", 2: "base 2", 3: "base 3"}.get(o, "base 4+")


def main():
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))
    windows = {}
    for r in results.itertuples(index=False):
        windows.setdefault(str(r.symbol), []).append(
            (pd.Timestamp(r.low_date), pd.Timestamp(r.high_date)))

    tickers = sorted({f[:-4] for f in os.listdir(os.path.join(ROOT, "collected_stocks"))
                      if f.endswith(".csv")})

    # rows: dicts with era, bucket, win/ctrl, r, pause, adr, ext, move_key, year, ord
    rows = []
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
        idx = ind.index
        wins = windows.get(sym, [])
        fold = split_symbol(sym)
        processed += 1

        # bases within each winning window (numbered per move); and bases in the
        # "wild" (outside any window) as control, numbered per uptrend run via the
        # same detector over the whole series.
        spans = [("win", lo, hi) for lo, hi in
                 [(int(idx.searchsorted(lo)), int(idx.searchsorted(hi, side="right")) - 1)
                  for lo, hi in wins]]
        for kind, a, b in spans:
            if b <= a:
                continue
            legs = detect_bases(arr["close"], a, b)
            for ordn, (i, pause) in enumerate(legs, start=1):
                dv = sb["dolvol_m"][i]
                if not (np.isfinite(dv) and dv >= MIN_DOLVOL_M):
                    continue
                tr = run_trade(arr, i, TRAIL, HOLD, STOP, FREE_ROLL)
                if tr is None:
                    continue
                yr = idx[i].year
                rows.append({"era": "2023+" if yr >= 2023 else "pre-2023",
                             "bucket": "winner_" + fold, "ord": ordn,
                             "ord_b": ord_bucket(ordn), "r": tr["r"], "pause": pause,
                             "adr": float(sb["adr"][i]) if np.isfinite(sb["adr"][i]) else None,
                             "ext": float(sb["ext"][i]) if np.isfinite(sb["ext"][i]) else None,
                             "move": f"{sym}_{yr}", "year": yr})

        # control: bases outside all windows (whole-series detection, numbered per
        # local uptrend run reset on a >40-bar gap with no new high)
        legs = detect_bases(arr["close"], NEWHIGH_LB, len(arr["close"]) - 1)
        run_ord, last_i = 0, -10 ** 9
        for (i, pause) in legs:
            ts = idx[i]
            if any(lo <= ts <= hi for lo, hi in wins):
                continue
            run_ord = 1 if (pause < 0 or i - last_i > 40 or pause > 40) else run_ord + 1
            last_i = i
            dv = sb["dolvol_m"][i]
            if not (np.isfinite(dv) and dv >= MIN_DOLVOL_M):
                continue
            tr = run_trade(arr, i, TRAIL, HOLD, STOP, FREE_ROLL)
            if tr is None:
                continue
            yr = ts.year
            rows.append({"era": "2023+" if yr >= 2023 else "pre-2023",
                         "bucket": "control", "ord": run_ord, "ord_b": ord_bucket(run_ord),
                         "r": tr["r"], "pause": pause,
                         "adr": float(sb["adr"][i]) if np.isfinite(sb["adr"][i]) else None,
                         "ext": float(sb["ext"][i]) if np.isfinite(sb["ext"][i]) else None,
                         "move": None, "year": yr})

    df = pd.DataFrame(rows)
    print(f"processed {processed} tickers; {len(df)} base-breakout entries\n")

    report = {"by_era_base": {}, "consolidation": {}, "per_move_2023": {}}

    # --- table: forward R by era x base number, winners (held-out) vs control ---
    print("=== FORWARD R BY BASE NUMBER (Mode A runner: 50-MA trail, structural stop) ===")
    for era in ("pre-2023", "2023+"):
        print(f"\n  --- {era} ---")
        print(f"  {'base':8} | {'WIN n':>6} {'win%':>5} {'avgR':>6} {'w99':>6} | {'CTRL n':>7} {'win%':>5} {'avgR':>6} {'w99':>6} | {'pause(md)':>9} {'ADR(md)':>7}")
        for ob in ("base 1", "base 2", "base 3", "base 4+"):
            sub = df[(df.era == era) & (df.ord_b == ob)]
            w = stats(sub[sub.bucket == "winner_test"]["r"].tolist())
            c = stats(sub[sub.bucket == "control"]["r"].tolist())
            wp = sub[sub.bucket.isin(["winner_train", "winner_test"])]
            pause_md = wp[wp.pause > 0]["pause"].median()
            adr_md = wp["adr"].median()
            report["by_era_base"].setdefault(era, {})[ob] = {
                "winner_test": w, "control": c,
                "pause_median": None if pd.isna(pause_md) else round(float(pause_md), 0),
                "adr_median": None if pd.isna(adr_md) else round(float(adr_md), 1),
                "winner_all_n": int(len(wp))}
            print(f"  {ob:8} | {w.get('n',0):>6} {w.get('win','-'):>5} {w.get('avgR','-'):>6} {w.get('avgRw99','-'):>6} | "
                  f"{c.get('n',0):>7} {c.get('win','-'):>5} {c.get('avgR','-'):>6} {c.get('avgRw99','-'):>6} | "
                  f"{str(report['by_era_base'][era][ob]['pause_median']):>9} {str(report['by_era_base'][era][ob]['adr_median']):>7}")

    # --- per-move capture share in 2023+: base 1 vs later bases (winners) ---
    w23 = df[(df.era == "2023+") & (df.bucket.isin(["winner_train", "winner_test"]))]
    pm = {}
    for mk, g in w23.groupby("move"):
        b1 = g[g.ord == 1]["r"].sum()
        later = g[g.ord >= 2]["r"].sum()
        pm[mk] = (b1, later, int((g.ord >= 2).sum()))
    if pm:
        b1s = np.array([v[0] for v in pm.values()])
        lts = np.array([v[1] for v in pm.values()])
        moves_with_later = sum(1 for v in pm.values() if v[2] > 0)
        report["per_move_2023"] = {
            "moves": len(pm),
            "moves_with_a_later_base": moves_with_later,
            "pct_with_later_base": round(moves_with_later / len(pm) * 100, 1),
            "avg_base1_R": round(float(b1s.mean()), 2),
            "avg_later_base_R": round(float(lts.mean()), 2),
            "later_share_of_total": round(float(lts.sum() / max(b1s.sum() + lts.sum(), 1e-9) * 100), 1)}
        print("\n=== PER-MOVE CAPTURE, 2023+ winners (Mode A runner) ===")
        for k, v in report["per_move_2023"].items():
            print(f"  {k}: {v}")

    with open(os.path.join(OUT, "bases_results.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT, 'bases_results.json')}")


if __name__ == "__main__":
    main()
