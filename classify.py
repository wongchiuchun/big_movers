"""CLI for the setup classifier."""
import argparse
from pathlib import Path

from classifier.pipeline import classify_moves

REPO = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="Filter to a single year")
    ap.add_argument("--symbol", help="Filter to a single symbol")
    ap.add_argument("--output", default="ai_classifications.json")
    ap.add_argument(
        "--no-merge",
        action="store_true",
        help="Start fresh instead of merging with existing output",
    )
    args = ap.parse_args()

    symbols = [args.symbol] if args.symbol else None
    out = classify_moves(
        REPO / "big_movers_result.csv",
        REPO,
        REPO / args.output,
        year=args.year,
        symbols=symbols,
        merge_existing=not args.no_merge,
    )

    # Print a distribution summary
    from collections import Counter
    primary_counts = Counter(v.get("ai_primary") for v in out.values())
    print("\nPrimary setup distribution:")
    for setup, n in primary_counts.most_common():
        print(f"  {setup or '(none)'}: {n}")


if __name__ == "__main__":
    main()
