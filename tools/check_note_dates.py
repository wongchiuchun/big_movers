#!/usr/bin/env python3
"""Audit drawings.json note text for EP/gap claims that don't match
the underlying OHLCV bar. Catches the CLS bug class: note text said
"Aug 5 EP: +9% gap on 2.5x vol" when the real EP was Jul 29 and Aug 5
was a red day with no qualifying gap.

Rule: for each note whose text mentions EP/gap/breakout/pivot + a month+day
token, load the ticker's CSV and verify the bar on that date satisfies
gap>=5% on vol>=1.5x 20d avg (same filter as tools/analyze_move.py).
If not, flag it — the text date was likely transcribed from reviews.json
instead of tools/analyze_move.py.

Usage:
    python3 tools/check_note_dates.py              # audit all moves
    python3 tools/check_note_dates.py CLS_2025     # audit one move
"""
import csv
import json
import os
import re
import sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRAWINGS = os.path.join(BASE, "drawings.json")
STOCKS = os.path.join(BASE, "collected_stocks")

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
MONTH_ALT = "|".join(MONTHS.keys())

# Tight inline claim patterns. We only verify dates that are directly
# followed by either "EP" (Episodic Pivot label) or a quantified stat
# like "+9% gap" / "2.5x vol" — matching the CLS failure signature:
#   "Aug 5 EP: +9% gap on 2.5x vol"
# Narrative mentions of EP ("no EP catalyst", "tested LoD of the EP",
# "EP on Oct 13") are intentionally ignored to avoid false positives.
_TAIL = (
    r"(?:"
    r"\s+EP\b"                                       # " EP" label
    r"|\s*[:\-]\s*[+-]?\d+(?:\.\d+)?\s*%\s*gap\b"    # ": +9% gap"
    r"|\s*[:\-]\s*\d+(?:\.\d+)?\s*x\s*vol\b"         # ": 2.5x vol"
    r")"
)
CLAIM_MON_DAY = re.compile(
    rf"\b({MONTH_ALT})[a-z]*\s+(\d{{1,2}}){_TAIL}",
    re.IGNORECASE,
)
CLAIM_DAY_MON = re.compile(
    rf"\b(\d{{1,2}})\s+({MONTH_ALT})[a-z]*{_TAIL}",
    re.IGNORECASE,
)

GAP_PCT_MIN = 5.0
REL_VOL_MIN = 1.5
BAR_SEARCH_WINDOW = 3  # trading-day slack when picking the nearest bar


def load_bars(symbol):
    """Load OHLCV CSV as a dict keyed by 'YYYY-MM-DD' date string."""
    path = os.path.join(STOCKS, f"{symbol}.csv")
    if not os.path.isfile(path):
        return None, None
    bars = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = (row.get("DateTime") or row.get("datetime") or "").strip()
            if not d:
                # noindex format may have date in first column under a different key
                vals = list(row.values())
                if vals:
                    d = (vals[0] or "").strip()
            d = d[:10]
            if len(d) != 10 or d[4] != "-":
                continue
            try:
                bars[d] = {
                    "open": float(row.get("Open") or 0),
                    "high": float(row.get("High") or 0),
                    "low": float(row.get("Low") or 0),
                    "close": float(row.get("Close") or 0),
                    "volume": float(row.get("Volume") or 0),
                }
            except (TypeError, ValueError):
                continue
    if not bars:
        return None, None
    dates_sorted = sorted(bars.keys())
    return bars, dates_sorted


def nearest_trading_day(dates_sorted, target_iso):
    """Return the closest trading day within BAR_SEARCH_WINDOW calendar days,
    or None if no bar is close enough (likely a data gap)."""
    if target_iso in dates_sorted:
        return target_iso
    t = date.fromisoformat(target_iso)
    for delta in range(1, BAR_SEARCH_WINDOW + 1):
        for sign in (1, -1):
            cand = (t + timedelta(days=delta * sign)).isoformat()
            if cand in dates_sorted:
                return cand
    return None


