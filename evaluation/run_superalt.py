"""Benchmark: Adaptive SuperTrend (superalt) vs our strategy, same databank.

Produces superalt_trades.csv with two trade kinds:
  sa_system        — SuperAlt's own entries (bullish flips inside move windows),
                     its own stop (the ST line) and exit (bearish flip)
  ours_sa_exit     — OUR entry events (same dedupe as run_trade_sim) with the
                     LOD stop, but exited by SuperAlt's bearish flip
                     (direct exit-vs-exit duel against LOD/E50)

Each row carries the same feature set used by the strategy filters so the
comparison can be made unfiltered AND with the freshness filters applied.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_superalt
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classifier.indicators import compute_all_indicators, load_spy_benchmark, load_ticker_bars
from evaluation.extract import detect_events, enrich
from evaluation.run_trade_sim import EVENT_PRIORITY
from evaluation.superalt import compute_superalt, simulate_superalt_trade, superalt_exit_after, HORIZON
from evaluation.trade_sim import make_arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")


def features_at(ind, arr, i, lo, spy_up_by_date):
    entry = arr["close"][i]
    first_close = arr["close"][lo]
    date = ind.index[i]
    return {
        "adr_pct_20": float(ind["adr_pct_20"].iloc[i]) if np.isfinite(ind["adr_pct_20"].iloc[i]) else None,
        "dollar_vol_20m": float(ind["dollar_vol_20"].iloc[i] / 1e6) if np.isfinite(ind["dollar_vol_20"].iloc[i]) else None,
        "event_rel_vol20": float(ind["rel_vol_20"].iloc[i]) if np.isfinite(ind["rel_vol_20"].iloc[i]) else None,
        "gain_from_move_start": round(float(entry / first_close * 100 - 100), 1),
        "spy_above_50sma": spy_up_by_date.get(date, None),
    }


def main() -> None:
    t0 = time.time()
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))
    spy["sma50"] = spy["close"].rolling(50).mean()
    spy_up_by_date = dict(zip(spy.index, (spy["close"] > spy["sma50"]).where(spy["sma50"].notna(), None)))

    rows: list[dict] = []
    cache: dict[str, object] = {}

    for n, row in enumerate(results.itertuples(index=False), 1):
        symbol, year = str(row.symbol), int(row.year)
        move_key = f"{symbol}_{year}"
        if symbol not in cache:
            try:
                bars = load_ticker_bars(symbol, os.path.join(ROOT, "collected_stocks"))
                ind_ = enrich(compute_all_indicators(bars, benchmark=spy))
                arr_ = make_arrays(ind_)
                cache[symbol] = (ind_, arr_, compute_superalt(arr_))
            except Exception:
                cache[symbol] = None
        if cache[symbol] is None:
            continue
        ind, arr, sa = cache[symbol]

        lo = int(ind.index.searchsorted(pd.Timestamp(row.low_date)))
        hi = int(ind.index.searchsorted(pd.Timestamp(row.high_date), side="right")) - 1
        if lo >= len(ind) or hi <= lo:
            continue
        span = max(hi - lo, 1)

        # --- kind 1: SuperAlt's own system ---
        flips = [i for i in np.flatnonzero(sa["bull_flip"]) if lo <= i <= hi]
        for ordinal, i in enumerate(flips, 1):
            t = simulate_superalt_trade(sa, arr, i)
            if t is None:
                continue
            rows.append({
                "kind": "sa_system", "move_key": move_key, "symbol": symbol, "year": year,
                "date": str(ind.index[i].date()), "entry_ordinal": ordinal,
                "pct_through_move": round((i - lo) / span * 100, 1),
            } | features_at(ind, arr, i, lo, spy_up_by_date) | t)

        # --- kind 2: our entries, SuperAlt exit (LOD stop) ---
        events = [(i, et) for i, et in detect_events(ind, lo, hi) if et != "move_start"]
        by_day: dict[int, str] = {}
        for i, et in events:
            if i not in by_day or EVENT_PRIORITY[et] < EVENT_PRIORITY[by_day[i]]:
                by_day[i] = et
        ordinal = 0
        for i in sorted(by_day):
            ordinal += 1
            entry = float(arr["close"][i])
            s0 = float(arr["low"][i])
            if s0 >= entry:
                continue
            end = min(i + HORIZON, len(arr["close"]) - 1)
            if end - i < 5:
                continue
            r0 = max(entry - s0, entry * 0.001)
            ex_bar, ex_px, reason = superalt_exit_after(sa, arr, i)
            lows = arr["low"][i + 1: end + 1]
            hit = np.flatnonzero(lows < s0)
            if len(hit) and (i + 1 + int(hit[0])) < ex_bar:
                j = i + 1 + int(hit[0])
                ex_bar, ex_px, reason = j, min(float(arr["open"][j]), s0), "stop"
            rows.append({
                "kind": "ours_sa_exit", "move_key": move_key, "symbol": symbol, "year": year,
                "date": str(ind.index[i].date()), "entry_ordinal": ordinal,
                "pct_through_move": round((i - lo) / span * 100, 1),
            } | features_at(ind, arr, i, lo, spy_up_by_date) | {
                "entry": round(entry, 4), "s0": round(s0, 4),
                "risk_pct": round(r0 / entry * 100, 2),
                "r": round((ex_px - entry) / r0, 3),
                "days": int(ex_bar - i), "reason": reason,
            })

        if n % 300 == 0:
            print(f"  {n}/{len(results)} moves … {len(rows)} trades … {time.time()-t0:.0f}s", flush=True)

    df = pd.DataFrame(rows)
    df.to_csv(os.path.join(OUT_DIR, "superalt_trades.csv"), index=False)
    log = {"generated": time.strftime("%Y-%m-%d %H:%M"), "rows": int(len(df)),
           "by_kind": df["kind"].value_counts().to_dict(), "elapsed_sec": round(time.time() - t0, 1)}
    with open(os.path.join(OUT_DIR, "superalt_run_log.json"), "w") as fh:
        json.dump(log, fh, indent=2)
    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
