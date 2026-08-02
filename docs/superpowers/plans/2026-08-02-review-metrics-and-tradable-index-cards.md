# Review Metrics and Tradable Index Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show average capital deployed, profit factor, and win rate in every portfolio Review report, and add always-available SPX and NDQ trading cards under a separate Indices tab.

**Architecture:** Keep randomized/setup stocks in `_state.basket` and fixed tradable indices in `_state.indexEntries`. Add one small asset helper module as the source of truth for reserved aliases, proxy metadata, stable identities, and the combined live/retired trade-entry boundary. Reuse the existing card/trade engine for index entries and the existing `SimStats.computePortfolioMetrics` result for Review persistence and rendering.

**Tech Stack:** Vanilla JavaScript, HTML/CSS, Lightweight Charts, browser localStorage, existing `PortSim` and `SimStats` modules.

**Verification note:** The user explicitly requested no automated behavioral tests and will test manually. Do not add or run automated tests. Run only JavaScript parse checks and `git diff --check` to catch malformed source.

---

## File Structure

- Create `portfolio_assets.js`: pure asset definitions and collection helpers shared by controller, Stats, export, and Review.
- Modify `Big_movers.html`: load the helper; add tab UI/CSS; validate reserved aliases; create/hydrate index cards; route all execution/reporting consumers through the combined entry boundary; persist/render Review metrics.
- Modify `docs/superpowers/plans/2026-08-02-review-metrics-and-tradable-index-cards.md`: check off steps while executing.

### Task 1: Add the asset identity and collection boundary

**Files:**
- Create: `portfolio_assets.js`
- Modify: `Big_movers.html:1-10`

- [ ] **Step 1: Create the UMD-style asset helper**

Expose `window.PortSimAssets` in the browser and `module.exports` under Node. Define immutable index metadata:

```js
var INDEXES = [
  { key: 'index:SPX', symbol: 'SPX', dataSymbol: 'SPY', cacheSymbol: 'SPX', assetType: 'index' },
  { key: 'index:NDQ', symbol: 'NDQ', dataSymbol: 'NDQ', cacheSymbol: 'NDQ', assetType: 'index' }
];
```

Export focused helpers:

```js
indexDefinitions()                 // defensive copies of INDEXES
isReservedIndexAlias(symbol)       // SPX, SPY, NDQ, NDX, QQQ
stockKey(symbol)                   // `stock:${UPPER}`
entryKey(entry)                    // persisted key or derived asset-qualified key
liveEntries(state)                 // basket + indexEntries
allTradeEntries(state)             // liveEntries + retiredEntries
isIndexEntry(entry)                // assetType === 'index'
```

Ignore null entries and de-duplicate `allTradeEntries` by object identity only. Never de-duplicate by `entryKey`: a current stock and multiple retired generations may legitimately share `stock:SYMBOL`, and every retired object must retain its completed trades.

`entryKey` identifies the underlying asset, not one card generation. The controller separately assigns every created entry a unique `entryInstanceKey` (for example `stock:NVDA#3`) and preserves it when the entry retires. Snapshots, Review tabs, and persisted trade-to-card reconstruction use the instance key so current and retired generations never collide.

- [ ] **Step 2: Load the helper before `Big_movers.html` inline modules**

Add:

```html
<script src="portfolio_assets.js"></script>
```

after `portfolio_basket.js`.

- [ ] **Step 3: Commit the helper boundary**

```bash
git add portfolio_assets.js Big_movers.html
git commit -m "feat: define portfolio asset identities"
```

### Task 2: Add Stocks and Indices card tabs

**Files:**
- Modify: `Big_movers.html` card-grid CSS near `.portsim-grid`
- Modify: `Big_movers.html` Portfolio Simulator shell near `#portsim-grid`

- [ ] **Step 1: Add accessible tab controls and separate grids**

Insert a card-area toolbar before the grids:

```html
<div class="portsim-card-tabs" role="tablist" aria-label="Tradable instruments">
  <button id="portsim-card-tab-stocks" class="portsim-card-tab is-active" data-card-tab="stocks" role="tab" aria-selected="true">Stocks</button>
  <button id="portsim-card-tab-indices" class="portsim-card-tab" data-card-tab="indices" role="tab" aria-selected="false">Indices</button>
</div>
<div id="portsim-grid" class="portsim-grid" data-card-panel="stocks"></div>
<div id="portsim-index-grid" class="portsim-grid is-tab-hidden cols-2" data-card-panel="indices"></div>
```

Keep `#portsim-grid` as the stock grid so existing setup/reorder code remains stock-only.

- [ ] **Step 2: Add compact tab and hidden-panel styles**

