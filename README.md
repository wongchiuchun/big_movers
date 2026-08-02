# Chart Studies — A Qullamaggie-Style Setup Research Platform

A single-file web app for studying historical "big mover" stock setups in the Qullamaggie tradition. Loads precomputed gain data for 900+ US tickers, renders candlestick charts with drawing tools, and layers a full study workflow — tags, ratings, AI setup classification, per-leg reviews, and side-by-side AI-vs-human calibration — on top of every move.

> Originally forked from [willhjw/big_movers](https://github.com/willhjw/big_movers). This fork significantly extends the foundation with the study system, AI classification, review workflow, and calibration tooling.

---

## What It Does

Identify strong historical moves → load the chart → annotate it like you would review a real trade → compare your read to an AI-generated review → extract the lessons that generalize.

The goal is not signal generation. It's deliberate pattern-recognition practice: hundreds of multi-hundred-percent moves, decomposed into legs, graded for tradability relative to *your* style, with the reasoning persisted.

---

## Feature Overview

### Chart Engine
- **Candlesticks + volume** — Lightweight Charts v3.8, daily data for 900+ tickers, volume pane with histogram overlay
- **Timeframes** — Daily / Weekly / Monthly, drawings persist across switches
- **Log / linear scale** — one-click toggle, critical for studying multi-hundred-percent moves
- **Benchmark overlay** — SPY in line/candle/bar modes for relative-strength context
- **Moving averages** — configurable EMA/SMA overlays (defaults: EMA 10, 20, SMA 50, 150, 200) with custom periods and colors
- **SuperTrend** — ML-adaptive K-means SuperTrend overlay with configurable ATR length, volatility factors, recency weighting

### Drawing Tools
| Tool | Shortcut | Purpose |
|------|----------|---------|
| Pan | V | Navigate and select drawings |
| H-Line | H | Horizontal price level |
| Line | A | Extended line (both directions) |
| Ray | R | One-directional ray |
| Segment | S | Fixed segment between two points |
| Text | T | Free-form text label |
| Note | N | Text with leader line anchor |
| Measure | M | Rectangle tool with % gain + bar count |

Each tool has independent color, width, and line style (solid/dashed/dotted). Drawings lock toggle, undo (Ctrl+Z), delete selected, copy-across-timeframe, and full persistence per move.

- **Annotation versions** — switch among three independent drawing versions per chart; existing drawings remain version 1, and confirmed reset affects only the active version

### Study Drawer
- **Tags** — preset setups (Breakout, VCP, EP, Gap & Go, Double Bottom, Pocket Pivot, etc.) plus custom tags with rename/delete management
- **Rating** — A–E grade per move
- **Direction** — long / short classification
- **Notes** — free-form rich text, AI-vs-human comparison tracking
- **Manual Leg Reviews** — optionally select chart date ranges and add period-specific detail notes without changing the main Study Notes or AI review
- **Filter views** — save named filter combinations (by tag, direction, min rating, min gain, symbol, year) and mark one as default

### AI Classification + Review
- **Setup detectors** — VCP, Episodic Pivot, Gap & Go, Double Bottom, Pocket Pivot, Breakout. Each reports criteria met / failed with scores, so you can see *why* the classifier picked (or rejected) a setup.
- **Per-leg review** — multi-leg moves decomposed into chapters (off-low / chop / tracker / parabolic) with tradability rationale per leg, entry/stop suggestions, and a style-fit verdict.
- **Compare side-by-side** — dedicated popup placing your notes next to the AI review, with click-to-highlight legs on the chart for direct correspondence.
- **Setup definitions reference** — built-in panel explaining every setup the classifier detects.

### Ticker Management
- **Fetch new tickers** — Twelve Data API integration, supply symbol + date range, auto-writes to local CSV
- **Extend existing** — append missing bars from last-recorded date to today
- **Remove ticker** — confirmation modal, removes from results, optionally deletes OHLCV file, cleans metadata and drawings

### Portfolio Simulation
- **Balanced baskets by default** — six visible tickers drawn from hidden mixtures of same-year movers, liquid point-in-time market anchors, and liquid cross-year comparison names
- **Flexible basket size** — supports one through ten tickers while retaining at least one genuine mover
- **Optional extended timeframe** — randomization normally uses 4–6 calendar months; enable Extended timeframe for a random 6–9 month window that may cross into the following year
- **No look-ahead selection** — anchors use eligibility at the simulation start; comparison-name liquidity uses only the preceding 20–60 daily bars
- **Blind live roles** — source roles stay hidden during setup and playback, then appear with the basket composition and reproducible seed in Trade Review
- **Offline randomization** — selection reads only `big_movers_result.csv`, `market_anchor_universe.json`, and local OHLCV files; it never downloads missing data

### Export
- **Screenshot** — composites chart + drawings + volume pane + header (symbol, gain, rating, tags) + footer (notes) into a single PNG download. Ctrl+Shift+S shortcut.

### Themes
- **Editorial dark** — deep black with warm cream and gold accents (Fraunces italic display, JetBrains Mono data, Plus Jakarta Sans UI)
- **Light** — warm cream/ivory paper aesthetic, print-friendly
- Subtle SVG film-grain on body for paper texture

---

## Technical Stack

- **Backend** — Python/Flask, Python stdlib only (no build dependencies beyond Flask itself)
- **Charts** — Lightweight Charts v3.8 (TradingView open-source library, bundled locally)
- **Frontend** — Single HTML file, all CSS/JS inline, ~5600 lines. No build step. Edit → refresh → done.
- **Storage** — Browser localStorage for chart config, JSON files on server for drawings/metadata/reviews, CSV for OHLCV data
- **Data** — Local daily CSV files in `collected_stocks/`; Twelve Data is used only when you explicitly Fetch or Extend

Normal study and simulation workflows run offline. No cloud, no subscription, no telemetry. Internet access is optional and used only for explicit Twelve Data Fetch/Extend actions or external links such as TradingView.

---

## Quick Start

> **Important:** your shell's default `python3` (in `~/.browser-use-env/`) does **not** have Flask. Always use the full path to system Python 3.13, which does.

```bash
# From the project directory (big_movers/)
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"

# Foreground (blocks terminal, Ctrl+C to stop)
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py

# Background (keeps running after you close the terminal)
nohup /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py > server.log 2>&1 &

# Then open http://localhost:5051/
```

### Stop the server

```bash
lsof -ti :5051 | xargs kill
```

### Check status / tail logs

```bash
lsof -ti :5051              # prints PID if running, nothing if stopped
tail -f server.log          # watch requests live
```

Tested with Python 3.13 + Flask. For Twelve Data ticker fetching, put `TWELVE_API_KEY=<your-key>` in `.env` (either in the project dir or the parent dir — both are checked).

### Market-anchor data maintenance

The reviewed anchor manifest contains 50 liquid leaders with point-in-time eligibility and a fixed initial coverage target of `2015-01-01` through `2025-12-31`. These CSVs live in `collected_stocks/`; they are deliberately not added to `big_movers_result.csv`.

Audit local coverage without internet access:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py --dry-run
```

Explicitly synchronize missing coverage:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py
```

Synchronization uses a minimum nine-second request interval, respects provider limits, writes atomically, and records resumable progress in the ignored `.market_anchor_sync_state.json`. Normal app startup and simulation never invoke it.

---

## File Layout

```
big_movers/
├── Big_movers.html             # Single-file frontend
├── Big_movers_server.py        # Flask backend, port 5051
├── portfolio_basket.js         # Seeded balanced-basket selection engine
├── market_anchor_universe.json # Reviewed 50-name point-in-time anchor pool
├── market_anchor_sync.py       # Explicit audit/synchronization engine
├── big_movers_result.csv       # Precomputed setups (symbol, year, gain, dates)
├── SPY Historical Data.csv     # Benchmark data
├── collected_stocks/           # ~929 ticker OHLCV CSVs
├── vendor/                     # Locally bundled browser dependencies
├── classifier/                 # Setup classification engine
├── drawings.json               # Per-move annotations
├── metadata.json               # Per-move tags, ratings, notes
├── ai_classifications.json     # AI setup detector output per move
├── reviews.json                # Per-leg review write-ups
├── setup_definitions.json      # Setup reference data
└── tools/                      # Analysis utilities
```

---

## Who This Is For

Traders and researchers who want to study price history *systematically* rather than rely on screeners that only show current market state. By annotating hundreds of historical movers with the same framework — setup type, leg decomposition, tradability verdict relative to your own style — you build visual pattern recognition as a repeatable skill.

The tool is opinionated about one thing: **data-only verdicts hide chapters**. A move that's "77% above the 10EMA on average" might decompose into legs of 49% / 100% / 86% — one untradable, one perfect, one parabolic. The study workflow is designed to force that decomposition before you trust any aggregate.

---

## Disclaimer

Stock data and any statistics or charts derived from it are **not** guaranteed to be accurate or complete. This is a research and study tool, not a trading system. You are responsible for independently verifying any information before using it.

---

## License

MIT License — see [LICENSE](LICENSE). Original foundation © willhjw; additions © Ray Wong.
