# Chart Arrow Drawing Tool

## Goal

Add a persistent arrow annotation to the existing chart drawing toolbar. The arrow is placed with one click, defaults to blue, and supports four directions: up, down, left, and right.

## Design

- Rename the existing cursor control's label from "Arrow" to "Pan / Select" (its internal `pan` identifier remains unchanged), then add an "Arrow annotation" tool and settings popup beside the existing line tools.
- The popup controls color and direction. Defaults are blue (`#2196f3`) and up.
- Offer one-click color presets from the app palette: blue (`#2196f3`), orange (`#ff6b35`), and yellow (`#f5c842`), plus a custom color picker. The toolbar arrow icon reflects the current color.
- Store arrows in the existing drawings collection as:
  `{type: "arrow", time, price, color, direction}`.
- Treat the stored time/price coordinate as the arrowhead tip. The tip points in the selected direction and the shaft extends from it in the opposite direction. Size the filled silhouette to match the chart's existing start/end markers visually.
- Reuse the existing drawing behavior for selection, whole-object dragging, deletion, undo, saving, loading, locking, and simulation cutoff filtering.
- Hit-test the visible arrow silhouette with a small selection tolerance so selection and dragging agree with its rendered position.
- Extend simulation cutoff filtering to check an arrow's top-level `time` coordinate explicitly.
- Selecting an arrow uses the drawing layer's existing yellow selection treatment.
- After placing one arrow, return to the pan tool, consistent with horizontal-line placement.

## Scope

No third-party dependency, free-angle rotation, resize handle, or automated test is required. Verification is limited to focused syntax/static checks; the user will test the interaction directly.
