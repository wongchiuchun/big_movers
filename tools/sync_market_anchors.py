#!/usr/bin/env python3
"""Audit and explicitly synchronize the market-anchor history files."""

from __future__ import annotations

import argparse
import math
import pathlib
import sys


PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market_anchor_sync import synchronize


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _minimum_interval(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed < 9:
        raise argparse.ArgumentTypeError("must be at least 9 seconds")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit or synchronize Twelve Data market-anchor history."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="audit local coverage without network calls or writes",
    )
    parser.add_argument(
        "--symbol",
        "--symbols",
        dest="symbol_groups",
        action="append",
        nargs="+",
        metavar="SYMBOL",
        help="limit work to listed symbols; may be repeated",
    )
    parser.add_argument(
        "--max-requests",
        type=_positive_integer,
        default=50,
        help="maximum external attempts, including retries (default: 50)",
    )
    parser.add_argument(
        "--min-interval",
        type=_minimum_interval,
        default=9.0,
        help="minimum seconds between attempts (default: 9)",
    )
    parser.add_argument("--start", help="override the manifest start date")
    parser.add_argument("--end", help="override the manifest end date")
    parser.add_argument(
        "--state",
        "--state-path",
        dest="state_path",
        type=pathlib.Path,
        default=PROJECT_ROOT / ".market_anchor_sync_state.json",
        help="override the resumable state path",
    )
    parser.add_argument(
        "--manifest-path",
        type=pathlib.Path,
        default=PROJECT_ROOT / "market_anchor_universe.json",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--stocks-dir",
        type=pathlib.Path,
        default=PROJECT_ROOT / "collected_stocks",
        help=argparse.SUPPRESS,
    )
    return parser


def _flatten_symbol_groups(groups):
    if groups is None:
        return None
    return [symbol for group in groups for symbol in group]


def _print_result(result: dict[str, object]) -> None:
    labels = {
        "skipped": "COMPLETE",
        "updated": "UPDATED",
        "failed": "FAILED",
        "remaining": "REMAINING",
    }
    for detail in result["details"]:
        date_range = detail["range"]
        line = (
            f"{labels[detail['status']]:>9}  {detail['symbol']:<6} "
            f"{date_range['start']} to {date_range['end']}"
        )
        if detail.get("coverage") not in {None, "complete"}:
            line += f" ({detail['coverage']})"
        if detail.get("error"):
            line += f": {detail['error']}"
        print(line)
    print(
        "Summary: "
        f"complete={result['complete']} "
        f"skipped={result['skipped']} "
        f"updated={result['updated']} "
        f"failed={result['failed']} "
        f"remaining={result['remaining']} "
        f"requests={result['requests']}"
    )


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = synchronize(
            args.manifest_path,
            args.stocks_dir,
            args.state_path,
            dry_run=args.dry_run,
            symbols=_flatten_symbol_groups(args.symbol_groups),
            max_requests=args.max_requests,
            min_interval=args.min_interval,
            start=args.start,
            end=args.end,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    _print_result(result)
    if result["fatal"] is not None:
        print(f"Fatal: {result['error']}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