Use existing colors, typography, and button states. `.is-tab-hidden` must use `display:none`; the tab bar must wrap without horizontal overflow. Index cards use the same responsive grid/Card CSS as stocks.

- [ ] **Step 3: Add idempotent tab wiring in the controller**

Create `_setCardTab(name)` and `_wireCardTabs()`:

```js
function _setCardTab(name) {
  var indices = name === 'indices';
  // toggle is-active, aria-selected, and is-tab-hidden
}
```

Switching tabs only changes visibility. It must not pause playback or call `_renderAll`. Reset to Stocks on each `_bootstrapFromConfig` and on `_hardExit`.

- [ ] **Step 4: Commit the tab shell**

```bash
git add Big_movers.html
git commit -m "feat: add portfolio stock and index tabs"
```

### Task 3: Reserve index aliases in stock setup/runtime management

**Files:**
- Modify: `Big_movers.html` `PortSim.Setup._validate`
- Modify: `Big_movers.html` `_addOrReplaceTicker` and random candidate filtering

- [ ] **Step 1: Reject reserved aliases in setup validation**

For each non-empty stock row, use `PortSimAssets.isReservedIndexAlias(sym)`. Add a row error:

```text
SPX/NDQ are available on the Indices tab
```

Do this before duplicate/pre-entry validation so users cannot create a stock/index display collision.

- [ ] **Step 2: Reject aliases in runtime add/replace**

Return the same clear error from `_addOrReplaceTicker`. Exclude all reserved aliases from `_pickRandomTickerForSim` even if they appear in `/api/results`.

- [ ] **Step 3: Stamp stock identity fields**

Both bootstrap and runtime-created stock entries receive:

```js
assetType: 'stock',
entryKey: PortSimAssets.stockKey(sym),
entryInstanceKey: _newEntryInstanceKey(PortSimAssets.stockKey(sym)),
dataSymbol: sym
```

Archive these fields in `_archiveEntry`.

- [ ] **Step 4: Commit stock/index separation rules**

```bash
git add Big_movers.html
git commit -m "fix: reserve portfolio index aliases"
```

### Task 4: Create and hydrate the fixed index cards

**Files:**
- Modify: `Big_movers.html` controller state and bootstrap lifecycle
- Modify: `Big_movers.html` card creation helpers

- [ ] **Step 1: Add state and shared card-entry construction**

Add `indexEntries: []` to `_state`. Extract the repeated stock-card construction into `_createTradeEntry(opts)` so stock and index cards share card creation, chart wiring, action rows, and bare-click behavior. Required options are display symbol, data symbol, asset type, entry key, bars, role, and host grid.

Add a per-run `_state.entrySequence` reset at bootstrap and `_newEntryInstanceKey(assetKey)` to create unique generation addresses. Index entries use `role: 'index'`, `assetType: 'index'`, fixed metadata from `PortSimAssets.indexDefinitions()`, `entryInstanceKey`, `sim: null`, `_fixedIndex: true`, and an explicit `_indexLoadState: 'loading' | 'ready' | 'unavailable'`.

- [ ] **Step 2: Render both index card shells immediately**

During bootstrap, clear/destroy both stock and index grids/entries. Create both fixed entries synchronously in `#portsim-index-grid` with empty bars and a `loading…` badge, then call `PortSim.IndexCache.ensure(def.cacheSymbol)` independently for each.

- [ ] **Step 3: Hydrate without changing the simulation timeline**

When a cache resolves:

1. confirm `_state.active` and that the entry still belongs to the current run;
2. filter only bars at or before `endDate`;
3. rebuild its `dateToBarIdx`;
4. set `lastCloseSeen` from the slice through the current date;
5. call `entry.card.setData(slice)` and set an idle badge;
6. leave `unifiedDates`, `playIdx`, `_history`, `prevEquity`, and the Positions curve untouched.

An empty/error result sets `_indexLoadState = 'unavailable'` and an `unavailable` badge while leaving the other card/simulation functional. A successful result sets `_indexLoadState = 'ready'`.

- [ ] **Step 4: Keep benchmark loading independent**

Do not change the index strip's selected benchmark behavior. Only `_state.indexBars` for the selected benchmark contributes index dates to `_buildUnifiedDates`. Tradable index hydration never calls `_buildUnifiedDates`.

- [ ] **Step 5: Destroy index cards on replay/exit**

Update bootstrap cleanup and `_hardExit` to destroy both collections and clear `indexEntries`. Replay recreates the fixed shells from scratch.

- [ ] **Step 6: Commit fixed index-card lifecycle**

```bash
git add Big_movers.html
git commit -m "feat: hydrate tradable SPX and NDQ cards"
```

### Task 5: Route the trading engine through all live entries

