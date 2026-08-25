# Blind Sim Duration and Individual-Sim Parity Design

**Date:** 2026-08-25

## Goal

Update the existing Blind Sim rather than create another simulator. Blind Sim must continue to use the Individual Sim controller and trading mechanics; its only special behavior is randomized historical selection and masking of ticker, year, and absolute dates.

## Scope

- Keep the existing Blind button, `SimBlind` module, modal, masking adapter, reveal behavior, and `Sim.Ctrl.startBlindPlayback` entry point.
- Keep Blind Sim starting without a position, so the user chooses whether and when to enter during playback.
- Continue using Individual Sim's existing controls and modals for market-at-close and limit entries, adds, partial sells, stop changes and trailing, playback, rewind, expanded view, multi-leg handling, and summary/review.
- Replace the free-form "bars to simulate" input with two duration choices:
  - **4–6 months:** randomly choose 84–126 trading bars.
  - **6–12 months:** randomly choose 126–252 trading bars.
- The chosen count includes the Day 0 start candle. For a chosen count `N`, the simulation ends at `endIdx = startIdx + N - 1`; a candidate is eligible only when that index is within the loaded bars.
- Select the random duration before candidate playback begins. A candidate is eligible only when it has the full chosen playback window. Retry other ticker/start combinations rather than silently shorten the selected duration.
- Preserve the existing historical/current-year eligibility rules and the existing four-month lookback context.
- At completion or explicit reveal, restore the real ticker, year, and dates through the existing reveal path.

## Data Flow

1. The user opens the existing Blind Replay modal and selects capital, fixed R, and a duration band.
2. `SimBlind` draws a random bar count from the selected band.
3. `SimBlind` searches the existing local ticker data for a random start bar with the required lookback context and full forward window.
4. It records the blind mask state and launches the existing `Sim.Ctrl.startBlindPlayback` with the chosen start and end indices.
5. From that point onward, the ordinary Individual Sim controller owns the simulation. `SimBlind` only owns identity/date masking and reveal.

## Failure Handling

- If no eligible ticker/start window is found after bounded retries, keep the app usable and show a duration-specific message asking the user to try again or choose the shorter band.
- Do not truncate a 6–12 month choice because a selected ticker lacks data.
- Cancelling setup clears any temporary Blind state and leaves the current chart unchanged beyond the existing ticker-selection behavior.

## Verification

- Confirm the modal offers only the two duration bands and no free-form bar count.
- Confirm generated durations remain within the selected trading-bar range.
- Confirm the chosen end index is fully present in local data.
- Confirm Blind playback still routes through `Sim.Ctrl.startBlindPlayback` and retains the Individual Sim actions and controls.
- Confirm masking remains active until reveal/completion.

## Out of Scope

- A new Blind engine or controller.
- A duplicated Individual Sim setup form.
- Changes to Portfolio Sim or Entry Trainer.
- Changes to the underlying trade execution engine.
