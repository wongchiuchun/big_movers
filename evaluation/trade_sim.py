"""Trade-policy simulator: play every entry event forward under a grid of
stop x exit policies and record the realized R-multiple.

Numpy-first for speed: extract per-symbol arrays once (make_arrays), then each
event simulates all 28 policies on zero-copy slices.

Mechanics (deterministic, no lookahead):
  entry        = close of the event day
  initial stop = LOD (event-day low) | LOD_ATR (LOD with >=0.5*ATR20 room) |
                 ATR10 (entry - 1*ATR20) | SW10C (10-bar swing low, capped 1.5*ATR)
  R0           = entry - stop  (floored at 0.1% of entry)
  stop fill    = bar low < stop; fill at min(open, stop)  [gap-aware]
  MA exit      = bar CLOSES below the MA; fill at NEXT bar's open (last bar: that close)
  chandelier   = max(high so far through j-1) - 2.5*ATR20[j-1], ratcheted, >= initial stop
  breakeven    = once high >= entry + 1*R0, stop ratchets to entry from the NEXT bar
  partial      = 1/3 sold at entry + 3*R0 (only if fillable before/at-open-of exit bar);
                 remaining 2/3 follow the trail; trade R = weighted sum
  horizon      = 250 bars; mark-to-close, exit_reason='horizon'

Same-bar ties: a next-open MA fill executes before that bar's intraday stop;
an intraday stop beats the same bar's close-based signal.
"""
from __future__ import annotations

import numpy as np

HORIZON = 250
MIN_FWD_BARS = 5

STOPS = ["LOD", "LOD_ATR", "ATR10", "SW10C"]
EXITS = ["FIX", "E10", "E20", "E50", "CH25", "BE_E20", "P3_E20"]
MA_FOR_EXIT = {"E10": "ema10", "E20": "ema20", "E50": "sma50",
               "BE_E20": "ema20", "P3_E20": "ema20"}

ARRAY_COLS = ("open", "high", "low", "close", "atr_20", "ema10", "ema20", "sma50")


def make_arrays(ind) -> dict:
    """One-time numpy extraction for a symbol's indicator frame."""
    return {c: ind[c].to_numpy(float) for c in ARRAY_COLS}


def _first_true(mask: np.ndarray) -> int | None:
    idx = np.flatnonzero(mask)
    return int(idx[0]) if len(idx) else None


def _initial_stops(arr: dict, i: int) -> dict[str, float]:
    entry = arr["close"][i]
    lod = arr["low"][i]
    atr = arr["atr_20"][i]
    out: dict[str, float] = {}
    if lod < entry:
        out["LOD"] = lod
    if np.isfinite(atr):
        s = min(lod, entry - 0.5 * atr)
        if s < entry:
            out["LOD_ATR"] = s
        s = entry - 1.0 * atr
        if s < entry:
            out["ATR10"] = s
        s = max(arr["low"][max(0, i - 9): i + 1].min(), entry - 1.5 * atr)
        if s < entry:
            out["SW10C"] = s
    return out


def simulate_event(arr: dict, i: int) -> list[dict]:
    """All stop x exit policies for one event. Returns list of trade dicts."""
    n_total = len(arr["close"])
    entry = arr["close"][i]
    end = min(i + HORIZON, n_total - 1)
    n = end - i
    if n < MIN_FWD_BARS:
        return []
    sl = slice(i + 1, end + 1)
    o, h, l, c = arr["open"][sl], arr["high"][sl], arr["low"][sl], arr["close"][sl]
    atr = arr["atr_20"][sl]

    # MA close-below signals: computed once per event per MA column
    ma_exit: dict[str, tuple[int, float] | None] = {}
    for col in ("ema10", "ema20", "sma50"):
        ma = arr[col][sl]
        sig = _first_true((c < ma) & np.isfinite(ma))
        if sig is None:
            ma_exit[col] = None
        elif sig + 1 < n:
            ma_exit[col] = (sig + 1, float(o[sig + 1]))
        else:
            ma_exit[col] = (sig, float(c[sig]))

    # chandelier level path (independent of stop)
    run_hi = np.maximum.accumulate(np.concatenate(([entry], h)))[:-1]
    atr_prev = np.concatenate(([atr[0]], atr[:-1]))
    chand = np.maximum.accumulate(run_hi - 2.5 * atr_prev)

    stops = _initial_stops(arr, i)
    trades: list[dict] = []
    for sk, s0 in stops.items():
        r0 = max(entry - s0, entry * 0.001)
        be_hit = _first_true(h >= entry + 1.0 * r0)
        for ek in EXITS:
            # effective stop path
            if ek == "CH25":
                stop_path = np.maximum(s0, chand)
            elif ek in ("BE_E20", "P3_E20") and be_hit is not None and be_hit + 1 < n:
                stop_path = np.full(n, s0)
                stop_path[be_hit + 1:] = max(s0, entry)
            else:
                stop_path = np.full(n, s0)
            stop_hit = _first_true(l < stop_path)

            mx = ma_exit.get(MA_FOR_EXIT.get(ek, ""), None) if ek in MA_FOR_EXIT else None

            candidates = []
            if stop_hit is not None:
                candidates.append((stop_hit, 0, "stop",
                                   min(float(o[stop_hit]), float(stop_path[stop_hit]))))
            if mx is not None:
                candidates.append((mx[0], -1, "trail_ma", mx[1]))
            if candidates:
                candidates.sort(key=lambda t: (t[0], t[1]))
                exit_bar, _, reason, exit_px = candidates[0]
            else:
                exit_bar, reason, exit_px = n - 1, "horizon", float(c[-1])

            partial_filled = False
            if ek == "P3_E20":
                tgt = entry + 3.0 * r0
                tgt_hit = _first_true(h >= tgt)
                valid = tgt_hit is not None and (
                    tgt_hit < exit_bar or (tgt_hit == exit_bar and o[tgt_hit] >= tgt))
                if valid:
                    fill = float(o[tgt_hit]) if o[tgt_hit] >= tgt else tgt
                    r = (fill - entry) / r0 / 3.0 + 2.0 * ((exit_px - entry) / r0) / 3.0
                    partial_filled = True
                else:
                    r = (exit_px - entry) / r0
            else:
                r = (exit_px - entry) / r0

            trades.append({
                "stop": sk, "exit": ek, "entry": round(float(entry), 4),
                "s0": round(float(s0), 4), "risk_pct": round(float(r0 / entry * 100), 2),
                "r": round(float(r), 3), "days": int(exit_bar) + 1, "reason": reason,
                "partial_filled": partial_filled,
            })
    return trades
