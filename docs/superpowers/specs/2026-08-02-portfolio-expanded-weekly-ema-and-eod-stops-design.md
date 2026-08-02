# Portfolio Expanded Weekly View, Long EMAs, and EOD Stops

Date: 2026-08-02

## Goal

Extend Portfolio Simulation with two focused capabilities:

1. Let each ticker's expanded analysis chart switch independently between daily and weekly candles and optionally show 100 EMA and 200 EMA.
2. Let every portfolio stop independently use the existing intraday trigger or an optional end-of-day close trigger.

The portfolio cards, playback timeline, and SPX/NDQ index chart remain daily.

## Expanded Chart Experience

The expanded ticker modal gets a compact analysis-control group containing:

- a `Daily | Weekly` segmented control;
- an unchecked `100 EMA` checkbox;
- an unchecked `200 EMA` checkbox.

Daily is the default. The long EMA checkboxes are off by default so their series and values are not calculated until requested. These display preferences belong to the current basket entry, not to the whole portfolio. Closing and reopening that ticker's expanded chart during the same simulation restores its selection. Replacing a ticker creates a new entry with the defaults.

The controls live in the expanded modal only. They must wrap within the header/action area at narrow widths and must not make the modal or toolbar overflow horizontally.

### Timeframe data

The expanded chart continues to receive only bars revealed through the current simulation date. Daily mode uses those bars directly. Weekly mode resamples that same revealed slice into Monday-keyed weekly OHLCV candles:

- open: first revealed daily open in the week;
- high: highest revealed daily high;
- low: lowest revealed daily low;
- close: last revealed daily close;
- volume: sum of revealed daily volume.

An incomplete current week is therefore a partial candle containing only already-revealed days. No future daily bars may enter the expanded chart. The existing `resampleBars(..., 'W')` behavior should be reused or wrapped rather than duplicated.

### EMA behavior

The existing 10, 20, and 50 EMAs remain visible. All EMA calculations use the currently selected candle array, so Weekly 100 EMA means a 100-week EMA. The 100 and 200 EMA line series should be created or populated lazily when enabled and cleared or hidden when disabled.

If the selected timeframe does not contain enough candles for an enabled EMA, the line remains empty without showing an error.

### Expanded annotations

Price lines, including active and initial stops, remain at their actual prices in both timeframes. Daily entry, exit, and R-hit markers must map to the Monday-keyed candle containing their event date when Weekly is selected. Multiple events may share a weekly candle. Switching timeframe must not mutate trade or simulation state.

## Per-Stop Trigger Mode

Each stop level gains a trigger mode:

- `intraday` is the default and preserves all current behavior;
- `close` is optional and evaluates only the bar's closing price.

Legacy or missing trigger-mode data is interpreted as `intraday` for backward compatibility.

### Trigger and fill rules

For intraday stops, existing rules remain unchanged:

- long: trigger when `low <= stop`, filling with existing stop/gap logic;
- short: trigger when `high >= stop`, filling with existing stop/gap logic.

For end-of-day stops:

- long: trigger when `close <= stop`;
- short: trigger when `close >= stop`;
- both directions fill at that bar's close, not at the stop level.

Touching the stop at the close triggers it. Existing stop percentages determine the quantity closed. Stop ordering remains direction-aware when multiple stops are active. Each stop is evaluated according to its own trigger mode.

EMA-trailing stops ratchet using the existing pre-trigger sequence and are then evaluated against the current bar's close when their mode is `close`.

### Stop controls

Portfolio Simulation shows an unchecked `Trigger only at end-of-day close` checkbox wherever a stop can be created or replaced:

- a pre-declared entry row in Portfolio Setup;
- initial entry setup;
- new-leg setup;
- the optional replacement stop entered while adding;
- Move Stop, including EMA-trailing strategies.

The shared simulation modals should expose this control only in portfolio mode unless a non-portfolio caller explicitly opts in. Submitting the form sends the selected mode with the stop data.

Move Stop replaces current unfired stops as it does today; the new stop uses the checkbox's selected mode. Directly editing only an existing stop's price retains that stop's current mode. Stop history and labels should identify EOD stops clearly enough to distinguish them from intraday stops.

## State and Data Flow

Chart preferences are display-only state on each live portfolio basket entry, for example:

```text
expandedChartPrefs: { timeframe: "D", ema100: false, ema200: false }
```

They are not part of the simulation engine, cash ledger, or playback snapshots.

Stop mode is engine state on each stop level, for example:

```text
{ id, price, pct, fired, barIdx, trail, triggerMode: "intraday" | "close" }
```

The mode must flow through entry/new-leg creation, immediate and queued stop replacement, step-back snapshots, replay configuration, stop history, CSV/review serialization, and event records. Because snapshots already deep-clone simulation data, storing the mode on the stop object makes rewind behavior deterministic.

Stop events caused by close-mode stops should record the close fill and identify the EOD trigger in their note or structured event data.

## Compatibility and Error Handling

- Existing portfolio simulations and stops continue to behave intraday.
- The normal card charts and index chart are unchanged.
- Missing or invalid chart preferences fall back to Daily with long EMAs hidden.
- Missing or unknown stop trigger modes fall back to `intraday`.
- Timeframe changes rebuild or rebind only the expanded chart series; failures should be logged without affecting the simulation.
- Controls must remain usable without horizontal overflow on narrower expanded-modal layouts.

## Test Strategy

Implementation follows focused test-driven cycles.

1. Weekly aggregation tests cover OHLCV, incomplete weeks, and cross-year input without future bars.
2. Expanded-chart tests cover Daily/Weekly selection, timeframe-specific EMA input, lazy 100/200 EMA behavior, per-entry preferences, and weekly marker mapping.
3. Stop-engine tests cover:
   - unchanged intraday long and short behavior;
   - long and short close-mode touches;
   - fills at the closing price;
   - partial close-mode stops;
   - mixed trigger modes;
   - EMA-trailing close-mode stops.
4. UI/data-flow tests cover each Portfolio Simulation stop checkbox and mode propagation through initial, new-leg, add, and move-stop paths.
5. Run the existing Node test suite, parse all inline scripts, and run `git diff --check` before completion.

Testing stays focused on these behaviors; broader manual visual testing can verify expanded-modal layout, toolbar wrapping, chart switching, and line colors.
