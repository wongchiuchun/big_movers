"""Vault-informed momentum engine — point-in-time, live-tradeable, and
identical for winners and the control group.

Why a new engine instead of extending trade_sim.py
---------------------------------------------------
trade_sim.py only tests breakout-CLOSE entries with immediate MA-close exits,
and its freshness features (entry ordinal, extension) are defined relative to a
*labeled move*, which does not exist for control signals. This engine defines
EVERYTHING off the trailing 63-day low (exactly what big_mover_signals.pine
uses), so a signal is computed the same way whether or not the stock later
became a monster — which is what makes a fair control group possible.

It also adds the levers the old engine never had, drawn from the user's vault:
  * entry style  : "breakout" (close of trigger bar) | "pullback" (first tag of
                   the 10EMA within 10 bars after the trigger — Episodic-Pivot /
                   buy-the-first-pullback)
  * stop         : "SW" (structural swing low, capped 1.5*ATR — the contract's
                   structural stop) | "ATR" (1*ATR) | "LOD" (entry-day wick;
                   the one the contract says NOT to use, kept for contrast)
  * trail        : EMA10 / EMA20 / SMA50 close-below, with a configurable
                   min-hold (3 = the 3-bar / Thursday-squat shakeout guard)
  * free_roll    : trim half at +2R and move the remainder's stop to breakeven

Fill conventions match trade_sim.py exactly (gap-aware intraday stop at
min(open, stop); MA close-below fills NEXT open; next-open MA fill beats the same
bar's intraday stop).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GAP_MIN_PCT = 5.0
GAP_MIN_RELVOL = 1.5
BREAKOUT_COOLDOWN = 5
HORIZON = 250
LOW_LOOKBACK = 63
PULLBACK_WINDOW = 10
MIN_FWD_BARS = 5

ARRAY_COLS = ("open", "high", "low", "close", "atr_20", "ema10", "ema20",
              "ema50", "sma50")


def make_arrays(ind: pd.DataFrame) -> dict:
    out = {c: ind[c].to_numpy(float) for c in ARRAY_COLS if c in ind}
    if "ema50" not in out:
        out["ema50"] = ind["close"].ewm(span=50, adjust=False).mean().to_numpy(float)
    return out


# ---------- point-in-time signals & features (off the 63-day low) ----------

def signal_bars(ind: pd.DataFrame) -> dict:
    """Return per-bar arrays needed to decide entries, all point-in-time."""
    high, low, close = ind["high"], ind["low"], ind["close"]
    vol = ind["volume"]
    prior20 = high.rolling(20).max().shift(1)
    prior50 = high.rolling(50).max().shift(1)
    above20 = (close > prior20)
    above50 = (close > prior50)
    relvol20 = (vol / vol.rolling(20).mean())
    gap = (ind["open"] - close.shift(1)) / close.shift(1) * 100
    gap_sig = (gap >= GAP_MIN_PCT) & (relvol20 >= GAP_MIN_RELVOL)

    def cross(a):
        return (a & ~a.shift(1, fill_value=False))

    br20 = cross(above20)
    br50 = cross(above50)
    raw = (br20 | br50 | gap_sig)

    lo63 = low.rolling(LOW_LOOKBACK).min()
    ext = (close / lo63 - 1) * 100
    return {
        "raw": raw.to_numpy(bool),
        "br50": br50.to_numpy(bool),
        "gap": gap_sig.to_numpy(bool),
        "ext": ext.to_numpy(float),
        "relvol20": relvol20.to_numpy(float),
        "adr": ind["adr_pct_20"].to_numpy(float) if "adr_pct_20" in ind else np.full(len(ind), np.nan),
        "dolvol_m": (ind["close"] * ind["volume"]).rolling(20).mean().to_numpy(float) / 1e6,
    }


def entries_since_low(raw: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Ordinal of each raw signal since the trailing 63-day low (1-based).

    Vectorised: the index of the rolling-63 low via a sliding-window argmin,
    then raw-signal count between that low and the current bar."""
    from numpy.lib.stride_tricks import sliding_window_view

    n = len(raw)
    cum = np.cumsum(raw.astype(int))
    low_idx = np.empty(n, dtype=int)
    ramp = min(n, LOW_LOOKBACK - 1)
    for i in range(ramp):                       # first <63 bars: argmin over [0:i+1]
        low_idx[i] = int(np.argmin(low[:i + 1]))
    if n >= LOW_LOOKBACK:
        win = sliding_window_view(low, LOW_LOOKBACK)        # (n-62, 63)
        am = win.argmin(axis=1)
        starts = np.arange(n - LOW_LOOKBACK + 1)
        low_idx[LOW_LOOKBACK - 1:] = starts + am
    prior = np.where(low_idx >= 1, cum[np.maximum(low_idx - 1, 0)], 0)
    return cum - prior


