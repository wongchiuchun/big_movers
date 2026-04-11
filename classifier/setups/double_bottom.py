"""Double Bottom ('W') detector.

Implements §3.4 of the setup classification reference. Finds the last two
swing lows in the 70-day window ending at the pivot date, plus the middle
peak between them.
"""
from __future__ import annotations

import pandas as pd

from classifier.setups import DetectorResult


def detect_double_bottom(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="Double Bottom", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    pivot_date = pivot["pivot_date"]
    try:
        full_window = indic.loc[:pivot_date].iloc[-70:]
    except Exception:
        r.criteria_failed.append("window_slice_error")
        return r
    if full_window.empty or len(full_window) < 20:
        r.criteria_failed.append("window_too_short")
        return r

    window_start_date = full_window.index[0]

    # Pull swings that fall inside our window
    swings = indic.attrs.get("swings", []) or []
    in_win = [
        s for s in swings
        if window_start_date <= s["date"] <= pivot_date
    ]
    lows = [s for s in in_win if s["kind"] == "low"]
    highs = [s for s in in_win if s["kind"] == "high"]

    if len(lows) < 2:
        r.criteria_failed.append("two_lows_found")
        return r
    r.score += 10
    r.criteria_met.append("two_lows_found")

    low1 = lows[-2]
    low2 = lows[-1]
    middle_peaks = [h for h in highs if low1["date"] < h["date"] < low2["date"]]
    if not middle_peaks:
        r.criteria_failed.append("middle_peak")
        return r
    # Use the highest middle peak
    peak = max(middle_peaks, key=lambda h: h["price"])

    # ---- Prior-trend gate (not strict: just grant +30 if there was any advance first) ----
    try:
        prior_window = indic.loc[:low1["date"]].iloc[-64:-1]
        if len(prior_window) >= 5:
            start_close = prior_window["close"].iloc[0]
            if pd.notna(start_close) and start_close > 0:
                low1_close = indic.loc[low1["date"], "close"]
                # Either +20% advance before or simply grant if pattern forms
                # after a pullback from a prior run
                prior_gain = (low1_close / start_close) - 1.0
                if prior_gain >= 0.0:  # any non-negative prior context
                    r.score += 30
                    r.criteria_met.append(f"prior_context ({prior_gain*100:.1f}%)")
    except Exception:
        pass

    # ---- lows_within_5pct (critical) ----
    if low1["price"] > 0:
        diff = abs(low2["price"] - low1["price"]) / low1["price"]
    else:
        diff = 1.0
    lows_within_5pct = diff <= 0.05
    if lows_within_5pct:
        r.score += 10
        r.criteria_met.append(f"lows_within_5pct ({diff*100:.1f}%)")
    else:
        r.criteria_failed.append(f"lows_within_5pct ({diff*100:.1f}%)")

    # ---- middle_peak_rally_10_30 (critical) ----
    if low1["price"] > 0:
        rally = (peak["price"] - low1["price"]) / low1["price"]
    else:
        rally = 0.0
    middle_peak_rally_ok = 0.10 <= rally <= 0.30
    if middle_peak_rally_ok:
        r.score += 10
        r.criteria_met.append(f"middle_peak_rally_10_30 ({rally*100:.1f}%)")
    else:
        r.criteria_failed.append(f"middle_peak_rally_10_30 ({rally*100:.1f}%)")

    # ---- 4w_between_lows ----
    bars_between = low2["idx"] - low1["idx"]
    if bars_between >= 20:
        r.score += 10
        r.criteria_met.append(f"4w_between_lows ({bars_between}d)")
    else:
        r.criteria_failed.append(f"4w_between_lows ({bars_between}d)")

    # ---- breakout_above_middle_peak (critical) ----
    try:
        pivot_close = indic.loc[pivot_date, "close"]
    except Exception:
        pivot_close = None
    breakout_above_middle_peak = False
    if pivot_close is not None and pd.notna(pivot_close) and pivot_close > peak["price"]:
        r.score += 10
        r.criteria_met.append("breakout_above_middle_peak")
        breakout_above_middle_peak = True
    else:
        r.criteria_failed.append("breakout_above_middle_peak")

    # ---- breakout_vol_15x ----
    breakout_vol = pivot.get("breakout_rel_vol", 0.0) or 0.0
    if breakout_vol >= 1.5:
        r.score += 10
        r.criteria_met.append(f"breakout_vol_15x ({breakout_vol:.2f}x)")
    else:
        r.criteria_failed.append(f"breakout_vol_15x ({breakout_vol:.2f}x)")

    # ---- A+ filter: undercut (low2 < low1 but within 5%) ----
    if low2["price"] < low1["price"] and low2["price"] > low1["price"] * 0.95:
        r.score += 5
        r.criteria_met.append("aplus_undercut")

    # Cap
    if r.score > 100:
        r.score = 100

    r.extra["low1"] = {"date": str(low1["date"].date()) if hasattr(low1["date"], "date") else str(low1["date"]),
                       "price": round(low1["price"], 4)}
    r.extra["low2"] = {"date": str(low2["date"].date()) if hasattr(low2["date"], "date") else str(low2["date"]),
                       "price": round(low2["price"], 4)}
    r.extra["peak"] = {"date": str(peak["date"].date()) if hasattr(peak["date"], "date") else str(peak["date"]),
                       "price": round(peak["price"], 4)}
    r.extra["rally_pct"] = round(rally * 100, 1)

    r.matched = (
        r.score >= 60
        and lows_within_5pct
        and middle_peak_rally_ok
        and breakout_above_middle_peak
    )
    return r