def gap_and_rel_vol(bars, dates_sorted, d):
    """Return (gap_pct, rel_vol_20) for the given trading day, or None."""
    idx = dates_sorted.index(d)
    if idx == 0:
        return None
    prev_close = bars[dates_sorted[idx - 1]]["close"]
    if prev_close <= 0:
        return None
    today = bars[d]
    gap_pct = (today["open"] - prev_close) / prev_close * 100
    lookback = dates_sorted[max(0, idx - 20):idx]
    if not lookback:
        return None
    avg_vol = sum(bars[b]["volume"] for b in lookback) / len(lookback)
    rel_vol = today["volume"] / avg_vol if avg_vol > 0 else 0
    return gap_pct, rel_vol


def extract_claim_dates(text, candidate_years):
    """Extract dates from tight EP-claim patterns only (DATE+EP or
    DATE+: stats). Narrative EP mentions are ignored by design."""
    tokens = set()
    for mon, day in CLAIM_MON_DAY.findall(text):
        tokens.add((MONTHS[mon.lower()], int(day)))
    for day, mon in CLAIM_DAY_MON.findall(text):
        tokens.add((MONTHS[mon.lower()], int(day)))
    out = []
    for mm, dd in tokens:
        for yr in candidate_years:
            try:
                out.append(date(yr, mm, dd))
                break
            except ValueError:
                continue
    return out


def audit(move_filter=None):
    with open(DRAWINGS) as f:
        drawings = json.load(f)

    issues = []
    checked = 0
    cache = {}

    for key, items in drawings.items():
        if move_filter and key != move_filter:
            continue
        if "_" not in key:
            continue
        symbol, _, year_str = key.rpartition("_")
        try:
            move_year = int(year_str)
        except ValueError:
            continue

        if symbol not in cache:
            cache[symbol] = load_bars(symbol)
        bars, dates_sorted = cache[symbol]
        if not bars:
            continue

        for note in items:
            if note.get("type") != "note":
                continue
            text = (note.get("text") or "").strip()
            if not text:
                continue

            years = [move_year, move_year + 1, move_year - 1]
            text_dates = extract_claim_dates(text, years)
            if not text_dates:
                continue

            for td in text_dates:
                checked += 1
                real_day = nearest_trading_day(dates_sorted, td.isoformat())
                if real_day is None:
                    continue  # date not in data range, skip
                result = gap_and_rel_vol(bars, dates_sorted, real_day)
                if result is None:
                    continue
                gap_pct, rel_vol = result
                if gap_pct >= GAP_PCT_MIN and rel_vol >= REL_VOL_MIN:
                    continue  # claim matches a real qualifying gap
                issues.append({
                    "move": key,
                    "id": note.get("id"),
                    "text_date": td.isoformat(),
                    "bar_date": real_day,
                    "gap_pct": gap_pct,
                    "rel_vol": rel_vol,
                    "snippet": text[:100].replace("\n", " | "),
                })

    print(f"Checked {checked} EP-claim date(s) in note text.")
    if not issues:
        print("OK — every EP/gap claim matches a qualifying bar "
              f"(gap>={GAP_PCT_MIN}% on vol>={REL_VOL_MIN}x 20d).")
        return 0

    print(f"Found {len(issues)} suspicious date(s):\n")
    by_move = {}
    for iss in issues:
        by_move.setdefault(iss["move"], []).append(iss)
    for move in sorted(by_move):
        print(f"{move}:")
        for iss in by_move[move]:
            print(f"  id={iss['id']:<4} text={iss['text_date']} "
                  f"→ bar {iss['bar_date']} "
                  f"gap={iss['gap_pct']:+.1f}% vol={iss['rel_vol']:.1f}x")
            print(f"    → {iss['snippet']}")
    print()
    print("These notes claim an EP/gap/breakout on a date that has no "
          "qualifying bar. Run `tools/analyze_move.py SYMBOL YEAR` to "
          "see the real gap list, then fix the note text.")
    return 1


if __name__ == "__main__":
    sys.exit(audit(sys.argv[1] if len(sys.argv) > 1 else None))
