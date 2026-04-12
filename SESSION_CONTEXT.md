# Setup Classifier POC — Session Context

> Starting point for the next conversation. Read this first.

## What this project is

A retrospective study tool for classifying historical big-winner stock moves against known trading setup patterns (VCP, EP, Flat Base, etc.). The ultimate goal is to build a **personalized trading playbook** through structured chart review — not a predictor.

The system has three layers:
1. **Automated hints** — Python detectors that scan OHLCV data and suggest which setup a move might be. These are rough suggestions, not ground truth.
2. **Chart overlays** — SMA/EMA lines, swing-pivot markers, and detected breakout-pivot marker rendered on a Lightweight Charts frontend for visual verification.
3. **Manual review** — the human reviews charts, annotates them with their own analysis (setup classification, entry/stop levels, tradability assessment, style fit notes), and the accumulated library becomes the playbook.

## Branch and repo state

- **Repo**: `/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers/`
- **Branch**: `feature/setup-classifier-poc` (12 commits ahead of `main`)
- **Server**: Flask at port 5051. Start with:
  ```bash
  cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py
  ```
  The system Python at `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` has Flask + pandas + numpy installed. The default `python3` points to a broken virtualenv — **never use it**.

## What's been built (completed)

### Phase 1 — Indicator layer (`classifier/indicators.py`)
- `compute_all_indicators(bars, benchmark=spy)` → DataFrame with: `sma50, sma150, sma200, ema10, ema20, avg_vol_50, rel_vol, adr_pct_20, atr_20, rs_vs_spy_63d`
- `.attrs["swings"]` → fractal swing-pivot list `[{idx, date, price, kind}]`
- `load_ticker_bars(symbol, stocks_dir)` and `load_spy_benchmark(path)` loaders
- Handles mixed CSV formats (new/noindex) after the date-normalization cleanup

### Phase 2 — Pivot detection (`classifier/pivot.py`)
- `find_breakout_pivot(indic, low_date, high_date)` → `{pivot_date, base_start, base_end, base_high, base_low, base_depth_pct, breakout_rel_vol, quality_score}` or `None`
- Score-based selection: scans all (day, base_len) candidates and returns the highest-quality one (prefers longer + tighter bases)
- Uses numpy arrays internally for performance (~5s for 97 moves)
- Defaults: min_base_len=15, max_base_depth=25%, min_breakout_rel_vol=1.4, base_len_stride=3

### Phase 3 — Setup detectors (`classifier/setups/*.py`)
Eight detectors, each returns `DetectorResult(setup, matched, score, criteria_met, criteria_failed, extra)`:

| Detector | File | Gate | Key criteria |
|----------|------|------|-------------|
| VCP | `vcp.py` | prior_uptrend optional (+30) | ≥2 decreasing contractions, final <10%, VDU, breakout vol ≥1.5x |
| Flat Base | `flat_base.py` | prior_advance optional (+30) | depth ≤15%, horizontal slope, duration ≥5w, breakout vol ≥1.4x |
| Cup & Handle | `cup_handle.py` | finds cup left edge | cup ≤33% deep, ≥7w, handle ≤15% in upper half |
| Double Bottom | `double_bottom.py` | finds two lows + middle peak | lows within 5%, peak rally 10-30%, breakout above peak |
| HTF | `htf.py` | pole ≥100% in 4-8w | flag ≤25% deep, volume contraction pole→flag |
| Pocket Pivot | `pocket_pivot.py` | above SMA200 | up-day vol beats 10d down-day max, near 10EMA/50SMA |
| Episodic Pivot | `episodic_pivot.py` | finds gap ≥5% on ≥2.5x vol | post-gap holds above gap low, tight consolidation |
| Gap & Go | `gap_go.py` | gap ≥10%, vol ≥3x, close>open | day-1 entry, gap unfilled |

