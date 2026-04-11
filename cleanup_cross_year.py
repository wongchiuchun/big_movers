#!/usr/bin/env python3
"""
Scan big_movers_result.csv for rows whose low_date or high_date falls outside
the row's `year` column, and rewrite them so each year has its own independent
move calculation.

Rules:
- Returns are calculated strictly within a single calendar year.
- Low must occur on or before the high (left-to-right in time).
- For a year's bars, pick the (low_idx, high_idx) pair with low_idx <= high_idx
  that maximizes gain_pct. If no positive gain exists, skip that year.
- When an existing row spans multiple years, the primary-year row is rewritten
  in place and new rows are appended for every other year covered by the
  original [low_date, high_date] window.

Usage:
    python3 cleanup_cross_year.py --dry-run
    python3 cleanup_cross_year.py --apply
"""

import argparse
import csv
import os
import shutil
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(SCRIPT_DIR, "big_movers_result.csv")
STOCKS_DIR = os.path.join(SCRIPT_DIR, "collected_stocks")


def load_bars(symbol):
    """Load OHLCV bars for a symbol. Returns list of {time, close, volume}."""
    path = os.path.join(STOCKS_DIR, f"{symbol}.csv")
    if not os.path.exists(path):
        path = os.path.join(STOCKS_DIR, f"{symbol.lower()}.csv")
    if not os.path.exists(path):
        return None

    bars = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        has_index = bool(header) and len(header) >= 7
        for row in reader:
            if not row:
                continue
            try:
                if has_index and len(row) >= 7:
                    d = row[1].strip()[:10]
                    close = float(row[5])
                    vol = float(row[6]) if row[6] else 0.0
                elif len(row) >= 6:
                    d = row[0].strip()[:10]
                    close = float(row[4])
                    vol = float(row[5]) if row[5] else 0.0
                else:
                    continue
                if d:
                    bars.append({"time": d, "close": close, "volume": vol})
            except (ValueError, IndexError):
                continue
    bars.sort(key=lambda b: b["time"])
    return bars


def best_move_within_year(bars, year):
    """
    Given full bar list, filter to `year`, and find the (low, high) pair with
    low_idx <= high_idx that maximizes gain. Returns dict or None.
    """
    year_bars = [b for b in bars if b["time"][:4] == str(year)]
    if not year_bars:
        return None

    running_min = year_bars[0]["close"]
    running_min_idx = 0
    best = None  # (gain_pct, low_idx, high_idx)

    for i, bar in enumerate(year_bars):
        c = bar["close"]
        if c < running_min:
            running_min = c
            running_min_idx = i
        if running_min > 0:
            gain = (c / running_min - 1) * 100
            if best is None or gain > best[0]:
                best = (gain, running_min_idx, i)

    if best is None or best[0] <= 0:
        return None

    gain_pct, low_idx, high_idx = best
    low_bar = year_bars[low_idx]
    high_bar = year_bars[high_idx]
    avg_vol = sum(b["volume"] for b in year_bars) / len(year_bars)

    return {
        "year": str(year),
        "gain_pct": round(gain_pct, 2),
        "low_date": low_bar["time"],
        "high_date": high_bar["time"],
        "low_price": round(low_bar["close"], 3),
        "high_price": round(high_bar["close"], 3),
        "avg_vol_b": round(avg_vol / 1e9, 2),
    }


def row_is_cross_year(row):
    y = str(row.get("year", "")).strip()
    low_y = str(row.get("low_date", ""))[:4]
    high_y = str(row.get("high_date", ""))[:4]
    return bool(y) and (low_y != y or high_y != y)


def years_covered(row):
    """All calendar years that fall inside [low_date, high_date]."""
    try:
        lo = datetime.strptime(str(row["low_date"])[:10], "%Y-%m-%d")
        hi = datetime.strptime(str(row["high_date"])[:10], "%Y-%m-%d")
    except ValueError:
        return []
    if hi < lo:
        lo, hi = hi, lo
    return list(range(lo.year, hi.year + 1))


def format_row(row, fieldnames):
    """Coerce numeric fields back to strings matching existing CSV style."""
    out = {}
    for k in fieldnames:
        v = row.get(k, "")
        out[k] = "" if v is None else str(v)
    return out


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Preview changes only")
    mode.add_argument("--apply", action="store_true", help="Write changes to CSV")
    args = ap.parse_args()

    if not os.path.exists(RESULTS_CSV):
        print(f"ERROR: {RESULTS_CSV} not found", file=sys.stderr)
        return 1

    with open(RESULTS_CSV, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    cross = [(i, r) for i, r in enumerate(rows) if row_is_cross_year(r)]
    if not cross:
        print("No cross-year rows found. Nothing to do.")
        return 0

    print(f"Found {len(cross)} cross-year row(s):")
    for _, r in cross:
        print(f"  {r['year']} {r['symbol']}: {r['low_date']} -> {r['high_date']} "
              f"({r['gain_pct']}%)")
    print()

    existing_keys = {(r["symbol"], str(r["year"])) for r in rows}
    new_rows = list(rows)
    replacements = {}  # idx -> new row (primary-year rewrite)
    additions = []     # new rows for bleed years

    for idx, r in cross:
        symbol = r["symbol"]
        bars = load_bars(symbol)
        if bars is None:
            print(f"  SKIP {symbol}: no OHLCV file", file=sys.stderr)
            continue

        years = years_covered(r)
        primary_year = str(r["year"])
        if primary_year not in [str(y) for y in years]:
            years.append(int(primary_year))

        for y in years:
            stats = best_move_within_year(bars, y)
            if stats is None:
                print(f"  SKIP {symbol} {y}: no positive move in {y} bars")
                continue

            new_row = dict(r)
            new_row.update(stats)

            if str(y) == primary_year:
                replacements[idx] = new_row
                before = (f"{r['low_date']}->{r['high_date']} "
                          f"{r['low_price']}->{r['high_price']} "
                          f"{r['gain_pct']}%")
                after = (f"{stats['low_date']}->{stats['high_date']} "
                         f"{stats['low_price']}->{stats['high_price']} "
                         f"{stats['gain_pct']}%")
                print(f"  REWRITE {symbol} {y}: {before}")
                print(f"                  ->  {after}")
            else:
                key = (symbol, str(y))
                if key in existing_keys:
                    print(f"  SKIP {symbol} {y}: already exists in results")
                    continue
                additions.append(new_row)
                existing_keys.add(key)
                print(f"  ADD     {symbol} {y}: "
                      f"{stats['low_date']}->{stats['high_date']} "
                      f"{stats['low_price']}->{stats['high_price']} "
                      f"{stats['gain_pct']}%")

    if not replacements and not additions:
        print("\nNothing to write.")
        return 0

    for idx, new_row in replacements.items():
        new_rows[idx] = new_row
    new_rows.extend(additions)
    new_rows.sort(key=lambda r: (str(r.get("year", "")), r.get("symbol", "")))

    print(
        f"\nSummary: {len(replacements)} rewrite(s), {len(additions)} addition(s)."
    )

    if args.dry_run:
        print("(dry run — no files changed)")
        return 0

    backup = RESULTS_CSV + "." + datetime.now().strftime("%Y%m%d_%H%M%S") + ".bak"
    shutil.copy2(RESULTS_CSV, backup)
    print(f"Backup: {backup}")

    with open(RESULTS_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in new_rows:
            writer.writerow(format_row(r, fieldnames))
    print(f"Wrote {RESULTS_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
