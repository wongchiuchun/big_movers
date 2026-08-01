# Annotation Versions and Manual Leg Reviews Design

**Date:** 2026-08-01  
**Status:** Approved for implementation planning

## Summary

Add two independent study features:

1. Up to three drawing versions per chart, selectable from the chart topbar.
2. Optional manual leg reviews that add date-range-specific notes below the existing AI Review without replacing the chart's main Study Notes or AI content.

The implementation must preserve all existing annotations and keep the chart toolbar contained at narrow widths.

## Goals

- Let a user revisit a chart and create a fresh annotation version without deleting earlier work.
- Let a user switch among drawing versions 1, 2, and 3 with one click.
- Let a user reset only the active drawing version after an explicit confirmation.
- Let a user select chart periods as manually reviewed legs and attach free-text detail notes.
- Preserve the existing overall Study Notes, AI Review, tags, ratings, and other chart-level study data as shared content.
- Preserve current behavior for existing drawing data and all charts that use only version 1.
- Prevent new topbar controls from overflowing or escaping their bordered container.

## Non-goals

- Showing multiple drawing versions at the same time.
- Naming, duplicating, merging, reordering, or exporting drawing versions.
- More than three drawing versions per chart.
- Replacing or editing AI-generated review legs.
- Automatically asking AI to review a manually selected leg.
- Creating structured per-leg forms, ratings, setup fields, entries, or stops.
- Replacing the existing chart-level Study Notes.

## Terminology

- **Drawing version:** One mutually exclusive set of chart annotations. Only the active version is visible and editable.
- **Manual leg review:** A user-selected start/end range plus a free-text detail note.
- **Main Study Notes:** The existing overall notes field for the chart. It remains unchanged and independent from manual leg reviews.

## Current State

Drawings are persisted in `drawings.json` as a map from move key (`SYMBOL_YEAR`) to a flat drawing array. Rendering, hit-testing, editing, deletion, undo, clearing, and screenshots all use that array.

AI reviews are persisted separately in `reviews.json`. Their legs already contain start/end dates, and the Study interface can highlight an AI leg's chart range on hover. AI review content is currently read-only in the Study interface.

User-authored chart metadata, including the main Study Notes, is persisted in `metadata.json` under the same move key.

## Drawing Version Data Model

Keep the current top-level drawing schema. Add an optional `version` field to individual drawings:

```json
{
  "ABVX_2025": [
    { "id": 31, "type": "note", "version": 1 },
    { "id": 1501, "type": "arrow", "version": 2 }
  ]
}
```

Rules:

- Valid versions are integers 1, 2, and 3.
- A drawing with no `version` field is treated as version 1.
- Existing drawings are not rewritten merely because a chart is loaded or a version is selected.
- New drawings receive the active version explicitly.
- Invalid saved versions are treated as version 1 so malformed data cannot make drawings disappear.
- Drawing IDs remain globally unique under the existing counter behavior.

This additive model avoids a bulk migration of the existing drawing library and keeps existing server endpoints and maintenance scripts compatible with the top-level `SYMBOL_YEAR -> array` shape.

## Drawing Version Module and Interface

Place a seam between raw persisted drawing arrays and drawing interactions. Its small interface should provide the active drawing set and scoped mutations while hiding legacy-version normalization.

Conceptual interface:

```text
getActiveVersion(moveKey) -> 1 | 2 | 3
setActiveVersion(moveKey, version)
getActiveDrawings(moveKey) -> Drawing[]
addToActiveVersion(moveKey, drawing)
replaceActiveVersion(moveKey, drawings)
resetActiveVersion(moveKey)
```

Rendering, hit-testing, selection, dragging, editing, delete, undo, clear/reset, and screenshots must cross this seam rather than independently filtering raw arrays. This concentrates version rules in one place and reduces the risk of an operation affecting a hidden version.

Active selection is remembered per chart for the current app session. A fresh application load defaults every chart to version 1.

Undo entries are keyed by both move key and drawing version. `Ctrl/Cmd+Z` searches for the newest entry matching the chart and the version that is active when undo is invoked. Switching versions therefore does not consume or apply another version's undo history.

## Version Switching Behavior

- The chart topbar contains a single non-breaking group labeled `Versions` with buttons `1`, `2`, `3`, and a compact reset icon.
- The topbar reset icon replaces the vertical drawing toolbar's existing clear-all control; the interface must not expose two destructive drawing-clear actions.
- Clicking an unused version immediately opens a blank annotation canvas; no creation dialog is required.
- Only the active version is rendered and available to hit-testing or editing.
- Switching versions clears the selected drawing, cancels any half-finished drawing, restores normal chart interaction, and redraws the canvas.
- Study Notes, tags, ratings, AI reviews, manual leg reviews, chart settings, indicators, and simulation state do not change when switching versions.
- Screenshots capture only the currently visible drawing version because they already composite the visible drawing canvas.
- Drawing lock and text/note visibility settings continue to apply globally to whichever version is active.

## Reset Behavior

The existing destructive clear behavior becomes an active-version reset action.

- Activating reset opens a confirmation that names the chart and version, for example: `Reset annotation version 2 on ABVX 2025?`
- The message states that other versions are unaffected.
- Cancel makes no changes.
- Confirm removes only drawings assigned to the active version.
- A confirmed reset pushes an undo snapshot first, allowing one-session recovery with `Ctrl/Cmd+Z`.
- Undo restores only the version captured by that reset, not the complete raw drawing array.

