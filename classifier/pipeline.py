"""Batch pipeline — classify every move in big_movers_result.csv."""
from __future__ import annotations

import json
import traceback
from pathlib import Path

import pandas as pd

from classifier.indicators import (
    load_ticker_bars, load_spy_benchmark, compute_all_indicators,
)
from classifier.pivot import find_breakout_pivot
from classifier.scoring import resolve_primary_setup
from classifier.setups.vcp import detect_vcp
from classifier.setups.flat_base import detect_flat_base
from classifier.setups.cup_handle import detect_cup_handle
from classifier.setups.double_bottom import detect_double_bottom
from classifier.setups.htf import detect_htf
from classifier.setups.pocket_pivot import detect_pocket_pivot
from classifier.setups.episodic_pivot import detect_ep
from classifier.setups.gap_go import detect_gap_go

DETECTORS = [
    ("VCP", detect_vcp),
    ("Flat Base", detect_flat_base),
    ("Cup with Handle", detect_cup_handle),
    ("Double Bottom", detect_double_bottom),
    ("HTF", detect_htf),
    ("Pocket Pivot", detect_pocket_pivot),
    ("Episodic Pivot", detect_ep),
    ("Gap & Go", detect_gap_go),
]


def classify_moves(
    results_csv: Path,
    repo_root: Path,
    output_json: Path,
    year: int | None = None,
    symbols: list[str] | None = None,
    merge_existing: bool = True,
) -> dict:
    spy = load_spy_benchmark(repo_root / "SPY Historical Data.csv")
    df = pd.read_csv(results_csv)
    if year is not None:
        df = df[df.year == year]
    if symbols:
        df = df[df.symbol.isin(symbols)]

    # Start from existing classifications to preserve user overrides
    out: dict = {}
    if merge_existing and output_json.exists():
        try:
            out = json.loads(output_json.read_text())
        except Exception:
            out = {}

    n = len(df)
    print(f"Classifying {n} moves...")
    ok = 0
    no_pivot = 0
    no_csv = 0
    errors = 0

    for i, (_, row) in enumerate(df.iterrows(), 1):
        key = f"{row.symbol}_{row.year}"
        existing = out.get(key, {})
        # Preserve user overrides across re-runs
        user_fields = {k: v for k, v in existing.items() if k.startswith("user_")}

        try:
            bars = load_ticker_bars(row.symbol, repo_root / "collected_stocks")
            indic = compute_all_indicators(bars, benchmark=spy)
            low = pd.to_datetime(row.low_date)
            high = pd.to_datetime(row.high_date)
            pivot = find_breakout_pivot(indic, low, high)

            if pivot is None:
                out[key] = {
                    "pivot": None,
                    "ai_classifications": [],
                    "ai_primary": None,
                    "needs_review": True,
                    "reason": "no_pivot",
                    **user_fields,
                }
                no_pivot += 1
                continue

            detector_results = []
            for name, fn in DETECTORS:
                try:
                    r = fn(indic, pivot)
                    detector_results.append(r)
                except Exception as e:
                    print(f"  {key}: detector {name} raised: {e}")
                    detector_results.append({
                        "setup": name,
                        "matched": False,
                        "score": 0,
                        "criteria_met": [],
                        "criteria_failed": ["detector_error"],
                        "extra": {"error": str(e)},
                    })

            # Normalize to dicts
            cls_dicts = [
                r.as_dict() if hasattr(r, "as_dict") else r
                for r in detector_results
            ]
            primary = resolve_primary_setup(
                [r for r in detector_results if hasattr(r, "matched")]
            )

            out[key] = {
                "pivot": {
                    "pivot_date": pivot["pivot_date"].strftime("%Y-%m-%d"),
                    "base_start": pivot["base_start"].strftime("%Y-%m-%d"),
                    "base_end": pivot["base_end"].strftime("%Y-%m-%d"),
                    "base_depth_pct": pivot["base_depth_pct"],
                    "breakout_rel_vol": pivot["breakout_rel_vol"],
                },
                "ai_classifications": [c for c in cls_dicts if c.get("matched")],
                "ai_all_detector_results": cls_dicts,  # full output for debugging
                "ai_primary": primary,
                "needs_review": primary is None or max(
                    (c.get("score", 0) for c in cls_dicts), default=0
                ) < 60,
                **user_fields,
            }
            ok += 1

        except FileNotFoundError:
            out[key] = {
                "pivot": None,
                "ai_classifications": [],
                "ai_primary": None,
                "needs_review": True,
                "reason": "no_csv",
                **user_fields,
            }
            no_csv += 1
        except Exception as e:
            traceback.print_exc()
            out[key] = {
                "pivot": None,
                "ai_classifications": [],
                "ai_primary": None,
                "needs_review": True,
                "reason": f"error: {e}",
                **user_fields,
            }
            errors += 1

        if i % 20 == 0:
            print(f"  {i}/{n} processed (ok={ok} no_pivot={no_pivot} no_csv={no_csv} err={errors})")

    output_json.write_text(json.dumps(out, indent=2, default=str))
    print(f"Wrote {len(out)} classifications to {output_json}")
    print(f"Summary: ok={ok}, no_pivot={no_pivot}, no_csv={no_csv}, errors={errors}")
    return out
