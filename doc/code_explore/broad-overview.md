# Codebase Overview: Big Movers

> Generated: 2026-06-11 | Mode: Broad Exploration

## Quick Reference
- **Tech Stack:** Python 3.13 + Flask (stdlib-only backend, ~1,036 lines) · Single-file HTML/CSS/JS frontend (`Big_movers.html`, ~29,344 lines) · Lightweight Charts v3.8.0 (CDN) · Local CSV/JSON data
- **Entry Points:** `Big_Movers_Start.command` (double-click launcher) or `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py` → http://localhost:5051
- **Tests:** `tests/sim_shorts.test.cjs` (Node runner, 9 cases — currently red, awaiting SHORTS_PLAN P0)
- **Python:** ALWAYS use `/Library/Frameworks/Python.framework/Versions/3.13/bin/python3` (has Flask), not shell default

## Project Structure
```
big_movers/
├── Big_movers.html            # Entire frontend (~29.3k lines, no build step)
├── Big_movers_server.py       # Flask file server + 14 API endpoints
├── big_movers_result.csv      # 1,529 big-mover moves, 2000–2026 (year, symbol, gain%, low/high date+price, avg vol)
├── collected_stocks/          # ~971 per-ticker daily OHLCV CSVs (Twelve Data; raw, NOT split-adjusted)
├── SPY Historical Data.csv    # Benchmark (special format, cached server-side)
├── drawings.json              # Per-move chart annotations {SYMBOL_YEAR: [drawings]}
├── metadata.json              # Per-move tags/rating/direction/notes {version, customTags, items}
├── ai_classifications.json    # Per-move detector output (8 setup detectors, scores, criteria met/failed, pivot)
├── reviews.json               # Structured per-leg AI/human reviews (snapshot stats, legs, style_fit, myth_bust_notes)
├── setup_definitions.json     # Reference library: 8 setups (VCP, C&H, Flat Base, DB, HTF, EP, Gap&Go, Pocket Pivot)
├── classifier/                # Python setup detectors (pipeline, indicators, pivot, scoring, setups/*.py)
├── classify.py                # CLI entry for classifier → ai_classifications.json
├── tools/                     # analyze_move.py (canonical gap dates), check_note_dates.py, check_annotation.py
├── tests/                     # sim_shorts tests (red)
├── normalize_dates.py / cleanup_cross_year.py  # one-off data cleaners
└── *.md plans                 # FEATURE_PLAN, ROADMAP, SHORTS_PLAN, REVIEW_FLYWHEEL_PLAN, SIM_FEATURE_PARITY, STATS_DATA_GUIDE, ANNOTATION_TRACKER, REVIEW_GUIDE
```

## Architecture
Thin Flask server serves the HTML and persists JSON/CSV with atomic writes (`.tmp` + `os.replace`). ALL application logic — charting, drawing, filtering, the entire simulation engine — lives browser-side in the single HTML file. Three sim modes share one engine (`Sim.createSim / advanceTo / queueAction`): **Individual sim** (single ticker walk-through with stops, legs, R-multiples, MFE/MAE), **Blind sim** (`SimBlind`: hides symbol/dates, "Day ±N" labels), and **PortSim** (multi-position portfolio with cash ledger, short proceed-locks, setup wizard, per-card charts — organized as 17 "tracks" A–S, lines ~17086–29015).

## Key API Endpoints (Big_movers_server.py)
| Endpoint | Purpose |
|----------|---------|
| `/api/results` | results CSV as JSON |
| `/api/ohlcv?symbol=X` | OHLCV bars (3 CSV layout auto-detect; SPY/NDQ special-cased) |
| `/api/drawings`, `/api/metadata`, `/api/reviews[/<key>]` | GET/POST JSON stores |
| `/api/indicators?symbol=X` | server-computed MA/EMA/RSI/ATR/ADR/RS-vs-SPY/swings (classifier/indicators.py) |
| `/api/pivot`, `/api/ai-classifications[/override]`, `/api/setup-definitions` | classifier data |
| `/api/fetch-ticker`, `/api/add-result`, `/api/remove-ticker` | Twelve Data fetch/extend, CSV row mgmt |

