"""Pocket Pivot detector.

Implements §4.1 of the setup classification reference. Applied to the
breakout/pivot day — checks the day's up/down volume dynamics and MA
proximity. In this POC, this is checked at the breakout pivot day (not a
separate base-level search).
"""
from __future__ import annotations

import pandas as pd

from classifier.setups import DetectorResult


def detect_pocket_pivot(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="Pocket Pivot", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    pivot_date = pivot["pivot_date"]
    try:
        history = indic.loc[:pivot_date]
    except Exception:
        r.criteria_failed.append("history_slice_error")
        return r
    if len(history) < 22:
        r.criteria_failed.append("history_too_short")
        return r

    today = history.iloc[-1]
    prior_close = history["close"].iloc[-2]
    prev_10 = history.iloc[-11:-1]  # prior 10 sessions (excluding today)

    # ---- above_sma200 (hard fail if below) ----
    sma200 = today.get("sma200")
    if pd.isna(sma200):
        r.criteria_failed.append("above_sma200 (nan)")
        return r
    if today["close"] > sma200:
        r.score += 30  # prereq gate
        r.criteria_met.append("above_sma200")
        above_sma200 = True
    else:
        r.criteria_failed.append("above_sma200")
        return r  # hard fail

    # ---- up_day ----
    up_day = bool(pd.notna(prior_close) and today["close"] > prior_close)
    if up_day:
        r.score += 10
        r.criteria_met.append("up_day")
    else:
        r.criteria_failed.append("up_day")

    # ---- vol_beats_10d_downvol (critical) ----
    vol_beats = False
    down_day_vols = []
    for i in range(len(prev_10)):
        if i == 0:
            # Need prior to that to know direction
            try:
                prev_prev_close = history["close"].iloc[-12]
            except Exception:
                continue
            bar = prev_10.iloc[0]
            if (
                pd.notna(prev_prev_close)
                and pd.notna(bar["close"])
                and pd.notna(bar["volume"])
                and bar["close"] < prev_prev_close
            ):
                down_day_vols.append(bar["volume"])
        else:
            bar = prev_10.iloc[i]
            prev_bar = prev_10.iloc[i - 1]
            if (
                pd.notna(prev_bar["close"])
                and pd.notna(bar["close"])
                and pd.notna(bar["volume"])
                and bar["close"] < prev_bar["close"]
            ):
                down_day_vols.append(bar["volume"])

    max_down_vol = max(down_day_vols) if down_day_vols else 0
    today_vol = today["volume"] if pd.notna(today["volume"]) else 0
    if today_vol > max_down_vol and today_vol > 0:
        vol_beats = True
        r.score += 10
        r.criteria_met.append(f"vol_beats_10d_downvol ({int(today_vol)} > {int(max_down_vol)})")
    else:
        r.criteria_failed.append(
            f"vol_beats_10d_downvol ({int(today_vol)} <= {int(max_down_vol)})"
        )

    # ---- close_upper_two_thirds (critical) ----
    day_range = today["high"] - today["low"]
    close_upper_ok = False
    if day_range > 0 and pd.notna(day_range):
        pos = (today["close"] - today["low"]) / day_range
        if pos >= 0.33:
            r.score += 10
            r.criteria_met.append(f"close_upper_two_thirds ({pos:.2f})")
            close_upper_ok = True
        else:
            r.criteria_failed.append(f"close_upper_two_thirds ({pos:.2f})")
    else:
        r.criteria_failed.append("close_upper_two_thirds (no range)")

    # ---- near_ma (critical): low within 2% of ema10 OR 3% of sma50 ----
    near_ma = False
    ema10 = today.get("ema10")
    sma50 = today.get("sma50")
    low = today["low"]
    if pd.notna(ema10) and ema10 > 0 and abs(low - ema10) / ema10 <= 0.02:
        near_ma = True
    elif pd.notna(sma50) and sma50 > 0 and abs(low - sma50) / sma50 <= 0.03:
        near_ma = True
    if near_ma:
        r.score += 10
        r.criteria_met.append("near_ma")
    else:
        r.criteria_failed.append("near_ma")

    # ---- rising_sma50 ----
    try:
        if len(history) >= 22:
            sma50_today = today["sma50"]
            sma50_21 = history["sma50"].iloc[-22]
            if pd.notna(sma50_today) and pd.notna(sma50_21) and sma50_today > sma50_21:
                r.score += 5
                r.criteria_met.append("rising_sma50")
            else:
                r.criteria_failed.append("rising_sma50")
    except Exception:
        r.criteria_failed.append("rising_sma50 (lookup error)")

    # A+ filter: close in top 25% (tighter)
    if day_range > 0 and pd.notna(day_range):
        pos = (today["close"] - today["low"]) / day_range
        if pos >= 0.75:
            r.score += 5
            r.criteria_met.append("aplus_close_top_quarter")

    if r.score > 100:
        r.score = 100

    r.extra["today_vol"] = int(today_vol)
    r.extra["max_down_vol_10d"] = int(max_down_vol)
    r.extra["num_down_days_10d"] = len(down_day_vols)

    r.matched = (
        r.score >= 60
        and vol_beats
        and close_upper_ok
        and near_ma
        and above_sma200
    )
    return r
