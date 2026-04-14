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

### Study Drawer
- **Tags** — preset setups (Breakout, VCP, EP, Gap & Go, Double Bottom, Pocket Pivot, etc.) plus custom tags with rename/delete management
- **Rating** — A–E grade per move
- **Direction** — long / short classification
- **Notes** — free-form rich text, AI-vs-human comparison tracking
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

### Export
- **Screenshot** — composites chart + drawings + volume pane + header (symbol, gain, rating, tags) + footer (notes) into a single PNG download. Ctrl+Shift+S shortcut.

### Themes
- **Editorial dark** — deep black with warm cream and gold accents (Fraunces italic display, JetBrains Mono data, Plus Jakarta Sans UI)
- **Light** — warm cream/ivory paper aesthetic, print-friendly
- Subtle SVG film-grain on body for paper texture

---

## Technical Stack

- **Backend** — Python/Flask, Python stdlib only (no build dependencies beyond Flask itself)
- **Charts** — Lightweight Charts v3.8 (TradingView open-source library, loaded from CDN)
- **Frontend** — Single HTML file, all CSS/JS inline, ~5600 lines. No build step. Edit → refresh → done.
- **Storage** — Browser localStorage for chart config, JSON files on server for drawings/metadata/reviews, CSV for OHLCV data
- **Data** — Local daily CSV files in `collected_stocks/`, optional Twelve Data API for new tickers

Everything runs offline. No cloud, no subscription, no telemetry.

---

## Quick Start

```bash
# From the project directory
python3 Big_movers_server.py
# Open http://localhost:5051/
```

Tested with Python 3.13 + Flask. For Twelve Data ticker fetching, put `TWELVE_API_KEY=<your-key>` in `.env` (either in the project dir or the parent dir — both are checked).

---

## File Layout

```
big_movers/
├── Big_movers.html             # Single-file frontend
├── Big_movers_server.py        # Flask backend, port 5051
├── big_movers_result.csv       # Precomputed setups (symbol, year, gain, dates)
├── SPY Historical Data.csv     # Benchmark data
├── collected_stocks/           # ~929 ticker OHLCV CSVs
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
