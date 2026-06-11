"""Do continuation (2nd / 3rd leg) entries pay, or are they just chasing?

The live indicator only takes the FIRST leg (extension <50% off the 63-day low,
<=3 triggers). Once a move is underway the filter is permanently off, so a failed
first entry locks you out of the whole run (VSH, RKLB, NOK all did this). This
script tests the alternative the user asked about: a CONTINUATION entry that is
deliberately further from the base.

Continuation entry = a pullback that reclaims the 20-EMA inside an established
uptrend (close > rising 50-MA). It is allowed at ANY extension/ordinal, so it
catches leg 2, 3, ... A flag/leg entry, not a base breakout.

We bucket EVERY entry by how extended it is off the 63-day low, and report avg R
on held-out winner tickers vs the control group (signals outside winning windows)
so the survivorship is visible. Decision input: does test-R stay positive and
control-R stay survivable as you move further from the base?

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_continuation
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
from evaluation.engine import entries_since_low, make_arrays, run_trade, signal_bars
from evaluation.split import split_symbol

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "output")

ADR_LO, ADR_HI, MIN_DOLVOL_M = 4.0, 8.0, 5.0
MIN_RELVOL = 1.5
ENTRY_COOLDOWN = 5
# Mode B (consistent) so base and continuation are judged on the same trade rules
TRAIL, HOLD, STOP, FREE_ROLL = "sma50", 3, "SW", True

EXT_BANDS = [(0, 50, "0-50% (base)"), (50, 100, "50-100%"),
             (100, 200, "100-200%"), (200, 1e9, "200%+")]


def band_of(ext: float) -> str:
    for lo, hi, name in EXT_BANDS:
        if lo <= ext < hi:
            return name
    return "neg"


def stats(rs):
    if not rs:
        return {"n": 0}
    a = np.array(rs, float)
    cap = np.quantile(a, 0.99) if len(a) > 5 else a.max()
    return {"n": len(a), "win": round(float((a > 0).mean() * 100), 1),
            "avgR": round(float(a.mean()), 2),
            "avgRw99": round(float(np.minimum(a, cap).mean()), 2),
            "medR": round(float(np.median(a)), 2)}


def main():
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))
    windows = {}
    for r in results.itertuples(index=False):
        windows.setdefault(str(r.symbol), []).append(
            (pd.Timestamp(r.low_date), pd.Timestamp(r.high_date)))

    tickers = sorted({f[:-4] for f in os.listdir(os.path.join(ROOT, "collected_stocks"))
                      if f.endswith(".csv")})

    # acc[entry_kind][band][bucket] -> list R   (entry_kind: base | cont)
    kinds = ["base", "cont"]
    buckets = ["winner_test", "control"]   # winner_train folded into test-side check below
    acc = {k: {b[2]: {bk: [] for bk in buckets + ["winner_train"]} for b in EXT_BANDS}
           for k in kinds}
    # per-move capture: move_key -> {base_R: [], cont_R: []}
    per_move = {}
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
        sma50 = arr["sma50"]
        ema20 = arr["ema20"]
        rising = np.full(len(sma50), False)
        rising[21:] = sma50[21:] > sma50[:-21]
        wins = windows.get(sym, [])
        fold = split_symbol(sym)
        processed += 1

        last_entry = -10_000
        n = len(ind)
        for t in range(60, n):
            if t - last_entry < ENTRY_COOLDOWN:
                continue
            adr, dv = sb["adr"][t], sb["dolvol_m"][t]
            if not (np.isfinite(adr) and ADR_LO <= adr <= ADR_HI and np.isfinite(dv) and dv >= MIN_DOLVOL_M):
                continue
            ext, rv = sb["ext"][t], sb["relvol20"][t]
            if not np.isfinite(ext) or ext < 0:
                continue

            # --- base entry: the live indicator's rule ---
            is_base = (sb["raw"][t] and ordn[t] <= 3 and ext < 50
                       and np.isfinite(rv) and rv >= MIN_RELVOL)
            # --- continuation entry: pullback reclaims 20EMA in an uptrend ---
            is_cont = (arr["close"][t] > sma50[t] and rising[t]
                       and arr["low"][t] <= ema20[t] * 1.01 and arr["close"][t] >= ema20[t]
                       and arr["close"][t] > arr["close"][t - 1]
                       and not is_base)
            if not (is_base or is_cont):
                continue

            kind = "base" if is_base else "cont"
            band = band_of(ext)
            if band == "neg":
                continue
            ts = idx[t]
            in_win = any(lo <= ts <= hi for lo, hi in wins)
            if in_win:
                bucket = "winner_" + fold
            else:
                bucket = "control"
            last_entry = t

            tr = run_trade(arr, t, TRAIL, HOLD, STOP, FREE_ROLL)
            if tr is None:
                continue
            acc[kind][band][bucket].append(tr["r"])
            if in_win:
                mk = f"{sym}_{ts.year}"
                pm = per_move.setdefault(mk, {"base": [], "cont": []})
                pm[kind].append(tr["r"])

    print(f"processed {processed} tickers\n")
    report = {"by_band": {}, "per_move": {}}
    print(f"{'entry':6} {'extension band':16} | "
          f"{'TEST n':>7} {'win':>5} {'avgR':>6} {'w99':>6} | {'CTRL n':>7} {'win':>5} {'avgR':>6} {'w99':>6}")
    print("-" * 92)
    for kind in kinds:
        for _, _, band in EXT_BANDS:
            te = stats(acc[kind][band]["winner_test"])
            ct = stats(acc[kind][band]["control"])
            report["by_band"].setdefault(kind, {})[band] = {"winner_test": te, "control": ct,
                "winner_train": stats(acc[kind][band]["winner_train"])}
            if te["n"] or ct["n"]:
                print(f"{kind:6} {band:16} | "
                      f"{te.get('n',0):>7} {te.get('win','-'):>5} {te.get('avgR','-'):>6} {te.get('avgRw99','-'):>6} | "
                      f"{ct.get('n',0):>7} {ct.get('win','-'):>5} {ct.get('avgR','-'):>6} {ct.get('avgRw99','-'):>6}")

    # per-move capture: how often a continuation entry fired, and the extra R
    moves_with_cont = sum(1 for m in per_move.values() if m["cont"])
    total_moves = len(per_move)
    extra = [sum(m["cont"]) for m in per_move.values() if m["cont"]]
    base_only = [sum(m["base"]) for m in per_move.values() if m["base"]]
    report["per_move"] = {
        "winning_moves_seen": total_moves,
        "moves_with_a_continuation_entry": moves_with_cont,
        "pct_moves_with_continuation": round(moves_with_cont / max(total_moves, 1) * 100, 1),
        "avg_extra_R_from_continuation_when_present": round(float(np.mean(extra)), 2) if extra else None,
        "median_extra_R": round(float(np.median(extra)), 2) if extra else None,
        "avg_base_R_per_move": round(float(np.mean(base_only)), 2) if base_only else None,
    }
    print("\n=== PER-MOVE CAPTURE (winning moves) ===")
    for k, v in report["per_move"].items():
        print(f"  {k}: {v}")

    with open(os.path.join(OUT, "continuation_results.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT, 'continuation_results.json')}")


if __name__ == "__main__":
    main()
