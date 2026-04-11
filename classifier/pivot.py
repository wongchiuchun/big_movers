"""Breakout-pivot detection for big-winner moves.

Given a move's [low_date, high_date] window, score every candidate
(day, base) pair and return the highest-quality one. "Quality" prefers:

- longer bases (real consolidation, not a 10-day wiggle)
- tighter depth (closer to 5% than 25%)
- higher breakout volume surge (closer to 3x than 1.4x)

Everything downstream treats the returned pivot as the anchor for base
analysis, so this function is the critical primitive. Inner loop uses
numpy arrays to avoid per-slice pandas overhead.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _score_candidate(base_len: int, depth: float, rel_vol: float,
                     max_base_depth: float) -> float:
    len_q = min(base_len, 50) / 50.0
    depth_q = max(0.0, 1.0 - (depth / max_base_depth))
    vol_q = min(rel_vol / 3.0, 1.0)
    return 0.45 * len_q + 0.40 * depth_q + 0.15 * vol_q


def find_breakout_pivot(
    indic: pd.DataFrame,
    low_date: pd.Timestamp,
    high_date: pd.Timestamp,
    min_base_len: int = 15,
    max_base_len: int = 80,
    max_base_depth: float = 0.25,
    min_breakout_rel_vol: float = 1.4,
    base_len_stride: int = 3,
) -> dict | None:
    """Score every qualifying (day, base) pair and return the best.

    `base_len_stride` controls how coarsely we sample base lengths inside
    the inner loop. Default 3 = try 15, 18, 21, ..., 78, which is enough
    granularity to find good bases without scanning every length.
    """
    if pd.isna(low_date) or pd.isna(high_date) or low_date >= high_date:
        return None

    try:
        window = indic.loc[low_date:high_date]
    except KeyError:
        return None

    n = len(window)
    if n < min_base_len + 2:
        return None

    # Pull out numpy arrays once — avoids per-iteration pandas overhead
    highs = window["high"].to_numpy(dtype=float)
    lows = window["low"].to_numpy(dtype=float)
    closes = window["close"].to_numpy(dtype=float)
    rel_vols = window["rel_vol"].to_numpy(dtype=float)
    dates = window.index.to_numpy()

    best: dict | None = None
    best_score = -1.0

    # Precompute rolling max/min per base_len using numpy maximum.accumulate
    # approach won't help here because base_lens vary — stick with explicit
    # slice but on numpy arrays (much faster than pandas .max()).

    base_lens = list(range(min_base_len, max_base_len + 1, base_len_stride))

    for i in range(min_base_len, n - 1):
        rv = rel_vols[i]
        if np.isnan(rv) or rv < min_breakout_rel_vol:
            continue
        today_close = closes[i]
        if np.isnan(today_close):
            continue

        day_best_score = -1.0
        day_best_payload: dict | None = None

        for base_len in base_lens:
            if base_len > i:
                break
            lo_idx = i - base_len
            base_highs = highs[lo_idx:i]
            base_lows = lows[lo_idx:i]
            bh = np.nanmax(base_highs)
            bl = np.nanmin(base_lows)
            if not np.isfinite(bh) or not np.isfinite(bl) or bh <= 0:
                continue
            depth = (bh - bl) / bh
            if depth > max_base_depth:
                continue
            if today_close <= bh:
                continue

            score = _score_candidate(base_len, depth, float(rv), max_base_depth)
            if score > day_best_score:
                day_best_score = score
                day_best_payload = {
                    "pivot_idx": i,
                    "base_lo_idx": lo_idx,
                    "base_hi_idx": i - 1,
                    "base_high": float(bh),
                    "base_low": float(bl),
                    "depth": float(depth),
                    "rel_vol": float(rv),
                }

        if day_best_payload is not None and day_best_score > best_score:
            best_score = day_best_score
            best = day_best_payload

    if best is None:
        return None

    return {
        "pivot_date": pd.Timestamp(dates[best["pivot_idx"]]),
        "pivot_idx_in_window": best["pivot_idx"],
        "base_start": pd.Timestamp(dates[best["base_lo_idx"]]),
        "base_end": pd.Timestamp(dates[best["base_hi_idx"]]),
        "base_high": best["base_high"],
        "base_low": best["base_low"],
        "base_depth_pct": best["depth"] * 100.0,
        "breakout_rel_vol": best["rel_vol"],
        "breakout_close": float(closes[best["pivot_idx"]]),
        "quality_score": float(best_score),
    }