**Important design decisions:**
- Prior-trend gates (VCP, Flat Base) are **scored, not hard-fail** — many 2025 big winners broke out of accumulation at the low without prior trend.
- Pocket Pivot and Gap & Go are **demoted** in tiebreaker unless they're the only match.
- EP wins over Gap & Go when both match (same gap, but EP = structured Day 2-10 entry).

### Phase 4 — Scoring + pipeline
- `classifier/scoring.py` — `resolve_primary_setup(results)` applies tiebreaker table and returns the winning setup name
- `classifier/pipeline.py` — `classify_moves(results_csv, repo_root, output_json, year=, symbols=)` iterates moves, runs all detectors, writes `ai_classifications.json`. Preserves `user_*` override fields across re-runs.
- `classify.py` — CLI entry point: `python3 classify.py --year 2025 [--symbol XXX] [--no-merge]`

### Phase 5 — Frontend
- **Server endpoints** (`Big_movers_server.py`):
  - `GET /api/indicators?symbol=XXX` — computed MAs/swings/RS/volume series
  - `GET /api/pivot?symbol=XXX&year=YYYY` — detected breakout pivot for a move
  - `GET /api/ai-classifications` — read `ai_classifications.json`
  - `POST /api/ai-classifications/override` — user accept/reject persisted
  - `GET /api/setup-definitions` — setup taxonomy from `setup_definitions.json`

- **Chart overlays** (`Big_movers.html`):
  - SMA50 (gold) / SMA150 (mint) / SMA200 (coral) line overlays
  - Swing-pivot arrow markers (coral-down for highs, mint-up for lows)
  - Yellow PIVOT circle on the detected breakout day
  - Three independent topbar toggles: **AI** (MAs), **Sw** (swings), **Piv** (pivot)

- **Setup definitions modal**:
  - **Defs** button in topbar opens a full-screen modal
  - Left sidebar groups 18 setups by family, right pane shows full spec
  - AI chips in the study drawer are clickable → opens definition for that setup

- **AI Suggested section** in Study drawer:
  - Shows matched setups with score chips + pivot info
  - Accept/Reject buttons (persisted to `ai_classifications.json`)
  - **AI filter dropdown** in top filter bar — filter stocks list by AI primary setup

### Phase 6 — Data cleanup (on `main`, pre-branch)
- `cleanup_cross_year.py` — splits moves that span calendar years into per-year rows (SNDK 2025→2026)
- `normalize_dates.py` — converts MM/DD/YYYY dates to ISO in 12 OHLCV CSVs
- Both are reusable scripts at the repo root

## Current 2025 classification results

97 moves processed, 62 matched (64%):

| Setup | Count |
|-------|-------|
| (none) | 35 |
| Double Bottom | 23 |
| Episodic Pivot | 14 |
| Pocket Pivot | 11 |
| VCP | 8 |
| Gap & Go | 3 |
| Flat Base | 2 |
| HTF | 1 |

11 moves had no pivot detected (too deep or no qualifying base).

**Known issues with current classification:**
- Double Bottom is over-represented (23/62) — likely many are false positives where the detector finds two arbitrary lows in the pre-move window
- VCP detector requires contractions that are hard to find in short bases — may need swing detector tuning (lookback=3 might be too narrow for longer bases)
- CIEN 2025 classified as VCP (85) when the real entry is the Sep 4 EP (80) — VCP won on score because the Jun-Sep base met contraction criteria, even though the gap was the defining event
- IREN 2025 correctly gets no match — no clean tradable setup at inception

## What we agreed to do next (not yet built)

### Stage 1: Manual chart review process
The user will review ~200-300 charts manually, broken into legs:
- Each move gets broken into 2-5 **legs** (distinct phases: advance, consolidation, pullback)
- Each leg gets independently classified (setup or "no setup") with entry/stop levels
- User adds **subjective style notes** ("too choppy, would be shaken out", "clean 10EMA trend, tradable")
- **No performance rating from the user** — that's hindsight-biased. Ratings come from empirical analysis later.

