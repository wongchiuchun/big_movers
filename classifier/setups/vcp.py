"""Volatility Contraction Pattern detector.

Implements §3.1 of the setup classification reference. Walks the base window
bounded by `pivot["base_start"]..pivot["base_end"]`, identifies contractions
from the fractal swing detector, and scores the pattern.
"""
from __future__ import annotations

import pandas as pd

from classifier.setups import DetectorResult


def _base_contractions(base: pd.DataFrame, swings: list[dict]) -> list[float]:
    """Convert swing points inside the base window into ordered contraction depths.

    A contraction is the drop from a swing high to the next swing low
    (expressed as a fraction of the swing high). We only look at swings
    that fall within the base's index range.
    """
    if base.empty or not swings:
        return []

    base_start_date = base.index[0]
    base_end_date = base.index[-1]
    in_base = [
        s for s in swings
        if base_start_date <= s["date"] <= base_end_date
    ]
    # Ensure we start from a high, then alternate high->low->high...
    contractions: list[float] = []
    i = 0
    while i < len(in_base) - 1:
        hi = in_base[i]
        if hi["kind"] != "high":
            i += 1
            continue
        # Find the next low after this high
        lo_j = None
        for j in range(i + 1, len(in_base)):
            if in_base[j]["kind"] == "low":
                lo_j = j
                break
        if lo_j is None:
            break
        lo = in_base[lo_j]
        depth = (hi["price"] - lo["price"]) / hi["price"] if hi["price"] > 0 else 0.0
        if depth > 0:
            contractions.append(depth)
        # Advance past the low we just consumed
        i = lo_j + 1
    return contractions