**Files:**
- Modify: `Big_movers.html` controller playback, snapshots, render, valuation, summary, and Stats payload
- Modify: `Big_movers.html` Positions/Track J/expanded-chart consumers that currently read `_state.basket`

- [ ] **Step 1: Add controller-local collection helpers**

Use:

```js
function _liveTradeEntries(){ return PortSimAssets.liveEntries(_state); }
function _allTradeEntries(){ return PortSimAssets.allTradeEntries(_state); }
```

Keep `_state.basket` direct access only in stock-only setup, grid layout, randomization, add/replace, archive, and reorder paths.

- [ ] **Step 2: Advance and force-close all live entries**

Change `_pushSnapshot`, `_stepBack`, `_advanceAll`, stopped/closed badge refresh, end-of-sim force-close, `_recomputeRealizedFromCash`, `_renderAll`, `_showSummary`, and open-position checks to iterate `_liveTradeEntries()` or `_allTradeEntries()` as appropriate.

Snapshots identify entries by unique `entryInstanceKey`, not display symbol or reusable asset `entryKey`, and include both index sims. Restoring a snapshot that predates asynchronous hydration must tolerate a still-empty index entry.

During playback, fixed index entries whose `_indexLoadState !== 'ready'` are skipped before date lookup and stale-badge logic. This preserves `loading…` and `unavailable` states and prevents empty shells from offering the stock Fetch/Extend path.

- [ ] **Step 3: Include indices in valuation and deployment**

Build `Sim.PortfolioValuation` inputs from all live entries. Ensure `PortSim.Positions` curve generation, open position rows, per-entry P&L series, and the shared `SimStats.computePortfolioMetrics` payload use stocks + indices + retired traded stocks where the existing path requires retired history.

Do not use collection length as a run/reset marker. Change Track Positions' marker to a stable run identity (`runInstanceId`, or start/initial plus a controller run counter) so asynchronous card hydration cannot reset the curve.

- [ ] **Step 4: Update chart-side consumers**

Replace stock-only reads in Track J marker rendering, expanded-card lookup, notes chart lookup, active-only filtering, and other trading-card consumers with `PortSimAssets.liveEntries(st)`. Stock reorder/hide synchronization stays scoped to `#portsim-grid` and `st.basket`; fixed index cards cannot be reordered, hidden, replaced, or removed.

- [ ] **Step 5: Include asset identity in Stats records**

Pass all trade entries to `SimStats.addCurrentPortfolio`. Stamp each extracted trade with `assetType`, `entryKey`, `entryInstanceKey`, `displaySymbol`, and `dataSymbol`. Persist session-level `basketAssets` or equivalent instance-key-to-asset metadata alongside existing `basketRoles`; only stock symbols enter `basketRoles` and legacy `activeSymbols` used by randomized provenance. Persist `activeEntryInstanceKeys` for every current stock and fixed index entry so reconstruction can distinguish current versus retired generations. Legacy sessions without it retain the existing `activeSymbols` fallback, while legacy index trades default to active because indices are fixed assets.

- [ ] **Step 6: Commit the combined execution boundary**

```bash
git add Big_movers.html
git commit -m "feat: trade indices through portfolio engine"
```

### Task 6: Include indices in CSV and Review without role regressions

**Files:**
- Modify: `Big_movers.html` CSV export
- Modify: `Big_movers.html` Review `_buildMeta`, `_renderOverview`, `_renderTickerTab`, rerun, print, and session reconstruction

- [ ] **Step 1: Export all trade entries**

Use `PortSimAssets.allTradeEntries(st)` for per-position rows and event logs. Add `Asset Type` to per-position/event exports while preserving display symbols. Header output reports stock basket size and tradable-entry count separately.

- [ ] **Step 2: Persist index metadata in Review snapshots**

`_buildMeta` serializes all live plus retired traded entries with `assetType`, `entryKey`, unique `entryInstanceKey`, `dataSymbol`, `cacheSymbol`, and role. Active membership is generation-safe through `activeEntryInstanceKeys`; retain stock-only `activeSymbols` for backward compatibility.

- [ ] **Step 3: Bypass basket-role resolution for indices**

In `_renderOverview` and `_synthMetaFromSession`:

```js
var role = entry.assetType === 'index'
  ? 'index'
  : PortSimBasket.resolveRole(...);
```

Filter index rows out before `countCurrentRoles`. Show `index` in the Role column. Never include index entries in mover/anchor/noise/unknown counts.

- [ ] **Step 4: Keep rerun stock-only**

Saved-review rerun rebuilds setup tickers only from entries whose `assetType !== 'index'`. The next simulation automatically recreates both index cards. Review tabs and print/PDF include index entries that traded; idle fixed index cards may appear in the live card tab but should not add empty per-ticker Review tabs unless the existing stock behavior already includes idle cards.

