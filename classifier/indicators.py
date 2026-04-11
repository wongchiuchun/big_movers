"""Technical indicator computations for setup classification.

All functions return a new DataFrame (do not mutate input). The canonical
entry point is `compute_all_indicators(bars, benchmark=spy)`.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def add_moving_averages(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    out["sma50"] = out["close"].rolling(50).mean()
    out["sma150"] = out["close"].rolling(150).mean()
    out["sma200"] = out["close"].rolling(200).mean()
    out["ema10"] = out["close"].ewm(span=10, adjust=False).mean()
    out["ema20"] = out["close"].ewm(span=20, adjust=False).mean()
    return out


def add_volume_baseline(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    out["avg_vol_50"] = out["volume"].rolling(50).mean()
    out["rel_vol"] = out["volume"] / out["avg_vol_50"]
    return out


def add_adr_pct_20(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    daily_range_pct = (out["high"] - out["low"]) / out["close"] * 100
    out["adr_pct_20"] = daily_range_pct.rolling(20).mean()
    return out


def add_atr_20(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    prev_close = out["close"].shift(1)
    tr1 = out["high"] - out["low"]
    tr2 = (out["high"] - prev_close).abs()
    tr3 = (out["low"] - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["atr_20"] = true_range.rolling(20).mean()
    return out


def add_rs_vs_benchmark_63d(bars: pd.DataFrame, benchmark: pd.DataFrame) -> pd.DataFrame:
    """63-day return ratio vs benchmark. >1 = outperforming."""
    out = bars.copy()
    bench_aligned = benchmark["close"].reindex(out.index, method="ffill")
    stock_ret = out["close"] / out["close"].shift(63)
    bench_ret = bench_aligned / bench_aligned.shift(63)
    out["rs_vs_spy_63d"] = stock_ret / bench_ret
    return out


def detect_swings(bars: pd.DataFrame, lookback: int = 3) -> list[dict]:
    """Fractal swing detector: bar[i] is a swing high if its high strictly
    exceeds every bar in [i-lookback, i-1] and [i+1, i+lookback]. Symmetric
    for swing lows. Consecutive same-kind swings are collapsed to the more
    extreme one.
    """
    if len(bars) < 2 * lookback + 1:
        return []
    highs = bars["high"].to_numpy()
    lows = bars["low"].to_numpy()
    n = len(bars)
    raw: list[dict] = []
    for i in range(lookback, n - lookback):
        left_hi = highs[i - lookback : i].max()
        right_hi = highs[i + 1 : i + lookback + 1].max()
        if highs[i] > left_hi and highs[i] > right_hi:
            raw.append({
                "idx": i,
                "date": bars.index[i],
                "price": float(highs[i]),
                "kind": "high",
            })
            continue
        left_lo = lows[i - lookback : i].min()
        right_lo = lows[i + 1 : i + lookback + 1].min()
        if lows[i] < left_lo and lows[i] < right_lo:
            raw.append({
                "idx": i,
                "date": bars.index[i],
                "price": float(lows[i]),
                "kind": "low",
            })

    cleaned: list[dict] = []
    for s in raw:
        if cleaned and cleaned[-1]["kind"] == s["kind"]:
            if s["kind"] == "high" and s["price"] > cleaned[-1]["price"]:
                cleaned[-1] = s
            elif s["kind"] == "low" and s["price"] < cleaned[-1]["price"]:
                cleaned[-1] = s
        else:
            cleaned.append(s)
    return cleaned


def compute_all_indicators(bars: pd.DataFrame, benchmark: pd.DataFrame | None = None) -> pd.DataFrame:
    """One-stop: returns a dataframe with every indicator column + .attrs['swings']."""
    out = add_moving_averages(bars)
    out = add_volume_baseline(out)
    out = add_adr_pct_20(out)
    out = add_atr_20(out)
    if benchmark is not None:
        out = add_rs_vs_benchmark_63d(out, benchmark)
    out.attrs["swings"] = detect_swings(out, lookback=3)
    return out


# ---------- loaders ----------

def load_ticker_bars(symbol: str, stocks_dir: Path | str) -> pd.DataFrame:
    """Read collected_stocks/<SYMBOL>.csv into an OHLCV dataframe indexed by date."""
    stocks_dir = Path(stocks_dir)
    path = stocks_dir / f"{symbol}.csv"
    if not path.exists():
        path = stocks_dir / f"{symbol.lower()}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{symbol}.csv not in {stocks_dir}")

    df = pd.read_csv(path)
    # Detect date column: 'new' format has Unnamed: 0 + DateTime; 'noindex' has DateTime first
    date_col = None
    for c in df.columns:
        lc = c.strip().lower()
        if lc in ("datetime", "date"):
            date_col = c
            break
    if date_col is None:
        # Fall back: second column if first looks like an index
        date_col = df.columns[1] if len(df.columns) >= 7 else df.columns[0]

    # Build normalized frame
    col_map = {c.strip().lower(): c for c in df.columns}
    out = pd.DataFrame({
        "date": pd.to_datetime(df[date_col]),
        "open": df[col_map["open"]].astype(float),
        "high": df[col_map["high"]].astype(float),
        "low": df[col_map["low"]].astype(float),
        "close": df[col_map["close"]].astype(float),
        "volume": df[col_map["volume"]].astype(float),
    })
    out = out.dropna(subset=["date"]).set_index("date").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out


def load_spy_benchmark(spy_csv_path: Path | str) -> pd.DataFrame:
    """Parse SPY Historical Data.csv. Format is DateTime (MM/DD/YYYY), OHLCV."""
    df = pd.read_csv(spy_csv_path)
    col_map = {c.strip().lower(): c for c in df.columns}
    date_col = col_map.get("datetime") or col_map.get("date")

    def to_float(series):
        return series.astype(str).str.replace(",", "").astype(float)

    out = pd.DataFrame({
        "date": pd.to_datetime(df[date_col]),
        "open": to_float(df[col_map["open"]]),
        "high": to_float(df[col_map["high"]]),
        "low": to_float(df[col_map["low"]]),
        "close": to_float(df[col_map["close"]]),
    })
    out = out.dropna(subset=["date"]).set_index("date").sort_index()
    out = out[~out.index.duplicated(keep="last")]
    return out
