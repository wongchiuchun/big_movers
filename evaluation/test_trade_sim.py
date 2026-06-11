"""Hand-verification of trade_sim mechanics on a known chart (STRL 2025)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from classifier.indicators import compute_all_indicators, load_spy_benchmark, load_ticker_bars
from evaluation.extract import detect_events, enrich
from evaluation.trade_sim import make_arrays, simulate_event

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

spy = load_spy_benchmark('SPY Historical Data.csv')
res = pd.read_csv('big_movers_result.csv')
row = res[(res.symbol == 'STRL') & (res.year == 2025)].iloc[0]
ind = enrich(compute_all_indicators(load_ticker_bars('STRL', 'collected_stocks'), benchmark=spy))
arr = make_arrays(ind)
lo = int(ind.index.searchsorted(pd.Timestamp(row.low_date)))
hi = int(ind.index.searchsorted(pd.Timestamp(row.high_date), side='right')) - 1
evs = [(i, et) for i, et in detect_events(ind, lo, hi) if et not in ('move_start',)]
i, et = evs[0]
print('first event:', et, ind.index[i].date(), 'entry close', round(ind.close.iloc[i], 2),
      'LOD', round(ind.low.iloc[i], 2))

trades = {(t['stop'], t['exit']): t for t in simulate_event(arr, i)}
EXPECT = {  # validated against bars in the pre-refactor run
    ('LOD', 'FIX'): (-2.68, 1, 'stop'),
    ('LOD', 'E10'): (-2.68, 1, 'stop'),
    ('LOD', 'P3_E20'): (-2.68, 1, 'stop'),
    ('ATR10', 'E20'): (-1.00, 3, 'stop'),
    ('SW10C', 'E20'): (9.94, 85, 'trail_ma'),
    ('LOD_ATR', 'E20'): (-1.00, 3, 'stop'),
}
ok = True
for key, (er, ed, ereason) in EXPECT.items():
    t = trades[key]
    match = abs(t['r'] - er) < 0.01 and t['days'] == ed and t['reason'] == ereason
    ok &= match
    print('  %-6s %-7s R=%7.2f days=%4d reason=%-9s %s' %
          (key[0], key[1], t['r'], t['days'], t['reason'], 'OK' if match else f'MISMATCH expect {er}/{ed}/{ereason}'))
print('regression vs validated run:', 'PASS' if ok else 'FAIL')
print('policies simulated:', len(trades))

t0 = time.time()
for j, _ in evs:
    simulate_event(arr, j)
dt = time.time() - t0
print(f'perf: {len(evs)} events in {dt:.2f}s -> {dt/len(evs)*1000:.1f} ms/event '
      f'(projected ~21k events: {21000*dt/len(evs)/60:.1f} min)')
