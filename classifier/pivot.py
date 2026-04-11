"""Breakout-pivot detection for big-winner moves.

Given a move's [low_date, high_date] window, find the day the stock broke
out of a tight base with volume expansion. Everything downstream treats
this pivot as the anchor for base analysis.
"""
from __future__ import annotations

import pandas as pd


def find_breakout_pivot(
    indic: pd.DataFrame,
    low_date: pd.Timestamp,
    high_date: pd.Timestamp,
    min_base_len: int = 10,
    max_base_len: int = 80,
    max_base_depth: float = 0.30,
    min_breakout_rel_vol: float = 1.4,
) -> dict | None:
    """Walk forward from low_date; return the earliest day where price
    closed above the preceding N-day base high on volume >= 1.4x avg.

    Returns a dict with pivot_date, base_start, base_end, base_high,
    base_low, base_depth_pct, breakout_rel_vol — or None if no candidate.
    """
    if pd.isna(low_date) or pd.isna(high_date) or low_date >= high_date:
        return None

    # Window from low to high, inclusive
    try:
        window = indic.loc[low_date:high_date]
    except KeyError:
        return None

    if len(window) < min_base_len + 2:
        return None

    for i in range(min_base_len, len(window) - 1):
        today = window.iloc[i]
        rel_vol = today.get("rel_vol")
        if pd.isna(rel_vol) or rel_vol < min_breakout_rel_vol:
            continue

        # Try several base lengths; pick the tightest one that satisfies the breakout
        best_for_this_day = None
        for base_len in range(min_base_len, min(i, max_base_len) + 1):
            base = window.iloc[i - base_len : i]
            base_high = base["high"].max()
            base_low = base["low"].min()
            depth = (base_high - base_low) / base_high if base_high > 0 else 1.0
            if depth > max_base_depth:
                continue
            if today["close"] <= base_high:
                continue
            # Found a qualifying base for this day — prefer longer bases (more meaningful)
            candidate = {
                "pivot_date": window.index[i],
                "pivot_idx_in_window": i,
                "base_start": base.index[0],
                "base_end": base.index[-1],
                "base_high": float(base_high),
                "base_low": float(base_low),
                "base_depth_pct": float(depth * 100),
                "breakout_rel_vol": float(rel_vol),
                "breakout_close": float(today["close"]),
            }
            if best_for_this_day is None or base_len > (best_for_this_day["pivot_idx_in_window"] -
                                                       window.index.get_loc(best_for_this_day["base_start"])):
                best_for_this_day = candidate

        if best_for_this_day is not None:
            return best_for_this_day

    return None