## Frontend Section Map (Big_movers.html)
| Lines | Section |
|-------|---------|
| 1–5050 | CSS (design system, sim/PortSim/review/calendar styles) |
| 5051–6220 | HTML (topbar, table, chart, study drawer, all modals) |
| 6221–6550 | Global state + boot (theme → initChart → loadDrawings → loadMetadata → loadResults → selectRow(0)) |
| 6550–9180 | Chart + drawing core (initChart ~8417, redrawAll ~7582, 7 tools, undo, hitTest) |
| 9180–10370 | Table/filtering/fetch/screenshot/filter-views |
| 10370–10897 | **Sim core engine** (createSim, advanceTo, computeDerived, Sim.Direction, Sim.ShortLocks) |
| 10897–16829 | Sim.UI + Sim.Ctrl (playback, hero, stops, summary modal) + SimBlind (~13672) |
| 16829–17071 | Sim.Review + SimStats (localStorage `bm_stats_sessions_v3`) |
| 17086–29015 | **PortSim tracks A–S** (cash ledger, wizard, controller ~20115, review modal ~26391, export) |

## Persistence
- **Server JSON:** drawings, metadata, reviews, ai-classification overrides (atomic writes)
- **localStorage:** `bm_cfg` (chart settings), `bm_theme`, `bm_filter_views`/`bm_default_view`, `bm_saved_sims_v1` (≤200 scenarios), `bm_sim_review_<runInstanceId>` (per-attempt notes), `bm_stats_sessions_v3` (lifetime sim stats, v3 schema with structured review sub-object), PortSim portfolio saves

## Key Data Schemas
- **moveKey:** `${symbol}_${year}` everywhere. Drawings use `drawKey()` (falls back to bare symbol) — don't mix.
- **SimStats v3 session:** `{v:3, review:{session:{emotionalScore, regimeFelt, ...}, legs:{[tradeId]:{setupType, conviction, planFidelity, thesis, ...}}}}`
- **ai_classifications:** per move `{pivot:{pivot_date, base_*, breakout_rel_vol}, ai_all_detector_results:[{setup, matched, score 0–100, criteria_met[], criteria_failed[]}]}`
- **reviews.json:** `{snapshot:{ema10/20_adherence_pct, worst_drawdown_pct, sma50_touches, big_gaps[]}, legs:[{setup, entry, stop, tradable, rationale}], style_fit, myth_bust_notes}`

## Gotchas
1. `setTimeframe()` re-enters `selectRow()` — infinite-loop risk with naive restore logic
2. `volChart` is a separate LWC instance; `chart.takeScreenshot()` excludes it
3. `#draw-canvas` is CSS-pixel, `#crosshair-overlay` is DPR-scaled
4. reviews.json prose may hallucinate dates — run `tools/analyze_move.py SYMBOL [YEAR]` before writing dates
5. CSV data is NOT split/dividend adjusted (documented in ROADMAP)
6. Fetch-ticker SSL uses certifi-with-unverified-fallback — don't change blind

## Plan-Docs Status (as of 2026-06-11)
- **REVIEW_FLYWHEEL_PLAN:** Phases 0–5,7 ✅ shipped; Phase 6 (frequency gate) deferred by design
- **FEATURE_PLAN (all queued, none shipped):** ① hide future bars (top priority, training contamination), ② stop presets, ③ trail strategies, ④ position sizing rules, ⑤ decision log. Recommended order 1→5→2→4→3
- **SHORTS_PLAN:** ✅ FULLY IMPLEMENTED — verified 2026-06-11: `node tests/sim_shorts.test.cjs` → 29/29 pass (P0–P8 incl. stop presets, EMA trails, short locks, backward-compat). The plan doc's "not started" framing is stale; treat as shipped
- **SIM_FEATURE_PARITY (untracked file):** PortSim lacks per-leg summary modal, per-leg notes/MD export, replay button; individual sim lacks benchmark line. Awaiting user decisions

## Loose Ends
1. 12+ `drawings.json.bak*` files cluttering root (manual batch backups)
2. 20 modified `collected_stocks/*.csv` uncommitted + `SIM_FEATURE_PARITY.md` untracked
3. 3 abandoned `.claude/worktrees/agent-*` worktrees; stale remote feature branches
4. `Chart_Studies_mockup.html` (1,161 lines) — likely dead design mockup
5. `.gitignore` has `*.bak` but the drawings backups predate it / naming doesn't match (`.bak_before_*` suffixes)
6. Stale plan docs: SHORTS_PLAN reads as "not started" but is fully shipped (29/29 tests pass); FEATURE_PLAN item ② (stop presets) also shipped with that branch

## Open Questions
- Is Chart_Studies_mockup.html still wanted as a design reference?
- Should extended ticker CSVs be committed routinely (data drift policy)?
