# Chart Arrow Drawing Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a blue, persistent, one-click chart arrow annotation with up, down, left, and right direction choices.

**Architecture:** Extend the existing custom canvas drawing type system in `Big_movers.html`. Arrow annotations use the same time/price coordinate conversion, persistence collection, undo stack, selection, dragging, locking, deletion, and simulator visibility rules as existing drawings.

**Tech Stack:** Vanilla JavaScript, HTML Canvas 2D, TradingView Lightweight Charts coordinate APIs, browser localStorage.

---

### Task 1: Add and wire the arrow annotation

**Files:**
- Modify: `Big_movers.html`

- [x] **Step 1: Add the toolbar control and settings**

Rename the existing `tool-pan` label to “Pan / Select.” Add a `tool-arrow` group with a blue arrow icon, blue color input, and an up/down/left/right direction select. Add `arrow` to `toolSettings`, popup binding, saved-setting restoration, `TOOLS`, and the `Alt+W` keyboard map.

- [x] **Step 2: Add arrow geometry and canvas rendering**

Add a geometry helper that produces a filled arrow silhouette with its tip at the stored chart coordinate and visually matches the existing start/end chart-marker size. Render it in `drawOne()`, using the saved direction/color and the existing yellow selected state.

- [x] **Step 3: Integrate one-click placement and simulator filtering**

When the arrow tool receives a valid chart click, add `{type:'arrow', time, price, color, direction}`, persist it, and return to pan mode. Treat `d.time` as a timed drawing in `_drawingExceedsCutoff()`.

- [x] **Step 4: Integrate selection and dragging**

Hit-test the visible arrow bounds with a small tolerance in `getHitPart()`. Move its top-level time/price coordinate in `applyDrag()`, thereby reusing selection, delete, undo, locking, and save behavior.

- [x] **Step 5: Perform focused verification**

Run:

```bash
node -e "const fs=require('fs'),vm=require('vm'),s=fs.readFileSync('Big_movers.html','utf8'),blocks=[...s.matchAll(/<script>([\\s\\S]*?)<\\/script>/g)]; blocks.forEach((m,i)=>new vm.Script(m[1],{filename:'inline-'+i+'.js'})); console.log('OK',blocks.length)"
git diff --check
git status --short
shasum -a 256 drawings.json metadata.json
```

Expected:

- Syntax output is `OK 7`.
- `git diff --check` has no output.
- Status contains only `Big_movers.html`, the implementation plan, and the two pre-existing user-modified files `drawings.json` and `metadata.json`.
- The user-data file hashes are observed only for scope awareness; they may change concurrently while the user runs the app. Feature edits and staging must still exclude both files.

Do not run the broader automated test suite, per user instruction.

- [x] **Step 6: Commit the implementation**

```bash
git add Big_movers.html docs/superpowers/plans/2026-07-28-chart-arrow-drawing-tool.md
git commit -m "feat: add chart arrow drawing tool"
```

### Task 2: Add consistent arrow color presets

**Files:**
- Modify: `Big_movers.html`
- Modify: `docs/superpowers/specs/2026-07-28-chart-arrow-drawing-tool-design.md`

- [x] Add blue (`#2196f3`), orange (`#ff6b35`), and yellow (`#f5c842`) swatches to the arrow popup.
- [x] Keep the custom color input and synchronize it with preset selection.
- [x] Show which preset is selected and update the toolbar arrow icon to the active color.
- [x] Restore the swatch, custom input, and icon from saved arrow settings.
- [x] Run the focused inline-script syntax check and `git diff --check`.
- [x] Commit only the HTML and feature documentation; exclude `drawings.json` and `metadata.json`.
