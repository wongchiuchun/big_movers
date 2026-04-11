#!/usr/bin/env python3
"""
Scan collected_stocks/ and normalize any MM/DD/YYYY dates to ISO YYYY-MM-DD.

Some CSVs have mixed date formats (legacy rows in MM/DD/YYYY, newer rows
appended via Twelve Data in ISO) which breaks chart rendering because
Lightweight Charts requires consistent ISO dates.

Rewrites files in place with a .bak backup. Also re-sorts bars by date.

Usage:
    python3 normalize_dates.py --dry-run
    python3 normalize_dates.py --apply
"""

import argparse
import csv
import os
import shutil
import sys
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STOCKS_DIR = os.path.join(SCRIPT_DIR, "collected_stocks")


def normalize_date(raw):
    """Return ISO YYYY-MM-DD or None if unrecognized."""
    s = str(raw or "").strip()[:10]
    if not s:
        return None
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if len(s) == 10 and s[2] == "/" and s[5] == "/":
        mm, dd, yyyy = s[0:2], s[3:5], s[6:10]
        if mm.isdigit() and dd.isdigit() and yyyy.isdigit():
            return f"{yyyy}-{mm}-{dd}"
    return None


def scan_file(path):
    """
    Returns (needs_fix, rows, header, date_col_idx) where rows are the raw
    data rows (unchanged) and date_col_idx is which column holds the date.
    """
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        rows = list(reader)

    if not header:
        return False, rows, header, None

    # Determine date column: new format [idx, DateTime, O, H, L, C, V]
    # or noindex [DateTime, O, H, L, C, V]
    if len(header) >= 2 and "date" in (header[1] or "").lower():
        date_col = 1
    elif len(header) >= 1 and "date" in (header[0] or "").lower():
        date_col = 0
    else:
        return False, rows, header, None

    has_slash = False
    for row in rows:
        if len(row) > date_col:
            d = row[date_col].strip()
            if len(d) >= 10 and d[2] == "/":
                has_slash = True
                break

    return has_slash, rows, header, date_col


def rewrite_file(path, rows, header, date_col):
    """Normalize all dates in `date_col` to ISO, sort by date, rewrite file."""
    fixed = 0
    normalized_rows = []
    for row in rows:
        if len(row) > date_col:
            iso = normalize_date(row[date_col])
            if iso and iso != row[date_col].strip()[:10]:
                fixed += 1
            if iso:
                new_row = list(row)
                new_row[date_col] = iso
                normalized_rows.append(new_row)
                continue
        normalized_rows.append(row)

    normalized_rows.sort(
        key=lambda r: r[date_col] if len(r) > date_col else ""
    )

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(normalized_rows)
    return fixed


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not os.path.isdir(STOCKS_DIR):
        print(f"ERROR: {STOCKS_DIR} not found", file=sys.stderr)
        return 1

    affected = []
    for fname in sorted(os.listdir(STOCKS_DIR)):
        if not fname.endswith(".csv"):
            continue
        path = os.path.join(STOCKS_DIR, fname)
        try:
            needs_fix, rows, header, date_col = scan_file(path)
        except Exception as e:
            print(f"  SKIP {fname}: {e}", file=sys.stderr)
            continue
        if needs_fix:
            affected.append((fname, path, rows, header, date_col))

    if not affected:
        print("No files need normalization.")
        return 0

    print(f"Files with MM/DD/YYYY dates: {len(affected)}")
    for fname, *_ in affected:
        print(f"  {fname}")

    if args.dry_run:
        print("\n(dry run — no files changed)")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    total_fixed = 0
    for fname, path, rows, header, date_col in affected:
        backup = path + "." + stamp + ".bak"
        shutil.copy2(path, backup)
        fixed = rewrite_file(path, rows, header, date_col)
        total_fixed += fixed
        print(f"  {fname}: normalized {fixed} date(s), backup {os.path.basename(backup)}")

    print(f"\nDone. {total_fixed} date(s) normalized across {len(affected)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
