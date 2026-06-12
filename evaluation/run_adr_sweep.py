"""What happens to the indicator if we raise / remove the ADR% cap?

The universe filter is ADR 4-8% (the momentum sweet spot). Higher ADR = faster,
more volatile names — bigger moves but wider stops. In R-terms the net effect
isn't obvious, so we measure it.

For the base-1 entry (early, not-extended, volume, liquid) we record each entry's
ADR and its forward R under Mode B (free roll) and Mode A (runner), then report:
  - MARGINAL bands: how do 8-10 / 10-12 / 12%+ ADR entries compare to 4-8?
  - CUMULATIVE caps: what the resulting universe looks like at 4-8 / 4-10 / 4-12 / 4-no cap.
On held-out winner tickers AND the control group (so dilution shows up).

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.run_adr_sweep
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from classifier.indicators import compute_all_indicators, load_spy_benchmark, load_ticker_bars
from evaluation.extract import enrich
from evaluation.engine import entries_since_low, make_arrays, run_trade, signal_bars
from evaluation.split import split_symbol

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "evaluation", "output")

ADR_LO = 4.0
MIN_DOLVOL_M = 5.0
MAX_ORDINAL, MAX_EXT, MIN_RELVOL = 3, 50.0, 1.5
ENTRY_COOLDOWN = 5
MARGINAL = [(4, 8, "4-8 (current)"), (8, 10, "8-10"), (10, 12, "10-12"), (12, 999, "12%+")]
CUMUL = [(8, "cap 8 (current)"), (10, "cap 10"), (12, "cap 12"), (999, "no cap")]


def stats(rs, days=None):
    if not rs:
        return {"n": 0}
    a = np.array(rs, float)
    cap = np.quantile(a, 0.99) if len(a) > 5 else a.max()
    out = {"n": len(a), "win": round(float((a > 0).mean() * 100), 1),
           "avgR": round(float(a.mean()), 2), "avgRw99": round(float(np.minimum(a, cap).mean()), 2)}
    if days:
        out["R30d"] = round(float(a.mean() / max(np.mean(days), 1) * 30), 2)
    return out


def main():
    results = pd.read_csv(os.path.join(ROOT, "big_movers_result.csv"))
    spy = load_spy_benchmark(os.path.join(ROOT, "SPY Historical Data.csv"))
    windows = {}
    for r in results.itertuples(index=False):
        windows.setdefault(str(r.symbol), []).append(
            (pd.Timestamp(r.low_date), pd.Timestamp(r.high_date)))
    tickers = sorted({f[:-4] for f in os.listdir(os.path.join(ROOT, "collected_stocks"))
                      if f.endswith(".csv")})

    rows = []  # each: bucket, adr, rB, rA, dB, dA
    processed = 0
    for sym in tickers:
        try:
            ind = enrich(compute_all_indicators(
                load_ticker_bars(sym, os.path.join(ROOT, "collected_stocks")), benchmark=spy))
        except Exception:
            continue
        if len(ind) < 120:
            continue
        arr = make_arrays(ind)
        sb = signal_bars(ind)
        ordn = entries_since_low(sb["raw"], arr["low"])
        idx = ind.index
        wins = windows.get(sym, [])
        fold = split_symbol(sym)
        processed += 1
        last_entry = -10_000
        for t in np.flatnonzero(sb["raw"]):
            if t - last_entry < ENTRY_COOLDOWN:
                continue
            adr, dv, ext, rv = sb["adr"][t], sb["dolvol_m"][t], sb["ext"][t], sb["relvol20"][t]
            if not (np.isfinite(adr) and adr >= ADR_LO and np.isfinite(dv) and dv >= MIN_DOLVOL_M):
                continue
            if not (ordn[t] <= MAX_ORDINAL and np.isfinite(ext) and ext < MAX_EXT
                    and np.isfinite(rv) and rv >= MIN_RELVOL):
                continue
            last_entry = t
            ts = idx[t]
            in_win = any(lo <= ts <= hi for lo, hi in wins)
            bucket = ("winner_" + fold) if in_win else "control"
            b = run_trade(arr, int(t), "sma50", 3, "SW", True)   # Mode B
            a = run_trade(arr, int(t), "sma50", 3, "SW", False)  # Mode A
            if b is None or a is None:
                continue
            rows.append({"bucket": bucket, "adr": float(adr),
                         "rB": b["r"], "dB": b["days"], "rA": a["r"], "dA": a["days"]})

    df = pd.DataFrame(rows)
    print(f"processed {processed} tickers; {len(df)} base-1 entries (ADR>=4, no upper cap)\n")
    report = {"marginal": {}, "cumulative": {}}

    def block(sub_w, sub_c):
        return {"winner_test_modeB": stats(sub_w["rB"].tolist(), sub_w["dB"].tolist()),
                "winner_test_modeA": stats(sub_w["rA"].tolist(), sub_w["dA"].tolist()),
                "control_modeB": stats(sub_c["rB"].tolist())}

    wt = df[df.bucket == "winner_test"]
    ct = df[df.bucket == "control"]

    print("=== MARGINAL ADR BANDS (what each band contributes) ===")
    print(f"  {'band':14} | {'WIN n':>6} {'win%':>5} {'B avgR':>7} {'B w99':>6} {'A w99':>6} {'B R30d':>7} | {'CTRL n':>7} {'B w99':>6}")
    for lo, hi, lab in MARGINAL:
        sw = wt[(wt.adr >= lo) & (wt.adr < hi)]
        sc = ct[(ct.adr >= lo) & (ct.adr < hi)]
        bl = block(sw, sc)
        report["marginal"][lab] = bl
        b, a, c = bl["winner_test_modeB"], bl["winner_test_modeA"], bl["control_modeB"]
        print(f"  {lab:14} | {b.get('n',0):>6} {b.get('win','-'):>5} {b.get('avgR','-'):>7} {b.get('avgRw99','-'):>6} "
              f"{a.get('avgRw99','-'):>6} {b.get('R30d','-'):>7} | {c.get('n',0):>7} {c.get('avgRw99','-'):>6}")

    print("\n=== CUMULATIVE (the universe you'd actually run) ===")
    print(f"  {'cap':16} | {'WIN n':>6} {'win%':>5} {'B avgR':>7} {'B w99':>6} {'A w99':>6} {'B R30d':>7} | {'CTRL n':>7} {'B w99':>6}")
    for hi, lab in CUMUL:
        sw = wt[(wt.adr >= ADR_LO) & (wt.adr < hi)]
        sc = ct[(ct.adr >= ADR_LO) & (ct.adr < hi)]
        bl = block(sw, sc)
        report["cumulative"][lab] = bl
        b, a, c = bl["winner_test_modeB"], bl["winner_test_modeA"], bl["control_modeB"]
        print(f"  {lab:16} | {b.get('n',0):>6} {b.get('win','-'):>5} {b.get('avgR','-'):>7} {b.get('avgRw99','-'):>6} "
              f"{a.get('avgRw99','-'):>6} {b.get('R30d','-'):>7} | {c.get('n',0):>7} {c.get('avgRw99','-'):>6}")

    with open(os.path.join(OUT, "adr_sweep.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT, 'adr_sweep.json')}")


if __name__ == "__main__":
    main()
