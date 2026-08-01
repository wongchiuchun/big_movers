# Extended Portfolio Simulation Window Design

## Goal

Let a user request a longer randomly generated Portfolio Simulation while preserving the existing default experience.

## User Experience

Add an unchecked checkbox to the randomization panel:

> Extended timeframe — random 6–9 month window (up to about 180 trading days)

The control appears with the existing Balanced basket option and affects the next click of **Randomize**.

- Unchecked: preserve the current random 120–180 calendar-day window (about 4–6 months).
- Checked: generate a random 180–270 calendar-day window (about 6–9 months and up to roughly 180 trading sessions).
- The selected start date remains in the chosen year.
- Both modes retain the existing random January–August start-month distribution.
- An extended end date may cross into the following calendar year.
- The checkbox is off by default. It does not alter manually entered start and end dates.
- The option applies to both balanced-basket and legacy same-year-only randomization.

The explanatory hint and Randomize button tooltip will describe both normal and extended ranges.

## Design and Data Flow

The existing `_makeRandomWindow` helper will accept the selected timeframe mode and remain responsible for producing random start and end dates. It will use the existing seeded random-number generator, so balanced basket attempts remain reproducible from their stored seed.

`handleRandomize` will read the checkbox once per click and pass the selected mode through both paths:

1. The same-year path calls `_makeRandomWindow` directly.
2. The balanced path injects a mode-aware `makeWindow` callback into `_resolveBalancedBasket`.

This removes the balanced resolver's duplicated date-range calculation. The balanced resolver will continue retrying distinct windows when a candidate basket lacks complete local data coverage. Standard windows retain the existing year-end cap. Extended windows do not apply that cap, allowing a simulation to cross year-end.

The basket-generation metadata, setup persistence, and simulation controller contract do not change. The generated dates already flow through the existing setup state and published configuration.

## Error Handling

Existing validation and local-coverage behavior remains in place:

- Balanced randomization retries another generated window when the basket cannot cover the requested dates.
- If no balanced basket can cover an extended window, the existing local-data failure status is shown.
- Same-year-only randomization continues through the existing setup data checks, which report missing coverage before a simulation starts.

No remote data will be fetched automatically.

## Testing

Automated tests will verify:

- The extended checkbox exists and is unchecked by default.
- Standard mode stays within the existing 120–180 calendar-day range and preserves its year-end cap.
- Extended mode stays within 180–270 calendar days and can cross into the next year.
- Same-year randomization supplies the selected mode to the shared window generator.
- Balanced randomization uses the same shared, mode-aware generator rather than its former duplicate logic.
- Existing portfolio setup and balanced-basket tests continue to pass.

## Non-Goals

- Selecting an exact number of trading sessions.
- Changing manually entered simulation dates.
- Persisting the checkbox across page reloads.
- Downloading additional market data to satisfy a long window.
- Changing basket composition rules or simulation playback behavior.
