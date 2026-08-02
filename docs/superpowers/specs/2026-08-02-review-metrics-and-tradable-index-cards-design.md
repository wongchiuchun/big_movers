# Review Metrics and Tradable Index Cards

Date: 2026-08-02

## Goal

Add three established portfolio metrics to the post-simulation Review report and make SPX and NDQ available as tradable cards on a separate card tab.

## Review Metrics

The Review Overview displays:

- average capital deployed;
- profit factor; and
- win rate, including the profitable-trade and extracted-trade counts.

The calculations reuse `SimStats.computePortfolioMetrics` and retain its existing definitions:

- Win rate keeps the existing calculator behavior: profitable extracted trade legs divided by all extracted trade legs. Breakeven legs remain in the denominator as non-wins. A live Review may include a currently open leg marked to the current close because `computePortfolioMetrics` already extracts it that way; a finalized post-simulation Review contains the force-closed legs produced by the normal completion flow. Review must not add a second filter that would make it disagree with the end summary or Stats.
- Profit factor is gross winning P&L divided by the absolute gross losing P&L across the same extracted legs used by the existing calculator. It displays infinity when there are winning extracted legs and no losing legs, including a profitable marked-to-close open leg in a live Review, and an em dash only when there are no extracted legs.
- Average capital deployed is the mean daily `max(0, (equity - cash) / equity)` over the portfolio equity curve. It is stored as percentage points in the `0–100` scale used by the current code.

The live Review snapshot stores the three metrics and their supporting counts when it builds metadata. Profit factor uses a JSON-safe pair: `profitFactor` is a finite number or `null`, while `profitFactorInfinite` explicitly records the all-win/no-loss case. Saved reviews therefore retain the values after the simulator exits. `_synthMetaFromSession` copies the session's persisted metrics and counts into reconstructed Review metadata; for existing sessions where profit factor is `null`, positive wins with zero losses identify infinity. The Overview tiles and printable PDF use these persisted fields. Legacy saved reviews without enough fields show an em dash rather than inventing a value. Any dormant Markdown builder should use the same fields so it cannot drift if re-enabled later.

## Tradable Index Cards

The card area gets a compact `Stocks | Indices` tab control. `Stocks` remains the default and shows the existing basket cards. `Indices` always contains two idle, tradable cards:

- `SPX`, backed by local SPY OHLCV data;
- `NDQ`, backed by the existing `NDQ` server/cache endpoint, whose explicit server contract prefers an NDQ historical file and otherwise serves local QQQ data.

The displayed symbol remains SPX or NDQ. A separate data-symbol or asset-type field carries the proxy mapping internally; trade records, review tabs, notes, and user-facing labels use the displayed index name.

Index cards reuse the existing portfolio card, simulation, cash ledger, sizing, entry, add, sell/cover, stop, EOD-stop, chart expansion, playback, rewind, and event-log paths. They share the same portfolio cash as stock cards. Switching tabs changes only card visibility and never pauses playback or changes trade state.

Both index card shells appear immediately and hydrate independently when their cache promises resolve. Hydration preserves the current portfolio playhead and paints data only through the current simulation date. It must not rebuild the shared timeline, reset playback, or reset the portfolio equity/deployment curve. The existing selected benchmark alone continues to contribute index dates to `unifiedDates`; the second tradable index feed does not alter the timeline, and changing the benchmark strip remains independent of either tradable card.

Both index cards are always available and do not count against the ten-stock setup limit. They consume no capital and create no trade records until the user enters a position. Stock setup rejects `SPX`, `NDQ`, `SPY`, and `QQQ` aliases as ordinary basket rows and directs the user to the Indices tab, preventing symbol collisions with the fixed index cards.

## Reporting and Basket Provenance

The live state keeps stock entries and fixed index entries in separate collections. Stock setup, randomization, generation reconciliation, the ten-row limit, stock swapping, and mover/anchor/noise provenance operate only on stock entries. A shared `allTradeEntries` boundary combines stocks and indices for advancement, rendering, snapshots, rewind, valuation, cash, position lists, force-close, deployment, performance metrics, Stats persistence, CSV export, and Review.

Traded index legs count in portfolio deployment, win-rate, profit-factor, P&L, Stats persistence, CSV output, and Review tabs exactly like stock legs. The two index cards cannot be removed, replaced, or included in stock-only rerun/setup membership.

Index cards are identified by `assetType: "index"` and an asset-qualified internal key such as `index:SPX`; stocks use keys such as `stock:NVDA`. `assetType`, the internal key, and the display/data-symbol distinction persist through saved Review metadata, SimStats sessions/trades, and session reconstruction. Existing symbol-keyed display and note paths may continue only where stock aliases are rejected and therefore cannot collide.

Index entries bypass `PortSimBasket.resolveRole` and are excluded before `countCurrentRoles` runs. Their Review role is shown as `index`, never `UNKNOWN`. Stock basket generation and randomized composition remain unchanged.

Retired stock entries and both index entries continue to be included wherever completed trades must survive card replacement or tab switching.

## Loading and Failure Behavior

The existing index cache remains the single source for SPX/NDQ data. If one feed is unavailable, its already-visible card shell shows an unavailable/empty state without preventing the stock simulation or the other index card from running.

The index strip remains a benchmark viewer and keeps its current SPX/NDQ toggle. Trading occurs through the cards on the Indices tab, avoiding a second execution interface.

## Verification Scope

The user will perform manual behavioral testing. Implementation will avoid a new automated test pass per the user's request. A lightweight syntax/diff sanity check may be used only to catch malformed source, not as behavioral verification.