The reset action must never remove Study Notes, AI reviews, manual leg reviews, or drawings in other versions.

## Responsive Topbar Layout

The approved layout places the version group in the chart topbar rather than lengthening the vertical drawing toolbar.

Requirements:

- The selector is one `flex: 0 0 auto` group so its internal buttons never split across rows.
- Individual version buttons retain a readable fixed target size and do not shrink into narrow slivers.
- The chart topbar continues to use wrapping and has no fixed height.
- When space is limited, the complete version group moves to the next topbar row.
- The topbar's bottom border expands with wrapped content; no button may render outside it.
- Existing topbar controls and the vertical drawing toolbar remain usable at narrow widths.
- The reset control is visually distinct from normal version switching without dominating the toolbar.

## Manual Leg Review Data Model

Store manual leg reviews as additional chart metadata, separate from both the main Study Notes and AI review:

```json
{
  "manualLegs": [
    {
      "id": "stable-local-id",
      "start": "2025-07-16",
      "end": "2025-08-29",
      "notes": "Free-text detail about this section."
    }
  ]
}
```

Rules:

- `start` and `end` use normalized `YYYY-MM-DD` dates.
- If the user selects the later point first, normalize the earlier date into `start`.
- Legs are sorted by start date, then end date.
- Display numbers are derived from sorted order and are not persisted.
- Deleting a leg automatically renumbers the remaining display list.
- Overlapping legs are allowed; manual review is descriptive rather than a trading-state model.
- Invalid saved ranges are skipped in the interface without preventing the rest of the Study panel from loading.

## Manual Leg Review Interaction

Add a `Manual Leg Reviews` subsection directly below the existing AI Review area.

The subsection remains available when the chart has no AI review. Its placement is after the AI Review area in the Study layout, not conditional on AI review content existing.

- When no manual legs exist, show only a compact `+ Add manual leg` action and no empty form.
- Starting the action enters a dedicated two-point chart-selection mode.
- The user selects a start and end date on the chart.
- Selection mode provides an obvious visual preview and can be canceled with Escape.
- Completing a valid range creates the leg, sorts all legs chronologically, and opens the new leg's free-text notes area.
- Each item displays `Leg N`, its date range, and one free-text review box.
- Clicking or hovering a leg highlights its chart range using the existing leg-highlight behavior.
- Manual leg notes save through the existing debounced metadata persistence path.
- A delete action requires confirmation and removes only that manual leg.

The existing main Study Notes remain the overall chart review. Manual leg notes provide additional period-specific detail and never replace, concatenate into, or synchronize with the main notes. AI review data remains read-only and unchanged.

## Interaction Conflicts

- Starting manual leg selection cancels any pending drawing and temporarily prevents normal drawing clicks.
- Starting a drawing tool cancels manual leg selection.
- Simulation pick modes retain priority over drawing and manual-leg selection, matching current chart event behavior.
- Changing chart, timeframe, or annotation version during selection cancels the incomplete leg.
- Weekly and monthly views map selected points to their underlying normalized chart dates using the existing nearest-bar date behavior.

## Persistence and Failure Handling

- Continue using the existing atomic JSON server writes for `drawings.json` and `metadata.json`.
- Do not change the `/api/drawings` or `/api/metadata` endpoint shapes.
- Preserve unknown drawing and metadata fields during updates.
- If a drawing save fails, keep the current in-memory view and use the existing lightweight feedback behavior.
- If manual-leg metadata saving fails, preserve the typed text in the open interface and show a non-blocking save error rather than clearing it.
- Loading malformed version or manual-leg data must degrade to version 1 or skip only the invalid leg.

## Minimal Automated Verification

Keep new automated coverage intentionally lean:

1. One focused drawing-version test covering legacy drawings as version 1, switching, scoped add/edit/delete behavior, and active-version-only reset/undo.
2. One focused manual-leg test covering normalized selection, chronological numbering, independent notes, and deletion renumbering.
3. One focused toolbar regression check confirming the version selector is a non-shrinking group inside a wrapping, non-fixed-height topbar.
4. One final run of the existing test suite.

Avoid broad browser automation or exhaustive per-drawing-type duplication. Existing drawing tests continue to cover geometry and tool-specific behavior.

## Manual Verification Checklist

- Open a chart with legacy drawings and confirm they appear in version 1.
- Add different drawings to versions 1, 2, and 3; switch repeatedly and confirm isolation.
- Reset version 2, cancel once, then confirm; verify versions 1 and 3 are untouched.
- Undo the confirmed reset during the same session.
- Narrow the chart until the topbar wraps; verify the complete version group stays inside the border.
- Add manual legs in reverse chronological order and confirm automatic sorting and numbering.
- Enter distinct notes in the main Study Notes and each manual leg; reload and confirm all remain independent.
- Delete a middle manual leg and confirm the remaining legs renumber without changing their notes.
- Confirm AI review legs and content remain unchanged.

## Acceptance Criteria

- Every existing drawing remains visible in version 1 without a bulk data migration.
- Each chart supports exactly three mutually exclusive drawing versions.
- All drawing operations affect only the active version.
- Reset is confirmed, active-version-only, and undoable during the session.
- The version selector remains contained at wide and narrow chart widths.
- Manual leg reviews are optional, chronologically numbered, and use only a free-text detail box.
- Manual leg notes remain independent from the existing main Study Notes and AI Review.
- Existing chart, drawing, Study, review, screenshot, and simulation behavior continues to pass the current test suite.