def detect_vcp(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="VCP", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    pivot_date = pivot["pivot_date"]
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

    # ---- Prior uptrend (+30 if met, but now OPTIONAL — not a hard gate) ----
    # Rationale: many big winners break out of accumulation at/near the low
    # (first-leg rallies) and never satisfy Minervini's ≥20% prior advance.
    # We still score it when present, but no longer hard-fail without it.
    prior_window = indic.loc[:base_start].iloc[-64:-1]
    prior_gain = 0.0
    if len(prior_window) >= 5:
        start_close = prior_window["close"].iloc[0]
        base_start_close = base["close"].iloc[0]
        if pd.notna(start_close) and start_close > 0:
            prior_gain = (base_start_close / start_close) - 1.0
            if prior_gain >= 0.20:
                r.score += 30
                r.criteria_met.append(f"prior_uptrend_20 ({prior_gain*100:.1f}%)")
            else:
                r.criteria_failed.append(f"prior_uptrend_20 ({prior_gain*100:.1f}%)")
        else:
            r.criteria_failed.append("prior_uptrend_20 (nan)")
    else:
        r.criteria_failed.append("prior_uptrend_20 (insufficient history)")

    # ---- Core: duration 10..65 ----
    base_len = len(base)
    if 10 <= base_len <= 65:
        r.score += 10
        r.criteria_met.append(f"duration_ok ({base_len}d)")
    else:
        r.criteria_failed.append(f"duration_ok ({base_len}d)")

    # ---- Core: has_contractions (≥2) ----
    swings = indic.attrs.get("swings", []) or []
    contractions = _base_contractions(base, swings)
    if len(contractions) >= 2:
        r.score += 10
        r.criteria_met.append(f"has_contractions ({len(contractions)})")
        has_contractions = True
    else:
        r.criteria_failed.append(f"has_contractions ({len(contractions)})")
        has_contractions = False

    # ---- Core: contractions_decreasing (allow one violation) ----
    if len(contractions) >= 2:
        violations = sum(
            1 for i in range(1, len(contractions))
            if contractions[i] > contractions[i - 1]
        )
        if violations <= 1:
            r.score += 10
            r.criteria_met.append("contractions_decreasing")
        else:
            r.criteria_failed.append(f"contractions_decreasing ({violations} violations)")
    else:
        r.criteria_failed.append("contractions_decreasing (not enough data)")

    # ---- Core: final_contraction_tight (<10%) ----
    final_tight = False
    if contractions:
        last = contractions[-1]
        if last < 0.10:
            r.score += 10
            r.criteria_met.append(f"final_contraction_tight ({last*100:.1f}%)")
            final_tight = True
        else:
            r.criteria_failed.append(f"final_contraction_tight ({last*100:.1f}%)")
    else:
        r.criteria_failed.append("final_contraction_tight (no contractions)")

    # ---- A+ filter: aplus_final_5pct (+5) ----
    if contractions and contractions[-1] < 0.05:
        r.score += 5
        r.criteria_met.append("aplus_final_5pct")

    # ---- A+ filter: vdu_right_side ----
    if len(base) >= 10:
        base_avg_vol = base["volume"].mean()
        right_avg_vol = base["volume"].iloc[-10:].mean()
        if pd.notna(base_avg_vol) and base_avg_vol > 0 and pd.notna(right_avg_vol):
            if right_avg_vol < base_avg_vol * 0.75:
                r.score += 5
                r.criteria_met.append("vdu_right_side")
            else:
                r.criteria_failed.append("vdu_right_side")
        else:
            r.criteria_failed.append("vdu_right_side (nan)")
    else:
        r.criteria_failed.append("vdu_right_side (base<10)")

    # ---- Breakout confirmation: rel_vol >= 1.5 (+10), +5 if >=2.0 ----
    breakout_vol = pivot.get("breakout_rel_vol", 0.0) or 0.0
    if breakout_vol >= 1.5:
        r.score += 10
        r.criteria_met.append(f"breakout_vol_surge ({breakout_vol:.2f}x)")
    else:
        r.criteria_failed.append(f"breakout_vol_surge ({breakout_vol:.2f}x)")
    if breakout_vol >= 2.0:
        r.score += 5
        r.criteria_met.append("aplus_breakout_2x")

    # ---- A+ filter: breakout_close_upper_half ----
    try:
        pivot_bar = indic.loc[pivot_date]
        day_range = pivot_bar["high"] - pivot_bar["low"]
        if day_range > 0 and pd.notna(day_range):
            pos = (pivot_bar["close"] - pivot_bar["low"]) / day_range
            if pos >= 0.5:
                r.score += 5
                r.criteria_met.append(f"breakout_close_upper_half ({pos:.2f})")
            else:
                r.criteria_failed.append(f"breakout_close_upper_half ({pos:.2f})")
        else:
            r.criteria_failed.append("breakout_close_upper_half (no range)")
    except Exception:
        r.criteria_failed.append("breakout_close_upper_half (lookup error)")

    # ---- A+ filter: near_52w_high ----
    try:
        history = indic.loc[:pivot_date]
        if len(history) >= 60:
            rolling_hi = history["high"].iloc[-252:].max()
            pivot_close = indic.loc[pivot_date, "close"]
            if pd.notna(rolling_hi) and rolling_hi > 0:
                dist = (rolling_hi - pivot_close) / rolling_hi
                if dist <= 0.05:
                    r.score += 5
                    r.criteria_met.append(f"near_52w_high ({dist*100:.1f}% away)")
                else:
                    r.criteria_failed.append(f"near_52w_high ({dist*100:.1f}% away)")
            else:
                r.criteria_failed.append("near_52w_high (nan)")
    except Exception:
        r.criteria_failed.append("near_52w_high (lookup error)")

    # Cap score
    if r.score > 100:
        r.score = 100

    r.extra["contractions"] = [round(c, 4) for c in contractions]
    r.extra["base_len"] = base_len
    r.extra["prior_gain_pct"] = round(prior_gain * 100, 1)

    r.matched = (r.score >= 60) and has_contractions and final_tight
    return r
