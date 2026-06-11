"""Faithful Python port of "Machine Learning Adaptive SuperTrend [AlgoAlpha]"
(superalt.md): SuperTrend(hl2, factor=3) whose ATR input is the centroid of the
current bar's k-means volatility cluster (3 clusters, trailing 100 ATR values,
initial centroids at the 25/50/75 percentile points of the window's range).

Pine specifics preserved:
  - ta.atr(10) is RMA (Wilder) smoothed true range
  - k-means window INCLUDES the current bar; iterates until centroids stop
    changing (empty cluster keeps its previous centroid)
  - cluster assignment of the current bar: nearest of [high, mid, low] centroid,
    first-match priority on ties
  - pine_supertrend band ratchet + direction logic ported line-for-line;
    dir == -1 means UPtrend (ST is the lower band)
  - bullish flip = dir transitions +1 -> -1 (close crossed above upper band)

simulate_superalt_trades(): long on bullish flip close, exit at the first
bearish flip (fill next open, same convention as the strategy's MA exits),
initial risk R0 = entry - SuperTrend line at entry (the system's natural stop).
"""
from __future__ import annotations

import numpy as np

ATR_LEN = 10
FACTOR = 3.0
TRAIN = 100
KMEANS_MAX_ITER = 50
HORIZON = 250


def rma_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = ATR_LEN) -> np.ndarray:
    prev_close = np.concatenate(([np.nan], close[:-1]))
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]
    out = np.empty_like(tr)
    alpha = 1.0 / n
    out[0] = tr[0]
    for i in range(1, len(tr)):
        out[i] = out[i - 1] + alpha * (tr[i] - out[i - 1])
    return out


def adaptive_atr(vol: np.ndarray) -> np.ndarray:
    """Per-bar k-means(3) over the trailing TRAIN window of ATR values.
    Returns the assigned centroid per bar (nan before warmup)."""
    n = len(vol)
    out = np.full(n, np.nan)
    if n < TRAIN:
        return out
    win = np.lib.stride_tricks.sliding_window_view(vol, TRAIN)  # (m, TRAIN), ends at bar t
    m = len(win)
    w_hi = win.max(axis=1)
    w_lo = win.min(axis=1)
    cent = np.stack([w_lo + (w_hi - w_lo) * q for q in (0.75, 0.50, 0.25)], axis=1)  # (m,3)

    active = np.ones(m, dtype=bool)
    for _ in range(KMEANS_MAX_ITER):
        if not active.any():
            break
        d = np.abs(win[active, None, :] - cent[active, :, None])      # (a,3,TRAIN)
        assign = np.argmin(d, axis=1)                                  # (a,TRAIN)
        new = cent[active].copy()
        for k in range(3):
            mask = assign == k
            cnt = mask.sum(axis=1)
            s = np.where(mask, win[active], 0.0).sum(axis=1)
            nonempty = cnt > 0
            new[nonempty, k] = s[nonempty] / cnt[nonempty]
        changed = ~np.all(np.isclose(new, cent[active], rtol=0, atol=1e-12), axis=1)
        cent[active] = new
        idx = np.flatnonzero(active)
        active[idx[~changed]] = False

    cur = win[:, -1]
    pick = np.argmin(np.abs(cur[:, None] - cent), axis=1)
    out[TRAIN - 1:] = cent[np.arange(m), pick]
    return out


def pine_supertrend(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                    atr_c: np.ndarray, factor: float = FACTOR) -> tuple[np.ndarray, np.ndarray]:
    """Returns (supertrend_line, direction). dir == -1 -> uptrend."""
    n = len(close)
    src = (high + low) / 2.0
    st = np.full(n, np.nan)
    direction = np.full(n, 1, dtype=int)
    prev_lower, prev_upper = np.nan, np.nan
    prev_st = np.nan
    for i in range(n):
        a = atr_c[i]
        if not np.isfinite(a):
            prev_lower, prev_upper, prev_st = np.nan, np.nan, np.nan
            direction[i] = 1
            continue
        upper = src[i] + factor * a
        lower = src[i] - factor * a
        pl = prev_lower if np.isfinite(prev_lower) else 0.0
        pu = prev_upper if np.isfinite(prev_upper) else 0.0
        if not (lower > pl or (i > 0 and close[i - 1] < pl)):
            lower = pl
        if not (upper < pu or (i > 0 and close[i - 1] > pu)):
            upper = pu
        if not np.isfinite(prev_st) or (i > 0 and not np.isfinite(atr_c[i - 1])):
            d = 1
        elif prev_st == pu:
            d = -1 if close[i] > upper else 1
        else:
            d = 1 if close[i] < lower else -1
        st[i] = lower if d == -1 else upper
        direction[i] = d
        prev_lower, prev_upper, prev_st = lower, upper, st[i]
    return st, direction


def compute_superalt(arr: dict) -> dict:
    """arr: dict of numpy arrays with open/high/low/close. Adds st/dir/flips."""
    vol = rma_atr(arr["high"], arr["low"], arr["close"])
    atr_c = adaptive_atr(vol)
    st, direction = pine_supertrend(arr["high"], arr["low"], arr["close"], atr_c)
    bull_flip = np.zeros(len(st), dtype=bool)
    bear_flip = np.zeros(len(st), dtype=bool)
    bull_flip[1:] = (direction[1:] == -1) & (direction[:-1] == 1)
    bear_flip[1:] = (direction[1:] == 1) & (direction[:-1] == -1)
    return {"st": st, "dir": direction, "bull_flip": bull_flip, "bear_flip": bear_flip}


def superalt_exit_after(sa: dict, arr: dict, i: int) -> tuple[int, float, str]:
    """First bearish flip strictly after bar i -> fill next open (last bar: close).
    Returns (exit_bar_abs, exit_px, reason)."""
    n = len(arr["close"])
    end = min(i + HORIZON, n - 1)
    flips = np.flatnonzero(sa["bear_flip"][i + 1: end + 1])
    if len(flips) == 0:
        return end, float(arr["close"][end]), "horizon"
    j = i + 1 + int(flips[0])
    if j + 1 <= end:
        return j + 1, float(arr["open"][j + 1]), "sa_flip"
    return j, float(arr["close"][j]), "sa_flip"


def simulate_superalt_trade(sa: dict, arr: dict, i: int) -> dict | None:
    """Full SuperAlt system trade from a bullish flip at bar i."""
    entry = float(arr["close"][i])
    s0 = float(sa["st"][i])
    if not np.isfinite(s0) or s0 >= entry:
        return None
    r0 = max(entry - s0, entry * 0.001)
    exit_bar, exit_px, reason = superalt_exit_after(sa, arr, i)
    return {
        "entry": round(entry, 4), "s0": round(s0, 4),
        "risk_pct": round(r0 / entry * 100, 2),
        "r": round((exit_px - entry) / r0, 3),
        "days": int(exit_bar - i), "reason": reason,
    }
