"""Full per-move analysis dump for annotation pipeline.

Usage: python3 tools/analyze_move.py SYMBOL [YEAR]
"""
import os
import sys
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classifier.indicators import load_ticker_bars, load_spy_benchmark, compute_all_indicators


def analyze(symbol: str, year: int = 2025) -> None:
    df = pd.read_csv('big_movers_result.csv')
    row = df[(df['symbol'] == symbol) & (df['year'] == year)]
    if row.empty:
        print(f"No move for {symbol} {year}")
        return
    row = row.iloc[0]
    low_date = pd.Timestamp(row['low_date'])
    high_date = pd.Timestamp(row['high_date'])
    gain_pct = float(row['gain_pct'])

    spy = load_spy_benchmark('SPY Historical Data.csv')
    bars = load_ticker_bars(symbol, 'collected_stocks')
    indic = compute_all_indicators(bars, benchmark=spy)

    move = indic[(indic.index >= low_date) & (indic.index <= high_date)].copy()
    if move.empty:
        print(f"No bars in window")
        return

    def window_stats(w: pd.DataFrame) -> dict:
        if len(w) == 0:
            return {}
        e10 = (w['close'] >= w['ema10']).mean() * 100
        e20 = (w['close'] >= w['ema20']).mean() * 100
        t50 = int((abs(w['close'] - w['sma50']) / w['sma50'] < 0.03).sum())
        below_50 = int((w['close'] < w['sma50']).sum())
        rh = w['close'].cummax()
        dd = ((w['low'] - rh) / rh).min() * 100
        u10 = int(((w['low'] - rh) / rh < -0.1).sum())
        adr = w['adr_pct_20'].mean()
        return {
            'days': len(w),
            '10ema': round(e10),
            '20ema': round(e20),
            '50sma_touches': t50,
            'days_below_50': below_50,
            'worst_dd_pct': round(dd, 1),
            'days_u10': u10,
            'pct_u10': round(u10 / len(w) * 100),
            'adr': round(adr, 1) if pd.notna(adr) else None,
            'px_start': round(w['close'].iloc[0], 2),
            'px_end': round(w['close'].iloc[-1], 2),
            'low': round(w['low'].min(), 2),
            'high': round(w['high'].max(), 2),
        }

    full = window_stats(move)

    print(f"=== {symbol} {year}  +{gain_pct:.0f}%  {low_date.date()} → {high_date.date()} ===\n")
    print(f"FULL  {full['days']}d  ${full['low']}→${full['high']}")
    print(f"  10EMA {full['10ema']}%  20EMA {full['20ema']}%  50SMA touches {full['50sma_touches']}  days<50 {full['days_below_50']}")
    print(f"  DD {full['worst_dd_pct']}%  days>10%u {full['days_u10']} ({full['pct_u10']}%)  ADR {full['adr']}%")

    prev_close = move['close'].shift(1)
    gap_pct = (move['open'] - prev_close) / prev_close * 100
    rel_vol = move['volume'] / move['volume'].rolling(20).mean()
    gap_mask = (gap_pct >= 5) & (rel_vol >= 1.5)
    gaps = move[gap_mask].copy()
    gaps['gp'] = gap_pct[gap_mask]
    gaps['rv'] = rel_vol[gap_mask]
    bar_range = gaps['high'] - gaps['low']
    gaps['cp'] = np.where(bar_range > 0, (gaps['close'] - gaps['low']) / bar_range * 100, 50)

    print(f"\nGAPS >=5% on >=1.5x vol:")
    if gaps.empty:
        print("  (none)")
    else:
        for d, r in gaps.iterrows():
            cp = r['cp']
            label = 'REAL' if cp > 70 else ('TRAP' if cp < 30 else 'MID')
            print(f"  {d.date()}  gap{r['gp']:+.0f}%  vol {r['rv']:.1f}x  close@{cp:.0f}%  [{label}]")

    n = len(move)
    quarters = [
        ('Q1', 0, n // 4),
        ('Q2', n // 4, n // 2),
        ('Q3', n // 2, 3 * n // 4),
        ('Q4', 3 * n // 4, n),
    ]
    print(f"\nQUARTERS:")
    for q, a, b in quarters:
        w = move.iloc[a:b]
        if len(w) == 0:
            continue
        s = window_stats(w)
        print(f"  {q} {w.index[0].date()}→{w.index[-1].date()}  {s['days']}d  ${s['px_start']}→${s['px_end']}  10EMA {s['10ema']}%  50SMA {s['50sma_touches']}  DD {s['worst_dd_pct']}%")

    print(f"\nLONGEST 10EMA STREAK:")
    above = (move['close'] >= move['ema10']).values
    longest_start, longest_len = 0, 0
    cur_start, cur_len = 0, 0
    for i, v in enumerate(above):
        if v:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > longest_len:
                longest_len = cur_len
                longest_start = cur_start
        else:
            cur_len = 0
    if longest_len > 0:
        s_date = move.index[longest_start].date()
        e_date = move.index[min(longest_start + longest_len - 1, len(move) - 1)].date()
        print(f"  {s_date} → {e_date}  ({longest_len} days = ~{longest_len // 5} weeks)")


if __name__ == '__main__':
    sym = sys.argv[1]
    yr = int(sys.argv[2]) if len(sys.argv) > 2 else 2025
    analyze(sym, yr)
