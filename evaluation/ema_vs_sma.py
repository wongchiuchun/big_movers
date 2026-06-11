"""Does switching the trailing exit from SMA-50 to an EMA help?

Tests the strategy's filtered entries (ADR 4-8%, >=$5M, fresh: <=3 signals since
63d low, <50% extended, >=1.5x vol, SPY>50SMA) exited on a close below each of:
  SMA50, EMA50, EMA20, EMA10  -- with the Consistency stop (swing low, 1.5*ATR cap).

Same fill conventions as trade_sim: MA close-below fills next open; intraday stop
fills min(open, stop); next-open MA fill beats the same bar's intraday stop.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.ema_vs_sma
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classifier.indicators import compute_all_indicators, load_spy_benchmark, load_ticker_bars
from evaluation.extract import detect_events, enrich
from evaluation.run_trade_sim import EVENT_PRIORITY
from evaluation.trade_sim import make_arrays

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HORIZON = 250


def trade(arr, ma, i, stop):
    """One trade: entry close[i], Consistency stop, exit on close<ma (next open)."""
    entry = arr["close"][i]
    n_total = len(arr["close"])
    end = min(i + HORIZON, n_total - 1)
    n = end - i
    if n < 5 or stop >= entry:
        return None
    r0 = max(entry - stop, entry * 0.001)
    o = arr["open"][i + 1:end + 1]
    l = arr["low"][i + 1:end + 1]
    c = arr["close"][i + 1:end + 1]
    m = ma[i + 1:end + 1]
    stop_hit = np.flatnonzero(l < stop)
    sig = np.flatnonzero((c < m) & np.isfinite(m))
    ma_bar = (sig[0] + 1) if len(sig) and sig[0] + 1 < n else (sig[0] if len(sig) else None)
    ma_px = (float(o[sig[0] + 1]) if len(sig) and sig[0] + 1 < n
             else (float(c[sig[0]]) if len(sig) else None))
    cands = []
    if len(stop_hit):
        cands.append((stop_hit[0], 0, min(float(o[stop_hit[0]]), stop)))
    if ma_bar is not None:
        cands.append((ma_bar, -1, ma_px))
    if cands:
        cands.sort(key=lambda t: (t[0], t[1]))
        eb, _, px = cands[0]
    else:
        eb, px = n - 1, float(c[-1])
    return {"r": (px - entry) / r0, "days": int(eb) + 1, "year": None}


def stats(rs, days):
    rs = np.array(rs, float)
    if len(rs) == 0:
        return {}
    cap = np.quantile(rs, 0.99)
    return {"n": len(rs), "win%": round((rs > 0).mean() * 100, 1),
            "avgR": round(rs.mean(), 2), "avgRw99": round(np.minimum(rs, cap).mean(), 2),
            "medR": round(float(np.median(rs)), 2),
            "R/30d": round(rs.mean() / max(np.mean(days), 1) * 30, 2)}


def main():
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))
    spy["sma50"] = spy["close"].rolling(50).mean()
    spy_up = dict(zip(spy.index, (spy["close"] > spy["sma50"]).where(spy["sma50"].notna(), None)))

    mas = ["sma50", "ema50", "ema20", "ema10"]
    acc = {m: {"r": [], "d": [], "yr": []} for m in mas}
    cache = {}

    for row in results.itertuples(index=False):
        symbol, year = str(row.symbol), int(row.year)
        if symbol not in cache:
            try:
                ind = enrich(compute_all_indicators(load_ticker_bars(symbol, os.path.join(ROOT, "collected_stocks")), benchmark=spy))
                ind["ema50"] = ind["close"].ewm(span=50, adjust=False).mean()
                a = make_arrays(ind)
                a["ema50"] = ind["ema50"].to_numpy(float)
                cache[symbol] = (ind, a)
            except Exception:
                cache[symbol] = None
        if cache[symbol] is None:
            continue
        ind, arr = cache[symbol]
        lo = int(ind.index.searchsorted(pd.Timestamp(row.low_date)))
        hi = int(ind.index.searchsorted(pd.Timestamp(row.high_date), side="right")) - 1
        if lo >= len(ind) or hi <= lo:
            continue
        events = [(i, et) for i, et in detect_events(ind, lo, hi) if et != "move_start"]
        by_day = {}
        for i, et in events:
            if i not in by_day or EVENT_PRIORITY[et] < EVENT_PRIORITY[by_day[i]]:
                by_day[i] = et
        first_close = arr["close"][lo]
        ordinal = 0
        for i in sorted(by_day):
            ordinal += 1
            # universe + freshness filter
            adr = ind["adr_pct_20"].iloc[i]
            dvol = ind["dollar_vol_20"].iloc[i] / 1e6
            relv = ind["rel_vol_20"].iloc[i]
            ext = arr["close"][i] / first_close * 100 - 100
            up = spy_up.get(ind.index[i], None)
            if not (np.isfinite(adr) and 4 <= adr <= 8 and np.isfinite(dvol) and dvol >= 5):
                continue
            if not (ordinal <= 3 and ext < 50 and np.isfinite(relv) and relv >= 1.5 and up is True):
                continue
            atr = ind["atr_20"].iloc[i]
            if not np.isfinite(atr):
                continue
            stop = max(float(arr["low"][max(0, i - 9):i + 1].min()), arr["close"][i] - 1.5 * atr)
            for m in mas:
                t = trade(arr, arr[m], i, stop)
                if t:
                    acc[m]["r"].append(t["r"]); acc[m]["d"].append(t["days"]); acc[m]["yr"].append(year)

    print(f"{'exit MA':10} {'n':>4} {'win%':>6} {'avgR':>6} {'avgRw99':>8} {'medR':>6} {'R/30d':>6} {'yrStd':>6} {'negYrs':>7}")
    for m in mas:
        s = stats(acc[m]["r"], acc[m]["d"])
        df = pd.DataFrame({"r": acc[m]["r"], "yr": acc[m]["yr"]})
        yr = df.groupby("yr")["r"].mean()
        yr3 = df.groupby("yr").filter(lambda g: len(g) >= 3).groupby("yr")["r"].mean()
        ystd = round(yr3.std(), 2) if len(yr3) > 1 else None
        neg = f"{int((yr3 <= 0).sum())}/{len(yr3)}"
        print(f"{m:10} {s['n']:4} {s['win%']:5}% {s['avgR']:6} {s['avgRw99']:8} {s['medR']:6} {s['R/30d']:6} {ystd!s:>6} {neg:>7}")


if __name__ == "__main__":
    main()
