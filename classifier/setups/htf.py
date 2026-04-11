"""High Tight Flag / Power Play detector.

Implements §3.5 of the setup classification reference. The base is the
flag; the window preceding it must contain a ≥100% gain within 4–8 weeks
(pole). Flag must be ≤25% deep with volume drying up vs the pole.
"""
from __future__ import annotations

import pandas as pd

from classifier.setups import DetectorResult


def detect_htf(indic: pd.DataFrame, pivot: dict) -> DetectorResult:
    r = DetectorResult(setup="HTF", matched=False)
    if pivot is None:
        r.criteria_failed.append("no_pivot")
        return r

    base_start = pivot["base_start"]
    base_end = pivot["base_end"]

    try:
        flag = indic.loc[base_start:base_end]
    except Exception:
        r.criteria_failed.append("flag_slice_error")
        return r
    if flag.empty:
        r.criteria_failed.append("empty_flag")
        return r

    flag_start_close = flag["close"].iloc[0]
    if pd.isna(flag_start_close) or flag_start_close <= 0:
        r.criteria_failed.append("flag_start_nan")
        return r

    # ---- Search for pole: 100%+ gain in 20/30/40 bars before flag ----
    prior_all = indic.loc[:base_start].iloc[:-1]
    if len(prior_all) < 20:
        r.criteria_failed.append("insufficient_pole_history")
        return r

    best_gain = 0.0
    best_pole_len = None
    best_pole_start_date = None

    for pole_len in (20, 30, 40):
        if len(prior_all) < pole_len:
            continue
        pole_slice = prior_all.iloc[-pole_len:]
        pole_start_close = pole_slice["close"].iloc[0]
        if pd.isna(pole_start_close) or pole_start_close <= 0:
            continue
        gain = (flag_start_close / pole_start_close) - 1.0
        if gain > best_gain:
            best_gain = gain
            best_pole_len = pole_len
            best_pole_start_date = pole_slice.index[0]

    pole_100 = best_gain >= 1.00
    if pole_100:
        r.score += 30  # treat as prereq "+30 gate"
        r.criteria_met.append(f"pole_100_in_4_8w ({best_gain*100:.0f}% in {best_pole_len}d)")
    else:
        r.criteria_failed.append(f"pole_100_in_4_8w (best {best_gain*100:.0f}%)")
        return r  # hard fail — HTF without a pole isn't HTF

    # ---- Flag depth 25 (critical) ----
    depth_pct = pivot.get("base_depth_pct", 100.0)
    flag_depth_25 = depth_pct <= 25.0
    if flag_depth_25:
        r.score += 10
        r.criteria_met.append(f"flag_depth_25 ({depth_pct:.1f}%)")
    else:
        r.criteria_failed.append(f"flag_depth_25 ({depth_pct:.1f}%)")

    # ---- Flag volume contraction vs pole ----
    try:
        pole_slice_final = prior_all.iloc[-best_pole_len:]
        pole_avg_vol = pole_slice_final["volume"].mean()
        flag_avg_vol = flag["volume"].mean()
        if pd.notna(pole_avg_vol) and pole_avg_vol > 0 and pd.notna(flag_avg_vol):
            if flag_avg_vol < pole_avg_vol * 0.6:
                r.score += 10
                r.criteria_met.append("flag_volume_contraction")
            else:
                r.criteria_failed.append(
                    f"flag_volume_contraction (flag {flag_avg_vol:.0f} vs pole {pole_avg_vol:.0f})"
                )
        else:
            r.criteria_failed.append("flag_volume_contraction (nan)")
    except Exception:
        r.criteria_failed.append("flag_volume_contraction (error)")

    # ---- Breakout vol 1.4x ----
    breakout_vol = pivot.get("breakout_rel_vol", 0.0) or 0.0
    if breakout_vol >= 1.4:
        r.score += 10
        r.criteria_met.append(f"breakout_vol_14x ({breakout_vol:.2f}x)")
    else:
        r.criteria_failed.append(f"breakout_vol_14x ({breakout_vol:.2f}x)")

    # ---- A+ filter: flag_depth_15 ----
    if depth_pct <= 15.0:
        r.score += 5
        r.criteria_met.append("aplus_flag_depth_15")

    # ---- A+ filter: pole_100 in ≤6 weeks (<=30 bars) ----
    if best_pole_len is not None and best_pole_len <= 30:
        r.score += 5
        r.criteria_met.append("aplus_pole_100_6w")

    # Cap score
    if r.score > 100:
        r.score = 100

    r.extra["pole_gain_pct"] = round(best_gain * 100, 1)
    r.extra["pole_len"] = best_pole_len
    r.extra["pole_start"] = (
        str(best_pole_start_date.date())
        if best_pole_start_date is not None and hasattr(best_pole_start_date, "date")
        else None
    )
    r.extra["flag_len"] = len(flag)
    r.extra["flag_depth_pct"] = depth_pct

    r.matched = (r.score >= 60) and pole_100 and flag_depth_25
    return r
