"""Episodic Pivot (EP) detector.

Implements section 5.1 of the setup classification reference. Scans for
qualifying gap-up events (>=5% gap on >=2.5x volume) and checks post-gap
consolidation quality. Entry is Day 2-10 after the gap, NOT Day 1.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from classifier.setups import DetectorResult


def detect_ep(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="Episodic Pivot", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    pivot_date = pivot["pivot_date"]

    # Scan window: 60 trading days before pivot through pivot_date
    try:
        end_loc = indic.index.get_loc(pivot_date)
    except KeyError:
        r.criteria_failed.append("pivot_date_not_in_index")
        return r
    start_loc = max(0, end_loc - 60)
    window = indic.iloc[start_loc : end_loc + 6]  # +5 days past pivot for post-gap check

    if len(window) < 5:
        r.criteria_failed.append("window_too_short")
        return r

    # --- Scan for qualifying gap events ---
    opens = window["open"].to_numpy(dtype=float)
    closes = window["close"].to_numpy(dtype=float)
    highs = window["high"].to_numpy(dtype=float)
    lows = window["low"].to_numpy(dtype=float)
    volumes = window["volume"].to_numpy(dtype=float)
    avg_vols = window["avg_vol_50"].to_numpy(dtype=float)
    dates = window.index

    candidates = []

    for i in range(1, len(window) - 1):  # skip first bar (need prior close)
        prior_close = closes[i - 1]
        if np.isnan(prior_close) or prior_close <= 0:
            continue

        gap_pct = (opens[i] - prior_close) / prior_close
        if gap_pct < 0.05:
            continue

        # Volume check: rel_vol >= 2.5
        avg_v = avg_vols[i]
        if np.isnan(avg_v) or avg_v <= 0:
            continue
        gap_rel_vol = volumes[i] / avg_v
        if gap_rel_vol < 2.5:
            continue

        # This is a qualifying gap day at index i
        gap_day_low = lows[i]
        gap_day_high = highs[i]

        # Post-gap analysis: look at next 2-10 bars
        post_start = i + 1
        post_end = min(i + 11, len(window))  # up to 10 bars after gap
        if post_start >= len(window):
            continue

        post_bars = post_end - post_start
        if post_bars < 1:
            continue

        post_lows = lows[post_start:post_end]
        post_highs = highs[post_start:post_end]

        # Check if post-gap bars held above gap day low
        held_above_gap_low = bool(np.all(post_lows >= gap_day_low * 0.98))
        # Strict check (no tolerance)
        held_above_gap_low_strict = bool(np.all(post_lows >= gap_day_low))

        # Post-gap consolidation range
        pg_hi = float(np.nanmax(post_highs))
        pg_lo = float(np.nanmin(post_lows))
        if pg_hi > 0:
            post_gap_range_pct = (pg_hi - pg_lo) / pg_hi
        else:
            post_gap_range_pct = 1.0

        # Gap fill check: did price fill <30% of the gap in first 2 days?
        gap_size = opens[i] - prior_close
        first_2_lows = lows[post_start : min(post_start + 2, len(window))]
        if len(first_2_lows) > 0 and gap_size > 0:
            max_fill = opens[i] - float(np.nanmin(first_2_lows))
            gap_fill_pct = max_fill / gap_size if gap_size > 0 else 0
        else:
            gap_fill_pct = 0.0

        # Breakout close position (on first post-gap bar that breaks above consolidation)
        breakout_close_pos = 0.0
        for j in range(post_start, post_end):
            day_range = highs[j] - lows[j]
            if day_range > 0:
                breakout_close_pos = (closes[j] - lows[j]) / day_range
                break

        # Strength metric for ranking
        strength = gap_pct * gap_rel_vol

        days_to_entry = post_bars  # how many days between gap and end of window

        candidates.append({
            "idx": i,
            "gap_date": dates[i],
            "gap_pct": float(gap_pct),
            "gap_rel_vol": float(gap_rel_vol),
            "gap_day_low": float(gap_day_low),
            "gap_day_high": float(gap_day_high),
            "held_above_gap_low": held_above_gap_low,
            "held_above_gap_low_strict": held_above_gap_low_strict,
            "post_gap_range_pct": float(post_gap_range_pct),
            "gap_fill_pct": float(gap_fill_pct),
            "breakout_close_pos": float(breakout_close_pos),
            "strength": float(strength),
            "days_to_entry": days_to_entry,
            "prior_close": float(prior_close),
        })

    if not candidates:
        r.criteria_failed.append("no_qualifying_gap (>=5% gap + >=2.5x vol)")
        return r

    # Pick the strongest gap candidate
    best = max(candidates, key=lambda c: c["strength"])

    # --- Scoring ---
    score = 0
    criteria_met = []
    criteria_failed = []

    # Gate: found a qualifying gap (+30)
    score += 30
    criteria_met.append(
        f"qualifying_gap ({best['gap_pct']:.1%} gap, {best['gap_rel_vol']:.1f}x vol)"
    )

    # gap_pct >= 10% (+10)
    if best["gap_pct"] >= 0.10:
        score += 10
        criteria_met.append(f"gap_gte_10pct ({best['gap_pct']:.1%})")
    else:
        criteria_failed.append(f"gap_gte_10pct ({best['gap_pct']:.1%})")

    # rel_vol >= 3.0 (+10)
    if best["gap_rel_vol"] >= 3.0:
        score += 10
        criteria_met.append(f"rel_vol_gte_3x ({best['gap_rel_vol']:.1f}x)")
    else:
        criteria_failed.append(f"rel_vol_gte_3x ({best['gap_rel_vol']:.1f}x)")

    # Post-gap held above gap low (+10)
    if best["held_above_gap_low"]:
        score += 10
        criteria_met.append("post_gap_held_above_gap_low")
    else:
        criteria_failed.append("post_gap_held_above_gap_low")

    # Tight post-gap consolidation <= 10% (+10)
    if best["post_gap_range_pct"] <= 0.10:
        score += 10
        criteria_met.append(f"tight_consolidation ({best['post_gap_range_pct']:.1%})")
    elif best["post_gap_range_pct"] <= 0.15:
        score += 5
        criteria_met.append(f"moderate_consolidation ({best['post_gap_range_pct']:.1%})")
    else:
        criteria_failed.append(f"tight_consolidation ({best['post_gap_range_pct']:.1%})")

    # A+ filters
    if best["gap_pct"] >= 0.15:
        score += 5
        criteria_met.append(f"aplus_gap_gte_15pct ({best['gap_pct']:.1%})")

    if best["gap_rel_vol"] >= 5.0:
        score += 5
        criteria_met.append(f"aplus_vol_gte_5x ({best['gap_rel_vol']:.1f}x)")

    if best["gap_fill_pct"] < 0.30:
        score += 5
        criteria_met.append(f"aplus_gap_fill_lt_30pct ({best['gap_fill_pct']:.0%})")
    else:
        criteria_failed.append(f"aplus_gap_fill_lt_30pct ({best['gap_fill_pct']:.0%})")

    if best["breakout_close_pos"] >= 0.75:
        score += 5
        criteria_met.append(
            f"aplus_close_top_25pct ({best['breakout_close_pos']:.0%})"
        )

    if score > 100:
        score = 100

    r.score = score
    r.criteria_met = criteria_met
    r.criteria_failed = criteria_failed

    r.extra["gap_date"] = best["gap_date"].strftime("%Y-%m-%d") if hasattr(best["gap_date"], "strftime") else str(best["gap_date"])
    r.extra["gap_pct"] = round(best["gap_pct"] * 100, 1)
    r.extra["gap_rel_vol"] = round(best["gap_rel_vol"], 1)
    r.extra["post_gap_range_pct"] = round(best["post_gap_range_pct"] * 100, 1)
    r.extra["days_to_entry"] = best["days_to_entry"]

    # Matched: score >= 60 AND found a qualifying gap AND post-gap held
    r.matched = score >= 60 and best["held_above_gap_low"]

    return r
