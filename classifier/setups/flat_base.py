"""Flat Base detector.

Implements §3.3 of the setup classification reference: a tight sideways
consolidation ≤15% deep lasting 5+ weeks, following a ≥30% prior advance.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from classifier.setups import DetectorResult


def detect_flat_base(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="Flat Base", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    base_start = pivot["base_start"]
    base_end = pivot["base_end"]
    try:
        base = indic.loc[base_start:base_end]
    except Exception:
        r.criteria_failed.append("base_slice_error")
        return r
    if base.empty:
        r.criteria_failed.append("empty_base")
        return r

    # ---- Prior advance gate (+30 prereq) ----
    prior_window = indic.loc[:base_start].iloc[-64:-1]
    if len(prior_window) < 5:
        r.criteria_failed.append("prior_advance_30 (insufficient history)")
        return r
    start_close = prior_window["close"].iloc[0]
    base_start_close = base["close"].iloc[0]
    if pd.isna(start_close) or start_close <= 0:
        r.criteria_failed.append("prior_advance_30 (nan)")
        return r
    prior_gain = (base_start_close / start_close) - 1.0
    if prior_gain >= 0.30:
        r.score += 30
        r.criteria_met.append(f"prior_advance_30 ({prior_gain*100:.1f}%)")
    else:
        r.criteria_failed.append(f"prior_advance_30 ({prior_gain*100:.1f}%)")
        return r  # hard fail

    # ---- Core: duration_5w (len >= 25) ----
    base_len = len(base)
    if base_len >= 25:
        r.score += 10
        r.criteria_met.append(f"duration_5w ({base_len}d)")
    else:
        r.criteria_failed.append(f"duration_5w ({base_len}d)")

    # ---- Core/critical: depth_under_15 (hard req) ----
    depth_pct = pivot.get("base_depth_pct", 100.0)
    depth_under_15 = depth_pct <= 15.0
    if depth_under_15:
        r.score += 10
        r.criteria_met.append(f"depth_under_15 ({depth_pct:.1f}%)")
    else:
        r.criteria_failed.append(f"depth_under_15 ({depth_pct:.1f}%)")

    # ---- Core/critical: horizontal_slope ----
    horizontal = False
    if len(base) >= 5:
        closes = base["close"].dropna().to_numpy()
        if len(closes) >= 5:
            x = np.arange(len(closes))
            try:
                slope, _intercept = np.polyfit(x, closes, 1)
                mean_close = closes.mean()
                if mean_close > 0 and not np.isnan(slope):
                    normalized = abs(slope) / mean_close
                    if normalized < 0.002:
                        horizontal = True
                        r.score += 10
                        r.criteria_met.append(f"horizontal_slope ({normalized:.5f})")
                    else:
                        r.criteria_failed.append(f"horizontal_slope ({normalized:.5f})")
                else:
                    r.criteria_failed.append("horizontal_slope (nan)")
            except Exception:
                r.criteria_failed.append("horizontal_slope (polyfit failed)")
        else:
            r.criteria_failed.append("horizontal_slope (not enough valid closes)")
    else:
        r.criteria_failed.append("horizontal_slope (base too short)")

    # ---- Core: breakout_vol_14x ----
    breakout_vol = pivot.get("breakout_rel_vol", 0.0) or 0.0
    if breakout_vol >= 1.4:
        r.score += 10
        r.criteria_met.append(f"breakout_vol_14x ({breakout_vol:.2f}x)")
    else:
        r.criteria_failed.append(f"breakout_vol_14x ({breakout_vol:.2f}x)")

    # ---- A+ filter: aplus_depth_10 ----
    if depth_pct <= 10.0:
        r.score += 5
        r.criteria_met.append(f"aplus_depth_10 ({depth_pct:.1f}%)")

    # ---- A+ filter: rising 50 SMA through the base (bonus) ----
    try:
        sma50_start = base["sma50"].iloc[0]
        sma50_end = base["sma50"].iloc[-1]
        if pd.notna(sma50_start) and pd.notna(sma50_end) and sma50_end > sma50_start:
            r.score += 5
            r.criteria_met.append("aplus_sma50_rising")
    except Exception:
        pass

    # Cap score
    if r.score > 100:
        r.score = 100

    r.extra["base_len"] = base_len
    r.extra["depth_pct"] = depth_pct
    r.extra["prior_gain_pct"] = round(prior_gain * 100, 1)

    r.matched = (r.score >= 60) and depth_under_15 and horizontal
    return r
