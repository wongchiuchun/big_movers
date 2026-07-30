# Chart Circle Drawing Tool

## Goal

Add a persistent, resizable perfect-circle annotation to the existing chart drawing toolbar. The circle highlights a chart area without obscuring the candles and follows the drawing system's existing selection, editing, persistence, and simulation-safety behavior.

## Chosen Approach

Represent a circle with two chart-coordinate anchors:

- `p1` is the centre.
- `p2` is one point on the circumference.

At render time, convert both anchors to canvas coordinates and use their pixel distance as the radius. This keeps the rendered shape perfectly circular at every zoom level while allowing its apparent size to respond naturally when the time or price scale changes.

This is preferable to storing a fixed pixel radius, which would make the highlighted market region change when the chart is zoomed, and preferable to a bounding-box ellipse, which adds independent width and height controls the user does not need.

## Interaction

- Add a Circle tool to the drawing toolbar with `Alt+C` as its shortcut.
- First click sets the centre.
- Moving the pointer shows a live circular preview.
- Second click sets the radius and completes the circle, then returns to Pan / Select.
- Clicking the circumference selects the circle.
- A selected circle shows a centre handle and one circumference handle.
- Dragging the circumference handle resizes the circle.
- Dragging the centre handle or the circumference away from the resize handle moves the whole circle.
- Delete, Backspace, undo, drawing lock, and Clear work through the existing drawing controls.

## Appearance and Settings

- Render an outline only; do not fill the circle, so price bars remain visible.
- Default to blue (`#2196f3`), width `2`, and a solid line.
- Provide blue (`#2196f3`), orange (`#ff6b35`), and yellow (`#f5c842`) presets plus the existing custom color input pattern.
- Provide the existing width and solid/dash/dot line-style controls.
- The toolbar icon reflects the selected circle color.
- Use the existing yellow selection treatment while keeping both edit handles visible.

## Data and Integration

Store each circle in the existing drawings collection as:

```js
{
  type: "circle",
  p1: { time, price },
  p2: { time, price },
  color,
  width,
  style
}
```

Integrate `circle` into the existing tool list, settings save/load flow, preview renderer, final renderer, hit testing, drag handling, keyboard shortcuts, and toolbar popup wiring.

The existing simulation cutoff logic already evaluates both `p1.time` and `p2.time`; therefore, a circle is hidden until both anchors are within the revealed simulation period and cannot leak future chart information.

## Edge Cases

- Ignore a completed placement when the centre and edge resolve to effectively the same canvas point; keep the tool active so the user can try again.
- If either anchor cannot currently be mapped to the visible chart scales, do not render or hit-test that circle.
- Preserve old saved drawings and settings without migration; the new drawing type is additive.

## Verification

- Verify circle geometry remains perfectly round and the resize hit target matches the visible handle.
- Verify placement, preview, selection, whole-object movement, resizing, deletion, undo, lock, save/load, and settings restoration.
- Verify blue/orange/yellow presets and custom colors.
- Verify daily, weekly, and monthly timeframes plus chart zooming and price-scale changes.
- Verify future-anchored circles remain hidden during simulation playback.

No third-party dependency or server change is required.
