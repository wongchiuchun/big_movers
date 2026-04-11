"""Cup with Handle detector.

Implements §3.2 of the setup classification reference. Treats the base
window (base_start..base_end) as the HANDLE, then walks backwards looking
for a prior swing high at a similar price level to define the cup's left
edge.
"""
from __future__ import annotations

import pandas as pd

from classifier.setups import DetectorResult


def detect_cup_handle(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="Cup with Handle", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    base_start = pivot["base_start"]
    base_end = pivot["base_end"]
    pivot_date = pivot["pivot_date"]

    try:
        handle = indic.loc[base_start:base_end]
    except Exception:
        r.criteria_failed.append("handle_slice_error")
        return r
    if handle.empty:
        r.criteria_failed.append("empty_handle")
        return r

    handle_high = float(handle["high"].max())
    handle_low = float(handle["low"].min())
    if handle_high <= 0:
        r.criteria_failed.append("bad_handle_prices")
        return r

    # ---- Walk back from base_start looking for cup left edge ----
    # Prior history: up to 200 bars ending just before base_start
    try:
        prior = indic.loc[:base_start].iloc[:-1]
    except Exception:
        prior = pd.DataFrame()
    if len(prior) < 35:
        r.criteria_failed.append("cup_history_too_short")
        return r

    lookback = prior.iloc[-200:] if len(prior) > 200 else prior

    # Find a prior high >= handle_high * 0.98 (within 2% tolerance of handle_high)
    tolerance_lo = handle_high * 0.98
    tolerance_hi = handle_high * 1.02
    # Walk from newest back to oldest; we want the most recent matching high
    highs = lookback["high"]
    found_idx: pd.Timestamp | None = None
    for date, h in highs.iloc[::-1].items():
        if pd.isna(h):
            continue
        if tolerance_lo <= h <= tolerance_hi:
            found_idx = date
            break

    if found_idx is None:
        r.criteria_failed.append("found_cup_left_edge")
        return r
    r.score += 10
    r.criteria_met.append("found_cup_left_edge")
    found_cup_left_edge = True

    # ---- Prior-trend gate before the cup (+30) ----
    try:
        before_cup = indic.loc[:found_idx].iloc[-64:-1]
        if len(before_cup) >= 5:
            start_close = before_cup["close"].iloc[0]
            cup_start_close = indic.loc[found_idx, "close"]
            if pd.notna(start_close) and start_close > 0 and pd.notna(cup_start_close):
                prior_gain = (cup_start_close / start_close) - 1.0
                if prior_gain >= 0.30:
                    r.score += 30
                    r.criteria_met.append(f"prior_uptrend_30 ({prior_gain*100:.1f}%)")
                else:
                    r.criteria_failed.append(f"prior_uptrend_30 ({prior_gain*100:.1f}%)")
    except Exception:
        r.criteria_failed.append("prior_uptrend_30 (lookup error)")

    # ---- Cup structure ----
    try:
        cup = indic.loc[found_idx:base_start]
    except Exception:
        r.criteria_failed.append("cup_slice_error")
        return r
    if len(cup) < 2:
        r.criteria_failed.append("cup_empty")
        return r

    cup_high = float(cup["high"].max())
    cup_low = float(cup["low"].min())
    cup_days = len(cup)
    cup_depth = (cup_high - cup_low) / cup_high if cup_high > 0 else 1.0

    # ---- Core: cup_duration_7w (>=35) ----
    if cup_days >= 35:
        r.score += 10
        r.criteria_met.append(f"cup_duration_7w ({cup_days}d)")
    else:
        r.criteria_failed.append(f"cup_duration_7w ({cup_days}d)")

    # ---- Core: cup_depth_33 (<=33%) ----
    if cup_depth <= 0.33:
        r.score += 10
        r.criteria_met.append(f"cup_depth_33 ({cup_depth*100:.1f}%)")
    else:
        r.criteria_failed.append(f"cup_depth_33 ({cup_depth*100:.1f}%)")

    # ---- A+ filter: u_shape (bottom bars within 5% of cup_low >= 15) ----
    if cup_low > 0:
        bottom_threshold = cup_low * 1.05
        bottom_bars = int((cup["low"] <= bottom_threshold).sum())
        if bottom_bars >= 15:
            r.score += 5
            r.criteria_met.append(f"u_shape ({bottom_bars} bottom bars)")
        else:
            r.criteria_failed.append(f"u_shape ({bottom_bars} bottom bars)")

    # ---- Core/critical: handle_depth_15 ----
    handle_depth = (handle_high - handle_low) / handle_high if handle_high > 0 else 1.0
    handle_depth_15 = handle_depth <= 0.15
    if handle_depth_15:
        r.score += 10
        r.criteria_met.append(f"handle_depth_15 ({handle_depth*100:.1f}%)")
    else:
        r.criteria_failed.append(f"handle_depth_15 ({handle_depth*100:.1f}%)")

    # ---- Core/critical: handle_upper_half ----
    midpoint = (cup_high + cup_low) / 2.0
    handle_upper_half = handle_low >= midpoint
    if handle_upper_half:
        r.score += 10
        r.criteria_met.append("handle_upper_half")
    else:
        r.criteria_failed.append("handle_upper_half")

    # ---- Core: breakout_vol_15x ----
    breakout_vol = pivot.get("breakout_rel_vol", 0.0) or 0.0
    if breakout_vol >= 1.5:
        r.score += 10
        r.criteria_met.append(f"breakout_vol_15x ({breakout_vol:.2f}x)")
    else:
        r.criteria_failed.append(f"breakout_vol_15x ({breakout_vol:.2f}x)")

    # ---- A+ filter: handle_above_50sma ----
    try:
        sma50_at_handle = handle["sma50"].iloc[0]
        if pd.notna(sma50_at_handle) and handle_low >= sma50_at_handle:
            r.score += 5
            r.criteria_met.append("aplus_handle_above_50sma")
    except Exception:
        pass

    # Cap score
    if r.score > 100:
        r.score = 100

    r.extra["cup_days"] = cup_days
    r.extra["cup_depth_pct"] = round(cup_depth * 100, 1)
    r.extra["handle_depth_pct"] = round(handle_depth * 100, 1)
    r.extra["cup_left_edge"] = str(found_idx.date()) if hasattr(found_idx, "date") else str(found_idx)

    r.matched = (
        r.score >= 60
        and found_cup_left_edge
        and handle_depth_15
        and handle_upper_half
    )
    return r
