# Simulation Chart Cutoff Design

## Goal

Prevent weekly/monthly timeframe changes and indicator toggles from revealing bars or indicator values beyond the current Individual Sim playhead.

## Scope

- Individual Sim and Blind/Random Sim paths that use `Sim.Ctrl` and the main chart.
- Main-chart daily, weekly, and monthly rendering while a simulation is active.
- User moving averages, AI moving-average overlays, SuperTrend, benchmark overlays, move markers, and drawings that are refreshed by existing chart controls.
- Normal non-simulation chart behaviour must remain unchanged.

Portfolio expanded-card charts are out of scope because they already build from each card's revealed-bar slice.

## Design

`Sim.Ctrl.getCutoffBarTime()` is the authoritative inclusive cutoff. Main-chart render functions will obtain their source bars through one simulation-aware helper that returns all bars normally and only bars whose daily date is less than or equal to that cutoff during a simulation.

When a timeframe button is used during a simulation, it will update `currentTF` and rebuild the chart from revealed bars without calling `selectRow`, which currently reloads the complete ticker. Weekly/monthly candles will therefore be aggregated only from daily bars already revealed. The existing resampler timestamps each bucket at its period start (Monday for weekly and the first day for monthly), so an incomplete active bucket remains eligible while its OHLCV contains revealed constituents only. As new daily bars play, the simulator will replace that active resampled candle and its volume rather than inserting raw daily candles into a weekly/monthly series.

Indicator refreshes will use the same revealed-bar source or cutoff date. User moving averages and SuperTrend will be computed from the active timeframe's candles after those candles have been resampled from revealed daily bars. Precomputed daily AI overlays and benchmark overlays will be filtered inclusively by cutoff before reaching their series. Catalogue low/high markers remain hidden during Sim; simulation event markers remain under `Sim.Ctrl` ownership.

Drawings retain their existing render-only cutoff contract: a timed drawing with any anchor beyond the cutoff is hidden in full, while untimed horizontal levels remain visible. Stored drawing geometry is never modified. Standard Individual Sim teardown continues to reload the selected row and restore complete chart data; chart-session-owned modes continue delegating restoration to their existing owner.

## Behaviour and Safety

- Switching D/W/M during Sim never reloads the ticker or changes the simulation state.
- No candle, indicator point, marker, or drawing dated after the playhead is rendered.
- Returning to daily view preserves the same playhead.
- Outside Sim, all controls continue using complete `currentBars` and existing behaviour.
- If an optional overlay has no revealed data, it renders empty instead of falling back to full data.

## Verification

Per user instruction, no automated tests, server, or browser session will be run. Verification is limited to source tracing, focused diff review, and whitespace checks; the user will manually exercise timeframe and indicator controls.