- [ ] **Step 5: Make Review charts proxy- and identity-aware**

Use unique tab IDs such as `t:index:SPX#2`, while rendering the display symbol as the tab label and adding `retired` when duplicate generations need disambiguation. Resolve live entries by `entryInstanceKey` across `PortSimAssets.allTradeEntries(st)` and resolve saved/view-only chart sources from persisted `dataSymbol`/`cacheSymbol`. Persist each trade's `entryInstanceKey`; `_synthMetaFromSession` groups legs by instance key, with a legacy fallback that groups by asset/display symbol only when the field is absent:

- SPX chart load/extend uses SPY data or `IndexCache.ensure('SPX')`;
- NDQ chart load uses `IndexCache.ensure('NDQ')`, preserving the server's NDQ-to-local-QQQ fallback;
- stock charts keep `/api/ohlcv?symbol=<stock>`;
- printable Review sections call the same identity-aware renderer.

Do not use a displayed-symbol-only lookup for index cards or duplicate retired generations. Notes can remain display-symbol keyed because stock setup rejects all reserved aliases.

- [ ] **Step 6: Commit reporting integration**

```bash
git add Big_movers.html
git commit -m "feat: report portfolio index trades"
```

### Task 7: Persist and render Review performance metrics

**Files:**
- Modify: `Big_movers.html` Review `_buildMeta`, `_synthMetaFromSession`, `_renderOverview`, and `_buildMD`

- [ ] **Step 1: Snapshot the existing shared metrics**

Inside `_buildMeta`, call the same source used by the end summary:

```js
var metrics = window.SimStats && SimStats.computePortfolioMetrics
  ? SimStats.computePortfolioMetrics({ basket: allTradeEntries })
  : null;
```

Persist:

```js
avgPctDeployed
tradeCount
winCount
lossCount
winRate
profitFactor              // finite number or null
profitFactorInfinite      // metrics.profitFactor === Infinity
```

When `tradeCount === 0`, persist `profitFactor: null` and `profitFactorInfinite: false` even though the shared calculator returns numeric zero. When there are extracted trades, preserve a finite zero as `0` and preserve infinity through the explicit flag. Do not recalculate from Review leg snapshots.

- [ ] **Step 2: Copy Stats metrics into reconstructed session Reviews**

`_synthMetaFromSession` copies `avgPctDeployed`, counts, and `winRate`. It sets `profitFactorInfinite` from an explicit future flag or infers it when `tradeCount > 0`, `winCount > 0`, `lossCount === 0`, and stored `profitFactor == null`.

- [ ] **Step 3: Add three Overview tiles**

Append tiles labelled `AVG CAPITAL DEPLOYED`, `PROFIT FACTOR`, and `WIN RATE`. Formatting:

- average deployment: one decimal plus `%`, otherwise `—`;
- profit factor: `—` when `tradeCount === 0`, `∞` for the flag, two decimals for finite values (including `0.00` for a nonempty all-nonwinning/breakeven set), otherwise `—`;
- win rate: one decimal plus `%`, with `W / N trades` as supporting text or in the value, otherwise `—`.

Apply positive/negative classes consistently with existing Stats: PF ≥ 1 positive, PF < 1 negative; win rate ≥ 50 positive, lower negative. These tiles automatically appear in PDF because print renders `_renderOverview`.

- [ ] **Step 4: Update dormant Markdown summary**

Add the same three values to `_buildMD` using the persisted fields and identical empty/infinity formatting.

- [ ] **Step 5: Commit Review metrics**

```bash
git add Big_movers.html
git commit -m "feat: add portfolio metrics to review report"
```

### Task 8: Source sanity checks and integration

**Files:**
- Modify: checked plan boxes in this file

- [ ] **Step 1: Parse the helper and every inline script**

Run a no-execution JavaScript syntax parse over `portfolio_assets.js` and all inline `<script>` blocks in `Big_movers.html`. Expected: no syntax errors.

- [ ] **Step 2: Inspect the final diff**

Run:

```bash
git diff --check main...HEAD
git status --short
git log --oneline --decorate main..HEAD
```

Expected: no whitespace errors; only intended files changed; all implementation commits visible.

- [ ] **Step 3: Commit plan checkbox updates if needed**

```bash
git add docs/superpowers/plans/2026-08-02-review-metrics-and-tradable-index-cards.md
git commit -m "docs: complete index cards implementation plan"
```

- [ ] **Step 4: Fast-forward merge the feature branch into local main**

From the primary worktree, verify both worktrees are clean, then:

```bash
git merge --ff-only feature/review-metrics-index-cards
```

Do not push unless separately requested.
