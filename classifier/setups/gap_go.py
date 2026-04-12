"""Gap & Go (Day 1) detector.

Implements section 5.2 of the setup classification reference. Same family
as EP but stricter thresholds (>=10% gap, >=3x volume) and the entry is
on the gap day itself — NOT after consolidation.

Key difference from EP: requires close > open (held above open, not
"gap and crap") and low > prior close (didn't fill the gap).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from classifier.setups import DetectorResult


def detect_gap_go(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="Gap & Go", matched=False)
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
    window = indic.iloc[start_loc : end_loc + 1]

    if len(window) < 3:
        r.criteria_failed.append("window_too_short")
        return r

    # --- Scan for qualifying Gap & Go events ---
    opens = window["open"].to_numpy(dtype=float)
    closes = window["close"].to_numpy(dtype=float)
    highs = window["high"].to_numpy(dtype=float)
    lows = window["low"].to_numpy(dtype=float)
    volumes = window["volume"].to_numpy(dtype=float)
    avg_vols = window["avg_vol_50"].to_numpy(dtype=float)
    dates = window.index

    candidates = []

    for i in range(1, len(window)):
        prior_close = closes[i - 1]
        if np.isnan(prior_close) or prior_close <= 0:
            continue

        gap_pct = (opens[i] - prior_close) / prior_close
        if gap_pct < 0.10:
            continue

        # Volume check: rel_vol >= 3.0
        avg_v = avg_vols[i]
        if np.isnan(avg_v) or avg_v <= 0:
            continue
        gap_rel_vol = volumes[i] / avg_v
        if gap_rel_vol < 3.0:
            continue

        # Close > open (held above open, not gap-and-crap)
        # Allow small tolerance: close >= open * 0.98
        close_above_open = closes[i] > opens[i]

        # Low > prior close (didn't fill the gap)
        low_above_prior = lows[i] > prior_close

        # All four gate criteria needed
        gate_met = (
            gap_pct >= 0.10
            and gap_rel_vol >= 3.0
            and close_above_open
            and low_above_prior
        )

        # Close position within day range
        day_range = highs[i] - lows[i]
        if day_range > 0:
            close_pos = (closes[i] - lows[i]) / day_range
        else:
            close_pos = 0.5

        # Strength metric for ranking
        strength = gap_pct * gap_rel_vol

        candidates.append({
            "idx": i,
            "gap_date": dates[i],
            "gap_pct": float(gap_pct),
            "gap_rel_vol": float(gap_rel_vol),
            "close_above_open": close_above_open,
            "low_above_prior": low_above_prior,
            "close_pos": float(close_pos),
            "gate_met": gate_met,
            "strength": float(strength),
            "prior_close": float(prior_close),
        })

    if not candidates:
        r.criteria_failed.append("no_qualifying_gap (>=10% gap + >=3x vol)")
        return r

    # Prefer candidates where gate is fully met; among those, pick strongest
    gate_candidates = [c for c in candidates if c["gate_met"]]
    if gate_candidates:
        best = max(gate_candidates, key=lambda c: c["strength"])
    else:
        best = max(candidates, key=lambda c: c["strength"])

    # --- Scoring ---
    score = 0
    criteria_met = []
    criteria_failed = []

    # Gate: all four conditions met (+30)
    if best["gate_met"]:
        score += 30
        criteria_met.append(
            f"gate_passed ({best['gap_pct']:.0%} gap, {best['gap_rel_vol']:.1f}x vol, "
            f"close>open={best['close_above_open']}, low>prior={best['low_above_prior']})"
        )
    else:
        # Partial credit: report which sub-gates passed/failed
        if best["gap_pct"] >= 0.10:
            criteria_met.append(f"gap_gte_10pct ({best['gap_pct']:.0%})")
        else:
            criteria_failed.append(f"gap_gte_10pct ({best['gap_pct']:.0%})")
        if best["gap_rel_vol"] >= 3.0:
            criteria_met.append(f"vol_gte_3x ({best['gap_rel_vol']:.1f}x)")
        else:
            criteria_failed.append(f"vol_gte_3x ({best['gap_rel_vol']:.1f}x)")
        if best["close_above_open"]:
            criteria_met.append("close_above_open")
        else:
            criteria_failed.append("close_above_open (gap-and-crap)")
        if best["low_above_prior"]:
            criteria_met.append("low_above_prior_close")
        else:
            criteria_failed.append("low_above_prior_close (gap filled)")

    # gap >= 20% (+10)
    if best["gap_pct"] >= 0.20:
        score += 10
        criteria_met.append(f"gap_gte_20pct ({best['gap_pct']:.0%})")
    else:
        criteria_failed.append(f"gap_gte_20pct ({best['gap_pct']:.0%})")

    # vol >= 5x (+10)
    if best["gap_rel_vol"] >= 5.0:
        score += 10
        criteria_met.append(f"vol_gte_5x ({best['gap_rel_vol']:.1f}x)")
    else:
        criteria_failed.append(f"vol_gte_5x ({best['gap_rel_vol']:.1f}x)")

    # close in top 50% of day range (+10)
    if best["close_pos"] >= 0.50:
        score += 10
        criteria_met.append(f"close_top_50pct ({best['close_pos']:.0%})")
    else:
        criteria_failed.append(f"close_top_50pct ({best['close_pos']:.0%})")

    # A+ filters
    if best["gap_pct"] >= 0.30:
        score += 5
        criteria_met.append(f"aplus_gap_gte_30pct ({best['gap_pct']:.0%})")

    if best["gap_rel_vol"] >= 8.0:
        score += 5
        criteria_met.append(f"aplus_vol_gte_8x ({best['gap_rel_vol']:.1f}x)")

    if score > 100:
        score = 100

    r.score = score
    r.criteria_met = criteria_met
    r.criteria_failed = criteria_failed

    r.extra["gap_date"] = best["gap_date"].strftime("%Y-%m-%d") if hasattr(best["gap_date"], "strftime") else str(best["gap_date"])
    r.extra["gap_pct"] = round(best["gap_pct"] * 100, 1)
    r.extra["gap_rel_vol"] = round(best["gap_rel_vol"], 1)

    # Matched: score >= 50 AND gate criteria met
    r.matched = score >= 50 and best["gate_met"]

    return r