# ---------- single-trade simulation ----------

def _first(mask: np.ndarray):
    idx = np.flatnonzero(mask)
    return int(idx[0]) if len(idx) else None


def _stop_level(arr: dict, i: int, mode: str) -> float | None:
    entry, lod, atr = arr["close"][i], arr["low"][i], arr["atr_20"][i]
    if mode == "LOD":
        return lod if lod < entry else None
    if not np.isfinite(atr):
        return None
    if mode == "ATR":
        s = entry - 1.0 * atr
    elif mode == "SW":
        s = max(arr["low"][max(0, i - 9): i + 1].min(), entry - 1.5 * atr)
    else:
        raise ValueError(mode)
    return s if s < entry else None


def run_trade(arr: dict, i: int, trail: str, min_hold: int, stop_mode: str,
              free_roll: bool) -> dict | None:
    """Simulate one entry at bar i. Returns {r, days} or None if untradeable."""
    entry = arr["close"][i]
    n_total = len(arr["close"])
    end = min(i + HORIZON, n_total - 1)
    n = end - i
    if n < MIN_FWD_BARS:
        return None
    s0 = _stop_level(arr, i, stop_mode)
    if s0 is None:
        return None
    r0 = max(entry - s0, entry * 0.001)
    sl = slice(i + 1, end + 1)
    o, h, l, c = arr["open"][sl], arr["high"][sl], arr["low"][sl], arr["close"][sl]
    ma = arr[trail][sl]

    # MA close-below signal, respecting the min-hold shakeout guard
    sig = np.flatnonzero((c < ma) & np.isfinite(ma))
    sig = sig[sig >= min_hold]
    if len(sig):
        s = int(sig[0])
        ma_bar, ma_px = (s + 1, float(o[s + 1])) if s + 1 < n else (s, float(c[s]))
    else:
        ma_bar = ma_px = None

    # stop path (breakeven ratchet if free_roll and +2R tagged)
    stop_path = np.full(n, s0)
    two_r = _first(h >= entry + 2.0 * r0) if free_roll else None
    if two_r is not None and two_r + 1 < n:
        stop_path[two_r + 1:] = max(s0, entry)
    stop_hit = _first(l < stop_path)

    cands = []
    if stop_hit is not None:
        cands.append((stop_hit, 0, min(float(o[stop_hit]), float(stop_path[stop_hit]))))
    if ma_bar is not None:
        cands.append((ma_bar, -1, ma_px))
    if cands:
        cands.sort(key=lambda t: (t[0], t[1]))
        eb, _, px = cands[0]
    else:
        eb, px = n - 1, float(c[-1])

    if free_roll and two_r is not None and two_r <= eb:
        # half off at +2R, remainder exits at px
        r = 0.5 * 2.0 + 0.5 * ((px - entry) / r0)
    else:
        r = (px - entry) / r0
    return {"r": float(r), "days": int(eb) + 1}


def find_entry(arr: dict, t: int, style: str) -> int | None:
    """Map a trigger bar t to the actual entry bar given the entry style."""
    if style == "breakout":
        return t
    if style == "pullback":
        # first bar within the next PULLBACK_WINDOW that tags the 10EMA and
        # closes back above it (buy-the-first-pullback). None if it runs away.
        end = min(t + PULLBACK_WINDOW, len(arr["close"]) - 1)
        for j in range(t + 1, end + 1):
            if arr["low"][j] <= arr["ema10"][j] and arr["close"][j] >= arr["ema10"][j]:
                return j
        return None
    raise ValueError(style)
