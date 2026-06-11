"""Deterministic train/test split — the single source of truth for every
out-of-sample evaluation in this folder.

Why this exists
---------------
The original strategy_opt.py selected the headline policy (LOD/E50) and its
filters by scanning the *entire* winners databank, then reported odd/even-year
splits AFTER selection. That is in-sample: the splits were contaminated by the
choice they were meant to validate. Combined with winners-only survivorship,
every published number was an optimistic ceiling.

The fix: choose a split ONCE, develop everything on TRAIN, and touch TEST only
to report final degradation. Two independent splits are provided because they
answer different questions:

  split_symbol(symbol)  -> "train" | "test"
      50/50 by SYMBOL (crc32-hashed). A ticker is wholly in one side, so a
      stock's idiosyncratic trend behaviour cannot leak across the boundary.
      This answers: "does the rule generalise to tickers I have never seen?"
      -- the overfitting question. This is the PRIMARY split.

  split_time(year)      -> "train" | "test"
      Chronological: years <= TIME_CUTOFF are train, later years are test.
      This answers the harder question: "does a rule fit on the past survive
      forward in time, through regimes I could not have seen?" It confounds
      rule-fit with regime, so it is the SECONDARY, stricter check.

Both are pure functions of a stable hash / a fixed year, so they reproduce
exactly across runs and machines (Python's built-in hash() is salted per
process and must NOT be used here).

Usage:
  from evaluation.split import split_symbol, split_time, tag_frame
  df = tag_frame(df)            # adds 'fold' and 'tfold' columns
  train = df[df.fold == "train"]
"""
from __future__ import annotations

import zlib

import pandas as pd

# crc32 is stable across processes/machines (unlike hash()). 50/50 by symbol.
SPLIT_SALT = "bigmover-v1"          # change to re-draw the split (don't, casually)
TIME_CUTOFF = 2019                  # train <= 2019, test >= 2020 (~37% of moves in test)


def split_symbol(symbol: str) -> str:
    """Deterministic 50/50 assignment of a ticker to train or test."""
    h = zlib.crc32(f"{SPLIT_SALT}:{symbol}".encode())
    return "train" if (h & 1) == 0 else "test"


def split_time(year: int) -> str:
    """Chronological holdout: <= TIME_CUTOFF train, later test."""
    return "train" if int(year) <= TIME_CUTOFF else "test"


def tag_frame(df: pd.DataFrame, symbol_col: str = "symbol",
              year_col: str = "year") -> pd.DataFrame:
    """Return a copy with 'fold' (symbol split) and 'tfold' (time split)."""
    out = df.copy()
    out["fold"] = out[symbol_col].astype(str).map(split_symbol)
    out["tfold"] = out[year_col].astype(int).map(split_time)
    return out


def describe_split(df: pd.DataFrame, symbol_col: str = "symbol",
                   year_col: str = "year") -> None:
    """Print the split balance so the protocol is auditable."""
    tagged = tag_frame(df, symbol_col, year_col)
    syms = tagged.drop_duplicates(symbol_col)
    print("SYMBOL split (primary, 50/50 by ticker):")
    print(f"  train: {(syms.fold == 'train').sum():4d} symbols, "
          f"{(tagged.fold == 'train').sum():7,d} rows")
    print(f"  test : {(syms.fold == 'test').sum():4d} symbols, "
          f"{(tagged.fold == 'test').sum():7,d} rows")
    print(f"TIME split (secondary, <= {TIME_CUTOFF} train):")
    print(f"  train: {(tagged.tfold == 'train').sum():7,d} rows")
    print(f"  test : {(tagged.tfold == 'test').sum():7,d} rows")


if __name__ == "__main__":
    import os

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res = pd.read_csv(os.path.join(root, "big_movers_result.csv"))
    describe_split(res)
