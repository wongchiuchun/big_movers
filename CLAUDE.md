# Chart Studies — Project Context

> Codebase orientation for Claude Code sessions. Read this first before exploring.

## What This Is

A single-file web app for studying historical "big mover" stock setups in the Qullamaggie style. Loads precomputed gain data from a CSV, fetches OHLCV bars per ticker, renders candlestick charts with drawing tools, and lets you tag/rate/annotate each setup for filtering and review.

**Stack**: Flask backend (Python stdlib only) + single-file HTML/CSS/JS frontend with Lightweight Charts v3.8.0 (TradingView's open-source library, loaded from CDN).

**No build step.** Edit HTML, refresh browser. Edit Python, restart server.

## How to Run

```bash
cd "<this dir>"
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py
# Open http://localhost:5051/
```

The system Python at the path above has Flask installed. The default `python3` in the user's environment is in `/Users/raywong/.browser-use-env/bin/python3` which does NOT have Flask. Always use the explicit Python 3.13 path.

To restart during development: `lsof -ti :5051 | xargs kill 2>/dev/null` then start again.

## File Structure

```
big_movers/
├── Big_movers.html               # Single-file frontend (~3900 lines, all CSS/JS inline)
├── Big_movers_server.py          # Flask backend, port 5051
├── Chart_Studies_mockup.html     # Standalone UI mockup (not served, design reference)
├── big_movers_result.csv         # Precomputed setups: year,symbol,gain_pct,low_date,high_date,low_price,high_price,avg_vol_b
├── SPY Historical Data.csv       # Benchmark data (separate format from collected_stocks)
├── collected_stocks/             # ~929 individual ticker OHLCV CSVs
├── drawings.json                 # Per-move drawing annotations (created on first save)
├── metadata.json                 # Per-move study data: tags, rating, direction, notes
├── README.md                     # User-facing project README
├── CLAUDE.md                     # This file
└── .env                          # NOT here — lives in parent dir at ../.env
```

The `.env` file is at `/Users/raywong/Desktop/qullamaggie-study-guide/.env` (parent dir). Contains `TWELVE_API_KEY` for fetching new ticker data via Twelve Data API. The server checks both `./.env` and `../.env`.

## Backend API (`Big_movers_server.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Serves `Big_movers.html` |
| `/api/results` | GET | Returns `big_movers_result.csv` as JSON array |
| `/api/ohlcv?symbol=XXX` | GET | Returns OHLCV bars for a ticker (SPY served from separate file, cached) |
| `/api/drawings` | GET/POST | Reads/writes `drawings.json` (atomic write via temp file + rename) |
| `/api/metadata` | GET/POST | Reads/writes `metadata.json` (atomic write) |
| `/api/fetch-ticker` | POST | Fetches OHLCV from Twelve Data API. Body: `{symbol, start_date, end_date}` for new, or `{symbol, extend: true}` to append from last date in CSV to today |
| `/api/add-result` | POST | Appends/updates a row in `big_movers_result.csv` |
| `/api/remove-ticker` | POST | Removes a row from results CSV; optionally deletes the OHLCV CSV file |

**CSV format auto-detection**: Server supports 3 layouts in `collected_stocks/` (lines 213-260 of server.py): `new` (with index col), `noindex` (DateTime first), and `old` (legacy date,close,open,...). New tickers fetched via Twelve Data API are written in `noindex` format.

**Important helpers**:
- `_atomic_json_write(path, data)` — writes to `.tmp` then `os.replace()`. Used by both drawings and metadata POSTs.
- `_normalize_date_maybe()`, `_parse_float_maybe()`, `_parse_volume_maybe()` — tolerant parsers for messy CSV data.
- SSL: server creates an SSL context with `certifi` if available, else falls back to unverified — needed for Twelve Data API calls from system Python.

## Frontend Architecture (`Big_movers.html`)

### Layout (CSS Grid)

```
.app (grid: auto + 1fr)
├── .topbar — logo, brand-meta, filter pill bar, action buttons (theme, +Add)
└── .main (grid: clamp(340px,28vw,420px) + 1fr)
    ├── .table-panel — title block + sort bar + scrollable card-style stocks list
    └── .chart-panel — chart-topbar + LWC chart + drawing canvas overlays + study drawer
```

### Chart Stack

Lightweight Charts v3.8.0 instances:
- `chart` — main chart
- `candleSeries` — candlesticks (default)
- `ohlcSeries` — OHLC bars (toggle)
- `priceSeries` — pointer to active price series
- `volSeries` — volume histogram (overlaid bottom 15% by default)
- `volChart` — separate volume pane chart instance (created when `volPaneEnabled`, line ~3064)
- `spyLineSeries` / `spyCandleSeries` / `spyBarSeries` — SPY benchmark overlay (3 modes)
- MA series — created on demand from `maList` config

**Drawing system** (~7 tools): rendered on `#draw-canvas` overlay. Coordinate transforms via `time2p()` / `price2p()` using LWC API. **Drawings are keyed by `drawKey()` which returns `moveKey(currentMoveRow)` (compound `symbol_year`) with fallback to `currentSymbol`** for backward compatibility.

**Custom crosshair**: `#crosshair-overlay` is a separate canvas that scales for `devicePixelRatio` (line ~2812). The main chart uses `CrosshairMode.None` so this overlay handles it.

### Critical State Variables

```javascript
let allRows = [];          // From /api/results
let filtered = [];         // After applyFilters()
let activeIdx = 0;         // Current row in filtered
let currentMoveRow = null; // Full row object for selection
let currentSymbol = '';    // Symbol string
let currentBars = [];      // OHLCV array
let currentTF = 'D';       // Timeframe: D/W/M

let drawings = {};         // { moveKey: [drawingObjects] }
let metadata = {           // Persisted study data
  version: 1,
  customTags: [],
  items: { 'SYMBOL_YEAR': { tags, rating, direction, notes } }
};
let maList = [];           // Moving average configs (saved to localStorage bm_cfg)
```

### Key Functions & Line Numbers (approximate, may shift with edits)

| Function | ~Line | Purpose |
|----------|-------|---------|
| `moveKey(r)` | ~1280 | Returns `${symbol}_${year}` compound key |
| `getMeta(r)` / `setMeta(r, patch)` | ~1290 | Read/write per-move metadata |
| `loadMetadata()` / `saveMetadata()` | ~1430 | Persist via /api/metadata |
| `drawKey()` | (helper) | Returns moveKey or fallback symbol for drawings |
| `redrawAll()` | ~2050 | Renders all drawings on canvas |
| `addDrawing(d)` | ~2650 | Adds drawing + pushes undo state |
| `pushUndo()` | ~2640 | Snapshots drawings for undo |
| `loadResults()` | ~3510 | Fetches results CSV |
| `populateTagFilter()` | ~3515 | Populates topbar tag filter dropdown |
| `applyFilters()` | ~3520 | Filters allRows → filtered (uses metadata for tag/dir/rating) |
| `applySort()` | ~3540 | Sorts and reconciles active row after filter change |
| `renderTable()` | ~3590 | Renders stocks list (3-line card layout in current redesign) |
| `renderStudyCell(r)` | ~3573 | Renders rating badge + direction pill + tag mini-pills |
| `fmtPeriod(low, high)` | ~3585 | Formats dates as "Jan 05 → Jun 18" |
| `selectRow(i)` | ~3606 | Loads bars, sets chart data, applies markers, redraws |
| `toggleStudyPanel()` / `updateStudyPanel()` | ~3673 | Study drawer open/refresh |
| `renderStudyTags()` | ~3703 | Tag chip checkbox grid in drawer |
| `takeScreenshot()` | ~3800 | Composites chart + drawings + volume + header/footer → PNG download |
| `setTimeframe(tf)` | ~1937 | Switches D/W/M (re-enters selectRow) |
| `saveSettings()` | ~1405 | Persists global config to localStorage `bm_cfg` |
| `initChart()` | ~2926 | Creates LWC instances |

### Persistence Layers

| Storage | Contents | Format |
|---------|----------|--------|
| `drawings.json` (server) | Per-move drawings | `{ moveKey: [drawings] }` |
| `metadata.json` (server) | Tags, rating, direction, notes per move | `{ version, customTags, items: { moveKey: {...} } }` |
| `big_movers_result.csv` | Precomputed setups + manually added tickers | Standard CSV |
| localStorage `bm_cfg` | Global chart config (log scale, chart type, MAs, etc.) | JSON |
| localStorage `bm_theme` | `light` or `dark` | String |
| localStorage `bm_filter_views` | Saved named filter combinations | `{ name: filterValues }` |
| localStorage `bm_default_view` | Name of default view to apply on load | String |
| localStorage `ma_open` / `toolbar_collapsed` | UI panel states | String |

### Boot Sequence (line ~3895)

```
load → apply theme → initChart() → loadDrawings() → loadMetadata()
     → populateTagFilter() → load filter views (apply default if set) → loadResults()
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Arrow Up/Down | Prev/next ticker in filtered list |
| Alt+V/H/A/R/S/T/N/M | Drawing tools (pan, hline, line, ray, seg, text, note, measure) |
| Esc | Cancel current tool |
| Delete/Backspace | Delete selected drawing |
| Ctrl+Z / Cmd+Z | Undo |
| Ctrl+Shift+S | Screenshot |

The `inInput` check (line ~2728) skips shortcuts when focus is in INPUT, SELECT, or TEXTAREA.

## Implemented Features (Phases 1-5 + extras)

1. **Per-move metadata system** — tags, rating (A-E), direction (long/short), notes
2. **Compound `moveKey()`** — drawings and metadata both keyed by `symbol_year` so same ticker in different years stays separate
3. **Study drawer** — single panel with rating, direction, tag chips, custom tag input, notes textarea, TradingView link, Extend to Today, Remove Ticker
4. **Filtering** — tag, direction, min rating filters compose with existing min%, symbol, year. Active-row reconciliation handles selection when filtered out
5. **Saved filter views** — name a filter combination, mark one as default to auto-load on startup (localStorage)
6. **Twelve Data API integration** — fetch new tickers with date range, extend existing tickers to today (auto-detects last date, dedupes)
7. **Remove ticker** — confirmation modal, removes from results CSV, optionally deletes OHLCV file, cleans metadata + drawings
8. **Screenshot** — `chart.takeScreenshot()` + draw canvas + volChart + crosshair-overlay composited into one PNG with header (symbol, gain, rating, tags) and footer (notes truncated to 120 chars)
9. **Editorial dark theme redesign** — Fraunces serif for display headings, JetBrains Mono for stock symbols and data, Plus Jakarta Sans for UI. Warm cream/gold accents on deep black

## Branches

- `main` — clean state at start of work
- `feature/study-system` — Phases 1-3 + screenshot/filters/fetch (this is what was merged from parallel agent worktrees)
- `feature/ui-redesign` — editorial dark theme redesign (current working branch)
- `feature/metadata-endpoint` — server-only endpoint addition (subset of study-system)
- `feature/study-system-frontend` — frontend half of phases 1-3 (subset)

GitHub remote: `my-origin` → https://github.com/wongchiuchun/big_movers (account: wongchiuchun)

## Known Gotchas

1. **Drawings vs metadata keys**: Drawings use `drawKey()` which falls back to plain symbol if `currentMoveRow` is null. Metadata uses `moveKey(row)` strictly. If you add code that touches drawings, use `drawKey()` not `currentSymbol` directly.

2. **`setTimeframe()` re-enters `selectRow()`**: Be careful when implementing per-ticker chart settings — naive "restore on row select" logic creates infinite loops. Use a silent apply path with a flag to skip resave.

3. **HiDPI canvas mismatch**: `#draw-canvas` is sized in CSS pixels (`resizeCanvas()`, line ~2190), while `#crosshair-overlay` scales for `devicePixelRatio`. When compositing for screenshots, account for both.

4. **`volChart` is a separate chart instance** when volume pane mode is on. `chart.takeScreenshot()` does NOT include it. Screenshot code stacks them manually.

5. **Single HTML file is ~3900 lines**: Use Grep to find functions before reading. The file is manageable but read-and-edit cycles are slow.

6. **CSV column 0 is sometimes empty/index**: The "new" format reader expects 7 cols with date in column 1; "noindex" expects 6 cols with date in column 0. New tickers from Twelve Data are written in "noindex" format.

7. **`inInput` check** must include TEXTAREA, not just INPUT/SELECT, otherwise typing notes will trigger drawing shortcuts.

8. **Server SSL**: System Python lacks certificates by default. The fetch-ticker endpoint creates an SSL context with `certifi` fallback to unverified. Don't change this without testing.

9. **The user's `python3` is the wrong one** — it's in `.browser-use-env` and lacks Flask. Always use `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3`.

## Design System (current redesign)

**Fonts**:
- Display (headings, brand): `Fraunces` italic 500-600, opsz 144
- UI (labels, buttons, body): `Plus Jakarta Sans` 400-700
- Mono (data, symbols, prices, dates): `JetBrains Mono` 400-600

**Colors** (dark, default):
```
--bg: #0c0d10           Deep black with hint of blue
--bg2: #131418          Surface 1
--bg3: #181a20          Surface 2
--bg4: #1f2229          Surface 3 (inputs)
--border: #262932
--border-bright: #353944
--text: #f4f1e8         Warm cream (not pure white)
--text-2: #b8b5ad
--muted: #7a7e8a
--accent: #d4a574       Warm gold
--accent-cream: #ede4cf Brand cream
--green: #6ee7b7        Mint bull
--red: #fb7185          Coral bear
```

Light theme uses warm cream tones (`#faf8f3` bg, etc.) — see `[data-theme="light"]` block.

**Subtle film grain** is applied via SVG noise on `body::before` at 0.022 opacity for paper-like atmosphere.

## Plan File

The full implementation plan from the original session is at:
`/Users/raywong/.claude/plans/reflective-discovering-lamport.md`

Phases 1-5 are complete. Phase 6 (deferred) includes server-side screenshot storage, batch zip export, TradingView widget embed, and Lightweight Charts v5.x upgrade.
