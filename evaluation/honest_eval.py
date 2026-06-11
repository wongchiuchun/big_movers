"""Honest, out-of-sample re-evaluation of the existing strategy.

Protocol (the fix for the contaminated odd/even split in strategy_opt.py):
  1. Partition every trade by SYMBOL into train / test (evaluation.split).
  2. Select the policy (stop x exit) and the filter set using TRAIN ONLY.
  3. Report the SAME locked choice on the held-out TEST set, and on the
     chronological time-split, without ever having looked at them.

What we learn: the gap between TRAIN and TEST avg-R is the overfit tax. If a
strategy chosen on half the tickers falls apart on the other half, it was
curve-fit. If it holds, it is a candidate for real trading.

Usage:
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 -m evaluation.honest_eval
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

from evaluation.split import tag_frame
from evaluation.strategy_opt import (
    ADR_HI, ADR_LO, FILTERS, MIN_DOLLAR_VOL_M, WIN_BAND, apply_filters,
    base_universe, filter_marginals, load, stats,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "evaluation", "output")


# FIX is a fixed-horizon hold (no trailing) — a baseline, not a tradeable exit
# rule. Exclude it from selection so we pick a real trail.
EXCLUDE_EXITS = {"FIX"}


def select_policy(train_uni: pd.DataFrame) -> tuple[str, str]:
    """Best stop x exit on TRAIN, inside the win band, by winsorized avg R."""
    best, best_score = None, -1e9
    for (sk, ek), sub in train_uni.groupby(["stop", "exit"]):
        if ek in EXCLUDE_EXITS:
            continue
        s = stats(sub)
        if s["n"] < 300:
            continue
        in_band = WIN_BAND[0] <= s["win_pct"] <= WIN_BAND[1]
        score = (s["avg_r_w99"] or -9) + (0.0 if in_band else -0.5)
        if score > best_score:
            best, best_score = (sk, ek), score
    return best


def filter_generalization(train_sub: pd.DataFrame, test_sub: pd.DataFrame) -> list[dict]:
    """For every candidate filter, compare its w99-R edge on train vs test.
    A filter whose edge flips sign out-of-sample was noise, not signal."""
    tr, te = filter_marginals(train_sub), filter_marginals(test_sub)
    rows = []
    for name in FILTERS:
        if name not in tr or name not in te:
            continue
        e_tr = (tr[name]["pass"].get("avg_r_w99") or 0) - (tr[name]["fail"].get("avg_r_w99") or 0)
        e_te = (te[name]["pass"].get("avg_r_w99") or 0) - (te[name]["fail"].get("avg_r_w99") or 0)
        rows.append({"filter": name, "edge_train": round(e_tr, 2),
                     "edge_test": round(e_te, 2),
                     "holds": (e_tr > 0) == (e_te > 0),
                     "n_pass_train": tr[name]["pass"].get("n", 0)})
    rows.sort(key=lambda r: -r["edge_train"])
    return rows


def select_filters(train_sub: pd.DataFrame) -> list[str]:
    """Keep filters with edge >= 0.15 w99-R and >= 300 passing TRAIN trades."""
    marg = filter_marginals(train_sub)
    keep = []
    for name, m in marg.items():
        edge = (m["pass"].get("avg_r_w99") or 0) - (m["fail"].get("avg_r_w99") or 0)
        if edge >= 0.15 and (m["pass"].get("n") or 0) >= 300:
            keep.append((name, edge))
    keep.sort(key=lambda x: -x[1])
    return [k for k, _ in keep[:4]]


def evaluate(df: pd.DataFrame, stop: str, exit_: str, filters: list[str]) -> dict:
    sub = df[(df["stop"] == stop) & (df["exit"] == exit_)]
    filtered = apply_filters(sub, filters)
    return {"unfiltered": stats(sub), "filtered": stats(filtered)}


def main() -> None:
    df = tag_frame(load())
    uni = base_universe(df)
    train_uni = uni[uni["fold"] == "train"]
    test_uni = uni[uni["fold"] == "test"]

    print(f"universe: {len(uni):,} trades  |  train {len(train_uni):,}  test {len(test_uni):,}")

    # --- selection happens on TRAIN ONLY ---
    stop, exit_ = select_policy(train_uni)
    train_sub = train_uni[(train_uni["stop"] == stop) & (train_uni["exit"] == exit_)]
    filters = select_filters(train_sub)
    print(f"\nSELECTED ON TRAIN -> stop={stop} exit={exit_} filters={filters}")

    # --- lock it, evaluate everywhere ---
    report = {"selected": {"stop": stop, "exit": exit_, "filters": filters},
              "splits": {}}

    for label, frame in (("train_symbol", train_uni), ("test_symbol", test_uni)):
        report["splits"][label] = evaluate(frame, stop, exit_, filters)

    # time split, same locked choice
    for label, mask in (("train_time", uni["tfold"] == "train"),
                        ("test_time", uni["tfold"] == "test")):
        report["splits"][label] = evaluate(uni[mask], stop, exit_, filters)

    # also lock the OLD published headline (LOD/E50 + its 4 filters) and show its
    # degradation, so the comparison is apples-to-apples with the playbook
    old_filters = select_filters(
        train_uni[(train_uni["stop"] == "LOD") & (train_uni["exit"] == "E50")])
    report["old_headline"] = {"stop": "LOD", "exit": "E50", "filters": old_filters,
                              "train_symbol": evaluate(train_uni, "LOD", "E50", old_filters),
                              "test_symbol": evaluate(test_uni, "LOD", "E50", old_filters)}

    # --- print a readable degradation table ---
    def line(tag, d):
        f = d["filtered"]
        return (f"  {tag:14} n={f['n']:5} win={f['win_pct']:5}% "
                f"avgR={f['avg_r']:6.2f} w99={f['avg_r_w99']:6.2f} "
                f"med={f['med_r']:5.2f} R/30d={f['r_per_30d']:5}")

    print(f"\n=== LOCKED {stop}/{exit_} + {filters} ===")
    for tag in ("train_symbol", "test_symbol", "train_time", "test_time"):
        print(line(tag, report["splits"][tag]))

    print(f"\n=== OLD HEADLINE LOD/E50 + {old_filters} (overfit check) ===")
    print(line("train_symbol", report["old_headline"]["train_symbol"]))
    print(line("test_symbol", report["old_headline"]["test_symbol"]))

    # filter generalization: does each train-selected filter hold its edge sign on test?
    gen = filter_generalization(train_sub, test_uni[(test_uni["stop"] == stop) & (test_uni["exit"] == exit_)])
    report["filter_generalization"] = gen
    print("\n=== FILTER GENERALIZATION (edge in w99-R, train vs held-out test) ===")
    for g in gen:
        flag = "holds" if g["holds"] else "FLIPS"
        print(f"  {g['filter']:16} train={g['edge_train']:+5.2f} test={g['edge_test']:+5.2f}  [{flag}]  n_pass_tr={g['n_pass_train']}")

    ts, te = (report["splits"]["train_symbol"]["filtered"]["avg_r_w99"],
              report["splits"]["test_symbol"]["filtered"]["avg_r_w99"])
    print(f"\nOVERFIT TAX (selected): train w99 {ts:.2f} -> test w99 {te:.2f} "
          f"= {(te - ts):+.2f} ({(te/ts - 1)*100:+.0f}%)")

    with open(os.path.join(OUT_DIR, "honest_eval.json"), "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"\nwrote {os.path.join(OUT_DIR, 'honest_eval.json')}")


if __name__ == "__main__":
    main()
