"""Point-in-time feature extraction anchored on deterministic events.

Design rule (the fix for the old "messy setup boundaries" problem):
every metric is f(symbol, event_date, fixed_window) — never f(fuzzy region).

Events per move (within low_date..high_date):
  move_start   first bar of the move (low_date)
  breakout20   close crosses above the prior 20-day high (cooldown 5 bars)
  breakout50   close crosses above the prior 50-day high (cooldown 5 bars)
  gap          open gap >=5% on >=1.5x 20d avg volume (canonical analyze_move rule)

Trailing features are as-of the event close (no future data). Forward metrics
deliberately look forward — they measure outcome/holdability, not entry signal.

Move-level metrics replicate tools/analyze_move.py window_stats exactly so they
can be validated against ANNOTATION_TRACKER.md numbers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GAP_MIN_PCT = 5.0
GAP_MIN_RELVOL = 1.5
BREAKOUT_COOLDOWN = 5
FWD_WINDOW = 60
TOUCH_BAND = 0.03  # |close-sma50|/sma50 < 3% counts as a touch (analyze_move convention)


# ---------- per-symbol indicator frame ----------

def enrich(ind: pd.DataFrame) -> pd.DataFrame:
    """Add study columns on top of classifier.indicators.compute_all_indicators output."""
    out = ind.copy()
    out["prior20high"] = out["high"].rolling(20).max().shift(1)
    out["prior50high"] = out["high"].rolling(50).max().shift(1)
    out["hi252"] = out["high"].rolling(252, min_periods=60).max()
    out["lo252"] = out["low"].rolling(252, min_periods=60).min()
    out["avg_vol_20"] = out["volume"].rolling(20).mean()
    out["rel_vol_20"] = out["volume"] / out["avg_vol_20"]
    out["dollar_vol_20"] = (out["close"] * out["volume"]).rolling(20).mean()
    out["sma200_rising"] = out["sma200"] > out["sma200"].shift(21)
    prev_close = out["close"].shift(1)
    out["gap_pct"] = (out["open"] - prev_close) / prev_close * 100
    rng = out["high"] - out["low"]
    out["close_in_range"] = np.where(rng > 0, (out["close"] - out["low"]) / rng * 100, 50.0)
    return out


# ---------- event detection ----------

def _cross_events(above: pd.Series, lo: int, hi: int) -> list[int]:
    """Indices in [lo, hi] where `above` flips False->True, with cooldown."""
    flips = above & ~above.shift(1, fill_value=False)
    idxs = [i for i in np.flatnonzero(flips.to_numpy()) if lo <= i <= hi]
    kept: list[int] = []
    for i in idxs:
        if not kept or i - kept[-1] > BREAKOUT_COOLDOWN:
            kept.append(i)
    return kept


def detect_events(ind: pd.DataFrame, lo: int, hi: int) -> list[tuple[int, str]]:
    """Return [(bar_idx, event_type)] within the move window, sorted."""
    events: list[tuple[int, str]] = [(lo, "move_start")]
    above20 = ind["close"] > ind["prior20high"]
    above50 = ind["close"] > ind["prior50high"]
    for i in _cross_events(above20, lo, hi):
        events.append((i, "breakout20"))
    for i in _cross_events(above50, lo, hi):
        events.append((i, "breakout50"))
    gap_mask = (ind["gap_pct"] >= GAP_MIN_PCT) & (
        ind["volume"] / ind["volume"].rolling(20).mean() >= GAP_MIN_RELVOL
    )
    for i in np.flatnonzero(gap_mask.to_numpy()):
        if lo <= i <= hi:
            events.append((int(i), "gap"))
    events.sort()
    return events


# ---------- trailing (point-in-time) features ----------

def trailing_features(ind: pd.DataFrame, i: int, spy: pd.DataFrame | None) -> dict:
    row = ind.iloc[i]
    close = row["close"]
    f: dict = {
        "close": round(float(close), 4),
        "event_gap_pct": _r(row["gap_pct"]),
        "event_rel_vol": _r(row["rel_vol"]),       # vs 50d avg (classifier convention)
        "event_rel_vol20": _r(row["rel_vol_20"]),  # vs 20d avg (analyze_move convention)
        "close_in_range": _r(row["close_in_range"]),
        "adr_pct_20": _r(row["adr_pct_20"]),
        "dollar_vol_20m": _r(row["dollar_vol_20"] / 1e6),
        "rs_63d": _r(row.get("rs_vs_spy_63d")),
    }
    # trend / stack state
    f["above_sma50"] = _b(close > row["sma50"])
    f["above_sma200"] = _b(close > row["sma200"])
    f["ema_stack_bull"] = _b(
        (row["ema10"] > row["ema20"]) and (row["ema20"] > row["sma50"]) and (close > row["sma50"])
    )
    f["trend_template"] = _b(
        (close > row["sma50"]) and (row["sma50"] > row["sma150"]) and
        (row["sma150"] > row["sma200"]) and bool(row["sma200_rising"])
    )
    f["pct_off_52wk_high"] = _r((close - row["hi252"]) / row["hi252"] * 100)
    f["pct_above_52wk_low"] = _r((close - row["lo252"]) / row["lo252"] * 100)
    # prior momentum
    for name, n in (("prior_gain_1m", 21), ("prior_gain_3m", 63), ("prior_gain_6m", 126)):
        f[name] = _r(close / ind["close"].iloc[i - n] * 100 - 100) if i >= n else None
    # trailing adherence / touch counts (fixed 60-bar window)
    w = ind.iloc[max(0, i - 59): i + 1]
    f["trail60_ema10_adh"] = _r((w["close"] >= w["ema10"]).mean() * 100)
    f["trail60_sma50_touches"] = int((abs(w["close"] - w["sma50"]) / w["sma50"] < TOUCH_BAND).sum())
    # consolidation proxies (fixed windows, no base detection)
    if i >= 20:
        c10 = ind["close"].iloc[i - 9: i + 1]
        f["tightness_10"] = _r(c10.std() / c10.mean() * 100)
        hi20 = ind["high"].iloc[i - 19: i + 1]
        lo20 = ind["low"].iloc[i - 19: i + 1]
        f["depth_20"] = _r((hi20.max() - lo20.min()) / hi20.max() * 100)
        r5 = ind["high"].iloc[i - 4: i + 1].max() - ind["low"].iloc[i - 4: i + 1].min()
        r15 = ind["high"].iloc[i - 19: i - 4].max() - ind["low"].iloc[i - 19: i - 4].min()
        f["contraction_5v15"] = _r(r5 / r15) if r15 > 0 else None
    else:
        f["tightness_10"] = f["depth_20"] = f["contraction_5v15"] = None
    # market regime at event date
    if spy is not None:
        s = spy[spy.index <= ind.index[i]]
        if len(s):
            srow = s.iloc[-1]
            f["spy_above_50sma"] = _b(srow["close"] > srow["sma50"]) if pd.notna(srow["sma50"]) else None
            f["spy_above_200sma"] = _b(srow["close"] > srow["sma200"]) if pd.notna(srow["sma200"]) else None
    return f


# ---------- forward (outcome) metrics ----------

def forward_metrics(ind: pd.DataFrame, i: int) -> dict:
    entry = float(ind["close"].iloc[i])
    lod = float(ind["low"].iloc[i])
    end = min(i + FWD_WINDOW, len(ind) - 1)
    fwd = ind.iloc[i + 1: end + 1]
    f: dict = {"fwd_bars": len(fwd)}
    if len(fwd) == 0:
        return f
    closes, lows, highs = fwd["close"], fwd["low"], fwd["high"]
    for n in (5, 10, 20, 60):
        f[f"fwd_ret_{n}"] = _r(closes.iloc[n - 1] / entry * 100 - 100) if len(fwd) >= n else None
    f["fwd_mfe_60"] = _r(highs.max() / entry * 100 - 100)
    f["fwd_mae_60"] = _r(lows.min() / entry * 100 - 100)
    # LOD stop survival (Qullamaggie-style stop at event-day low)
    risk = max(entry - lod, entry * 0.001)
    undercut = lows < lod
    first_stop = int(np.argmax(undercut.to_numpy())) if undercut.any() else None
    f["lod_stop_survives_20"] = _b(not undercut.iloc[:20].any()) if len(fwd) >= 20 else None
    hit_2r = highs >= entry + 2 * risk
    first_2r = int(np.argmax(hit_2r.to_numpy())) if hit_2r.any() else None
    if first_2r is not None and (first_stop is None or first_2r < first_stop):
        f["reach_2r_before_stop"] = True
    elif first_stop is not None:
        f["reach_2r_before_stop"] = False
    else:
        f["reach_2r_before_stop"] = None  # neither within window
    # forward holdability
    f["fwd_ema10_adh_60"] = _r((closes >= fwd["ema10"]).mean() * 100)
    rh = closes.cummax()
    f["fwd_max_dd_60"] = _r(((lows - rh) / rh).min() * 100)
    return f


# ---------- move-level metrics (analyze_move.py window_stats parity) ----------

def move_metrics(ind: pd.DataFrame, lo: int, hi: int) -> dict:
    w = ind.iloc[lo: hi + 1]
    if len(w) == 0:
        return {}
    e10 = (w["close"] >= w["ema10"]).mean() * 100
    e20 = (w["close"] >= w["ema20"]).mean() * 100
    t50 = int((abs(w["close"] - w["sma50"]) / w["sma50"] < TOUCH_BAND).sum())
    below_50 = int((w["close"] < w["sma50"]).sum())
    rh = w["close"].cummax()
    dd = ((w["low"] - rh) / rh).min() * 100
    u10 = int(((w["low"] - rh) / rh < -0.1).sum())
    adr = w["adr_pct_20"].mean()
    return {
        "days": len(w),
        "ema10_adh": _r(e10),
        "ema20_adh": _r(e20),
        "sma50_touches": t50,
        "days_below_50": below_50,
        "worst_dd_pct": _r(dd),
        "pct_days_u10": _r(u10 / len(w) * 100),
        "adr_mean": _r(adr),
    }


def _r(v, nd=2):
    try:
        if v is None or (isinstance(v, float) and not np.isfinite(v)) or pd.isna(v):
            return None
    except (TypeError, ValueError):
        return None
    return round(float(v), nd)


def _b(v):
    if v is None:
        return None
    return bool(v)