**Note convention** for the existing Study drawer textarea:
```
[VCP] 2025-03-15 → 2025-05-20 | leg 1 of 3
Entry: 48.50 (range break) | Stop: 45.00
Context: 2-year base, broke ATH Jan 2025
Structure: 3 contractions, VDU last week, breakout closed top 20% of range
Subjective: textbook tight. To my liking — would trade.

[NO SETUP] — choppy, pulled back to 20 EMA 6 times, would've been shaken out.
```

### Stage 2: LLM-assisted co-pilot (future)
Once enough labeled examples exist (~50-100 legs), the library becomes a retrieval corpus:
- User shows a current chart: "I think this is a VCP breakout from a 3-month base"
- System pulls up similar historical legs from the library
- LLM debates the setup: agrees/disagrees, suggests entry/stop based on labeled examples
- Rates the setup for the user's specific style (not generic textbook rating)

### Review guide
`REVIEW_GUIDE.md` documents the structured process for Claude to analyze a ticker+year:
1. Quantitative snapshot (10EMA adherence, drawdowns, gaps, trend slope)
2. Break move into legs
3. Classify each leg (setup or no-setup, entry/stop, tradability)
4. Assess style fit (holdability, which leg matches user's style)
5. Compare to textbook definitions (myth-busting)

Trigger with: "Review [TICKER] [YEAR]"

## Key files

```
setup analysis/big_movers/
├── Big_movers_server.py          # Flask server, port 5051
├── Big_movers.html               # Single-file frontend (~4500 lines)
├── big_movers_result.csv         # Move dataset: year,symbol,gain_pct,low/high dates+prices
├── ai_classifications.json       # Per-move classifier output + user overrides
├── setup_definitions.json        # 18 setup definitions (spec, criteria, A+ filters)
├── REVIEW_GUIDE.md               # How to do structured chart reviews
├── SESSION_CONTEXT.md            # This file
├── CLAUDE.md                     # Project conventions and architecture reference
├── classify.py                   # CLI: python3 classify.py --year 2025
├── cleanup_cross_year.py         # Data cleanup: split cross-year moves
├── normalize_dates.py            # Data cleanup: MM/DD/YYYY → ISO
├── classifier/
│   ├── __init__.py
│   ├── indicators.py             # SMA/EMA/ADR/ATR/RS/swings/loaders
│   ├── pivot.py                  # Score-based breakout-pivot detection
│   ├── scoring.py                # Tiebreaker resolution
│   ├── pipeline.py               # Batch classifier over results CSV
│   └── setups/
│       ├── __init__.py           # DetectorResult dataclass
│       ├── vcp.py
│       ├── flat_base.py
│       ├── cup_handle.py
│       ├── double_bottom.py
│       ├── htf.py
│       ├── pocket_pivot.py
│       ├── episodic_pivot.py
│       └── gap_go.py
├── collected_stocks/             # ~929 individual ticker OHLCV CSVs
├── SPY Historical Data.csv       # Benchmark
├── metadata.json                 # Per-move manual tags/rating/direction/notes
├── drawings.json                 # Per-move chart drawings
└── indicators_cache/             # (empty, reserved for optional caching)
```

## Strategic context

The user is an active trader studying Qullamaggie/Minervini/O'Neil style momentum setups. The goal isn't to build a trading bot — it's to develop a **personalized playbook** by:

1. Reviewing 200-300 confirmed winners retrospectively
2. Breaking each move into legs and identifying which legs were tradable
3. Accumulating subjective style notes ("this is my kind of setup" vs "would've been shaken out")
4. Building a searchable library of tagged legs for future reference
5. Eventually having an LLM co-pilot that can pull relevant examples and challenge/validate live trade ideas

The system sits between art and science — structured enough to query, flexible enough to handle discretion. The automated classifier is a starting hint, not the answer. The human's labeled annotations are the real value.
