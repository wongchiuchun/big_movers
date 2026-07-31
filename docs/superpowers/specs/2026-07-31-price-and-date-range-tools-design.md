# Price Range and Date Range Drawing Tools

## Goal

Replace the temporary combined Measure tool with two persistent TradingView-style chart annotations:

- **Price Range** measures absolute and percentage price movement.
- **Date Range** counts the number of bars selected in the current chart timeframe.

Both tools must behave like the chart's other saved drawings: selectable, editable, movable, undoable, lockable, persistent, and safe during simulation playback.

## Shared Architecture

Both tools use two chart-coordinate anchors:

```js
{
  type: "priceRange" | "dateRange",
  p1: { time, price },
  p2: { time, price }
}
```

Shared helpers derive normalized visual bounds for the canvas rectangle, classify handle/interior hits, and move or resize the two anchors. Visual normalization must never reorder or mutate stored `p1` and `p2`: their semantic identity is preserved because Price Range direction is always calculated from `p1` to `p2`. Each tool has its own metrics and renderer, avoiding duplicated interaction code while keeping the visible behavior distinct.

The existing temporary `measureStart`, `measureEnd`, and `drawMeasure` path is removed. The two new tools use the standard `pendingP1` two-click placement flow and the persistent `drawings` collection.

## Toolbar and Placement

- Replace the Measure toolbar button with separate Price Range and Date Range buttons.
- Use a vertical-range icon for Price Range and a horizontal-range icon for Date Range.
- Use `Alt+P` for Price Range and retain `Alt+M` for Date Range as the replacement measurement shortcut.
- First click sets `p1`.
- Pointer movement displays a live rectangle and label preview.
- Second click sets `p2`, persists the drawing, and returns to Pan / Select.
- Reject a completed placement when the rectangle is effectively zero-sized in both dimensions; retain the first anchor so the user can try again.

## Price Range

Price Range calculates:

```text
absolute change = p2.price - p1.price
percentage change = absolute change / p1.price * 100
```

- Display percentage change as the prominent value.
- Display absolute price change as the secondary value.
- Use green styling when the change is zero or positive and red styling when it is negative.
- Render a lightly tinted rectangle, outlined border, and centered label.
- Format values compactly without hiding meaningful precision for lower-priced stocks.
- Example labels: a move from `$10.00` to `$12.50` displays `+25.00%` prominently and `+$2.50` secondarily; a move from `$0.40` to `$0.55` displays `+37.50%` and `+$0.15`; a move from `$20.00` to `$15.00` displays `-25.00%` and `-$5.00`.
- If the starting price is not finite or is zero, show the absolute change and an unavailable percentage instead of producing `Infinity` or `NaN`.
- Format an unavailable percentage as `—%` while retaining the finite absolute change.

Price Range does not show dates, elapsed time, or bar count.

## Date Range

Date Range displays only an inclusive current-timeframe bar count:

```text
bar count = number of rendered timeframe bars from the first anchor bar
            through the second anchor bar, inclusive
```

- Use the full loaded/resampled series for the active timeframe, not only bars currently inside the viewport. Panning or zooming must not change the count.
- One selected candle displays `1 bar`; all other counts display `N bars`.
- Anchor order does not affect the result.
- Switching among Daily, Weekly, and Monthly recalculates the count from the full active-timeframe series.
- Map anchors that do not land exactly on a resampled bar to the nearest bar using the drawing time-normalization helpers.
- If an anchor is exactly equidistant between two resampled bars, choose the earlier bar deterministically.
- Render a lightly tinted blue rectangle, blue outline, and centered count label.

Date Range does not show calendar days, trading-day duration, price change, or percentage change.

## Selection and Editing

- Clicking either range's outline, label, or tinted interior selects it.
- A selected range uses the existing yellow selection treatment and shows handles at `p1` and `p2`.
- Dragging either handle changes only that anchor and resizes the rectangle.
- Dragging elsewhere inside the range translates both anchors together.
- Delete, Backspace, undo, Clear, and drawing lock reuse the existing drawing behavior.
- Saved drawings load without migration; the new drawing types are additive.

## Timeframes, Zoom, and Simulation Safety

- Both tools redraw from chart-coordinate anchors, so they track time/price scaling, panning, and zooming.
- Date Range recomputes its bar count on every render using the active timeframe.
- Both tools use the existing `p1.time`/`p2.time` simulation cutoff behavior.
- Hit testing applies the same cutoff guard as rendering, so a future-anchored invisible range cannot be selected or dragged.
- If either anchor cannot currently map to the chart, do not render or hit-test that drawing.

## Verification

- Unit-test price delta/percentage calculation, including zero starting price.
- Unit-test inclusive Daily, Weekly, and Monthly bar counts, reversed anchors, same-bar selection, and nearest-bar mapping.
- Verify toolbar registration, keyboard shortcuts, placement, persistence, selection, resizing, movement, deletion, undo, locking, and cutoff wiring.
- Browser-test both tools on locally stored OHLCV data across Daily, Weekly, Monthly, zooming, panning, price-scale changes, save/reload, and simulation playback.
- Confirm the old Measure tool and its transient state are removed.

## Out of Scope

- Calendar-day or elapsed-time labels.
- A combined Date & Price Range tool.
- User-configurable colors or typography.
- Server, API, database, or third-party-library changes.
