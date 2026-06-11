"""Run the stop x exit policy grid over every deduped entry event.

Output: evaluation/output/trades.csv — one row per (event, stop, exit) with the
realized R-multiple, days held and exit reason. Join to events.csv on
(move_key, date) for entry-time features.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_trade_sim
"""
from __future__ import annotations

import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classifier.indicators import compute_all_indicators, load_spy_benchmark, load_ticker_bars
from evaluation.extract import detect_events, enrich
from evaluation.trade_sim import make_arrays, simulate_event

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")

EVENT_PRIORITY = {"gap": 0, "breakout50": 1, "breakout20": 2}  # lower wins on same day


def main() -> None:
    t0 = time.time()
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))

    rows: list[dict] = []
    cache: dict[str, object] = {}
    skipped = 0

    for n, row in enumerate(results.itertuples(index=False), 1):
        symbol, year = str(row.symbol), int(row.year)
        move_key = f"{symbol}_{year}"
        if symbol not in cache:
            try:
                bars = load_ticker_bars(symbol, os.path.join(ROOT, "collected_stocks"))
                ind_ = enrich(compute_all_indicators(bars, benchmark=spy))
                cache[symbol] = (ind_, make_arrays(ind_))
            except Exception:
                cache[symbol] = None
        if cache[symbol] is None:
            skipped += 1
            continue
        ind, arr = cache[symbol]

        lo = int(ind.index.searchsorted(pd.Timestamp(row.low_date)))
        hi = int(ind.index.searchsorted(pd.Timestamp(row.high_date), side="right")) - 1
        if lo >= len(ind) or hi <= lo:
            skipped += 1
            continue

        events = [(i, et) for i, et in detect_events(ind, lo, hi) if et != "move_start"]
        # dedupe same-day events: gap > breakout50 > breakout20
        by_day: dict[int, str] = {}
        for i, et in events:
            if i not in by_day or EVENT_PRIORITY[et] < EVENT_PRIORITY[by_day[i]]:
                by_day[i] = et

        span = max(hi - lo, 1)
        ordinal = 0
        for i in sorted(by_day):
            ordinal += 1
            et = by_day[i]
            base = {
                "move_key": move_key, "symbol": symbol, "year": year,
                "date": str(ind.index[i].date()), "event_type": et,
                "entry_ordinal": ordinal,
                "pct_through_move": round((i - lo) / span * 100, 1),
            }
            for trade in simulate_event(arr, i):
                rows.append(base | trade)

        if n % 200 == 0:
            print(f"  {n}/{len(results)} moves … {len(rows)} trades … {time.time()-t0:.0f}s", flush=True)

    trades = pd.DataFrame(rows)
    trades.to_csv(os.path.join(OUT_DIR, "trades.csv"), index=False)
    log = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "trades": int(len(trades)),
        "unique_entries": int(trades.groupby(["move_key", "date"]).ngroups) if len(trades) else 0,
        "skipped_moves": skipped,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(OUT_DIR, "trade_sim_log.json"), "w") as fh:
        json.dump(log, fh, indent=2)
    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
