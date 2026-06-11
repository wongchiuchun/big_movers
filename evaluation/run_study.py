"""Run the myth-testing extraction across the whole big-movers databank.

Outputs (evaluation/output/):
  moves.csv    one row per move  — move-level holdability metrics + review label
  events.csv   one row per event — point-in-time trailing features + forward outcomes
  run_log.json skips and coverage stats

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_study
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
from evaluation.extract import detect_events, enrich, forward_metrics, move_metrics, trailing_features

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")


def normalize_label(overall: str | None) -> str | None:
    if not overall:
        return None
    o = overall.upper()
    if o.startswith("TRADABLE"):
        return "tradable"
    if o.startswith("PARTIALLY"):
        return "partial"
    if o.startswith("NOT"):
        return "not"
    return None


def load_labels() -> dict[str, str]:
    path = os.path.join(ROOT, "reviews.json")
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        reviews = json.load(fh)
    out = {}
    for key, rev in reviews.items():
        lab = normalize_label((rev.get("style_fit") or {}).get("overall"))
        if lab:
            out[key] = lab
    return out


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()

    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    labels = load_labels()

    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))
    spy["sma50"] = spy["close"].rolling(50).mean()
    spy["sma200"] = spy["close"].rolling(200).mean()

    move_rows: list[dict] = []
    event_rows: list[dict] = []
    skips: list[dict] = []
    cache: dict[str, pd.DataFrame | None] = {}

    for n, row in enumerate(results.itertuples(index=False), 1):
        symbol, year = str(row.symbol), int(row.year)
        move_key = f"{symbol}_{year}"
        if symbol not in cache:
            try:
                bars = load_ticker_bars(symbol, os.path.join(ROOT, "collected_stocks"))
                cache[symbol] = enrich(compute_all_indicators(bars, benchmark=spy))
            except Exception as exc:  # missing/corrupt CSV
                cache[symbol] = None
                skips.append({"move": move_key, "reason": f"load: {exc}"})
        ind = cache[symbol]
        if ind is None:
            if not any(s["move"] == move_key for s in skips):
                skips.append({"move": move_key, "reason": "no bars"})
            continue

        low_date = pd.Timestamp(row.low_date)
        high_date = pd.Timestamp(row.high_date)
        lo = int(ind.index.searchsorted(low_date))
        hi = int(ind.index.searchsorted(high_date, side="right")) - 1
        if lo >= len(ind) or hi <= lo:
            skips.append({"move": move_key, "reason": "move window not in bars"})
            continue

        mm = move_metrics(ind, lo, hi)
        mm.update({
            "move_key": move_key, "symbol": symbol, "year": year,
            "gain_pct": float(row.gain_pct),
            "low_date": str(ind.index[lo].date()), "high_date": str(ind.index[hi].date()),
            "label": labels.get(move_key),
            "history_bars_before_move": lo,
        })
        move_rows.append(mm)

        events = detect_events(ind, lo, hi)
        span = max(hi - lo, 1)
        ordinals: dict[str, int] = {}
        first_close = float(ind["close"].iloc[lo])
        for i, etype in events:
            ordinals[etype] = ordinals.get(etype, 0) + 1
            ev = {
                "move_key": move_key, "symbol": symbol, "year": year,
                "event_type": etype, "event_ordinal": ordinals[etype],
                "date": str(ind.index[i].date()),
                "pct_through_move": round((i - lo) / span * 100, 1),
                "gain_from_move_start": round(float(ind["close"].iloc[i]) / first_close * 100 - 100, 1),
                "history_bars": i,
                "label": labels.get(move_key),
                "move_gain_pct": float(row.gain_pct),
            }
            ev.update(trailing_features(ind, i, spy))
            ev.update(forward_metrics(ind, i))
            event_rows.append(ev)

        if n % 200 == 0:
            print(f"  {n}/{len(results)} moves … {time.time() - t0:.0f}s", flush=True)

    moves_df = pd.DataFrame(move_rows)
    events_df = pd.DataFrame(event_rows)
    moves_df.to_csv(os.path.join(OUT_DIR, "moves.csv"), index=False)
    events_df.to_csv(os.path.join(OUT_DIR, "events.csv"), index=False)
    log = {
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "moves_total": int(len(results)),
        "moves_processed": int(len(moves_df)),
        "events": int(len(events_df)),
        "events_by_type": events_df["event_type"].value_counts().to_dict() if len(events_df) else {},
        "labeled_moves": int(moves_df["label"].notna().sum()) if len(moves_df) else 0,
        "skips": skips,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    with open(os.path.join(OUT_DIR, "run_log.json"), "w") as fh:
        json.dump(log, fh, indent=2)
    print(json.dumps({k: v for k, v in log.items() if k != "skips"}, indent=2))
    print(f"skips: {len(skips)}")


if __name__ == "__main__":
    main()
