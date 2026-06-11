# Feature Plan — Near-Term Queue

> Working doc for the next batch of features. Each section has my proposed
> design + a **Your notes** block for you to fill in your execution ideas
> before we start building. When a feature ships, move its block to a
> "Done" section at the bottom (or delete — git remembers).
>
> Order is my recommended priority by training-impact-per-hour-of-work.
> Reorder freely.
>
> Source for the strategic framing: `ROADMAP.md`.

---

## 1. Hide future bars during sim ★★★

**Status:** queued · **Priority:** highest · **Estimated effort:** ½–1 day

### What

In sim mode (single-ticker AND portfolio), clip the chart's right edge to the current playhead. Bars beyond `playIdx` are not rendered. The chart re-renders on every step.

### Why this matters

The single biggest source of training contamination in the current system. Today, the entire window is plotted — your peripheral vision sees what's coming, your pattern recognition does 30% of the work for you, and the simulation isn't really blind. Clipping the chart converts the sim from "watch it play" to "actually trade with no information advantage."

### UX sketch

- Default behavior in sim mode: show only `bars[0..playIdx]`.
- Opt-out toggle in the sim header: `👁 Reveal All` — for users who explicitly want to study with hindsight visible.
- Smooth append: when stepping forward, the new bar is added (`series.update`) — no full re-render.
- Index strip and per-card charts in PortSim follow the same rule.
- Saved-review view-only mode is unaffected (those are post-hoc reviews — the future is already settled).

### Implementation sketch

Single-ticker `Sim.Ctrl`:
- Today the chart is loaded with `currentBars` (full array). On entering sim, slice to `[0..endBarIdx]` (already done — `endBarIdx` is the user-picked end).
- Add a "playhead clip" on top: while sim is running, only `bars[0..sim.playIdx]` are visible. On `_appendBar(idx)` (`Big_movers.html` ~line 10083), instead of `series.update(bar)` use the existing setData with the slice — or just rely on `update()` and ensure no future bars were ever passed in.
- The cleanest fix: pass only `bars[0..startBarIdx+1]` to `setData` when sim starts; then `_appendBar` correctly extends one bar at a time. The "reveal all" toggle would `setData(allBars)`.

Portfolio sim:
- Each `PortSim.Card` already does `setData(bars)` once on init. Change the init-time slice to `[0..startIdx]`, then let the existing per-tick `appendBar` add bars as the sim plays.
- Index strip already does this correctly (the recent fix). Use it as the reference pattern.

### Acceptance criteria

- [ ] In single-ticker sim, on the first paint, the chart shows only history up to the entry bar — nothing to the right.
- [ ] After clicking Play, the chart extends one bar at a time in sync with `playIdx`.
- [ ] In portfolio sim, every card AND the index strip clip in lockstep with `unifiedDates[playIdx]`.
- [ ] `👁 Reveal All` toggle restores the full window without breaking the playhead.
- [ ] Drawings, markers, R-levels, MAs all follow the visible window correctly (no orphaned overlay anchored to a future bar).

### Your notes / execution ideas:

_(fill in: do you want the toggle ON by default for the first sim of a session and OFF for subsequent? Different default for portfolio vs single? Should "Reveal All" be a global setting or per-session?)_

---

## 2. Stop placement strategy presets ★★

**Status:** ✅ SHIPPED (May 2026) — implemented direction-aware as part of `SHORTS_PLAN.md` phase P2 (`feature/shorts-and-stop-presets`, merged to main). Presets live: manual, % offset, ATR offset, swing low/high (`Sim.StopRules`). Verified via `tests/sim_shorts.test.cjs`. · **Original estimate:** 2 days

### What

Replace the bare "Stop $___" input on entry modals with a strategy picker. User chooses a method; the modal pre-fills the stop value. They can still override the number.

### Why this matters

You called this out. Real swing traders don't pull stops from thin air — they place them at structurally meaningful levels (below recent swing, below the base, ATR-distance away). Modeling this in the entry flow surfaces the *decision*, not just the number. Over time you build muscle memory for which stop strategy fits which setup.

### UX sketch

In the entry modal (`showSetupModal`, `showNewLegModal`, PortSim setup row):

```
Stop strategy:  [ Manual ▾ ]
                  ├ Manual           (user types $)
                  ├ % below entry    (default 7%)
                  ├ ATR(14) × 1.5    (k = 1.5 default)
                  ├ Below 5-bar low
                  ├ Below 10-bar low
                  └ Below base low   (uses ai_classifications)
Stop $:        [calculated]   ← user can edit
Risk $:        [auto]
Distance:      [auto, in % and ATR]
```

When the user changes the strategy, the Stop $ field updates. When they manually edit Stop $, the strategy auto-flips to "Manual."

### Implementation sketch

- New helpers in the Sim core (`Sim.StopRules`?):
  - `pctBelow(price, pct)` — trivial
  - `atrBelow(bars, idx, k)` — compute ATR(14) on `bars[..idx]`, return `bars[idx].close - k * atr`
  - `swingLowBelow(bars, idx, n)` — `min(bars[idx-n..idx].low)` minus a small buffer (e.g. 0.05)
  - `baseLowBelow(symbol, year)` — read `ai_classifications[symbol_year].pivot.base_low` if present
- The setup modal calls these on strategy change to populate the stop field.
- For PortSim per-row setup, same dropdown per row.
- Initial-stop options also useful as the *default trail* on entry — see feature #3.

### Acceptance criteria

- [ ] Picker available in single-sim setup, single-sim new-leg, PortSim per-row setup.
- [ ] Each strategy computes a stop from real bar data; manual override always wins.
- [ ] Risk $ and distance % update live as strategy/stop changes.
- [ ] "Below base low" works for moves with `ai_classifications` data; falls back gracefully if absent.
- [ ] Saved metadata records which strategy was chosen, so we can later report "you do best with ATR stops on EPs" etc.

### Your notes / execution ideas:

_(fill in: any specific strategies you want first? Default k for ATR? Buffer below swing low — fixed cents or % of price? Should the strategy choice persist between sims?)_

---

## 3. Trail strategy presets ★★

**Status:** partially shipped — EMA trail (`stopTrail`, direction-aware ratchet) landed with the shorts branch; % trail / ATR trail / swing-low trail / HHV-N still queued · **Priority:** high · **Estimated effort:** 1–1.5 days remaining

### What

Optional "trail strategy" assigned per leg. Once set, the engine auto-queues `movestop` actions each tick to advance the stop according to the rule. User can still manually move the stop at any time (overrides + persists until the next trail tick re-evaluates).

### Why this matters

You called this out. Today, stops only move when the user manually moves them — which means in long sims you click Move Stop a hundred times to ride a winner. With auto-trail, the user picks a rule and lets the engine express it. The cognitive load shifts from arithmetic ("where should the stop be?") to discretion ("is this the right rule for this setup?").

### UX sketch

Two places:

**At entry:** an additional row in the setup modal:
```
Trail strategy: [ None ▾ ]
                ├ None (manual only)
                ├ % trail (k = 5%)
                ├ ATR trail / Chandelier (k = 3 × ATR(14))
                ├ 10MA trail
                ├ 21EMA trail
                ├ 50MA trail
                ├ Swing low (last 5 bars)
                └ HHV(20) low — i.e. 20-bar low
```

**Mid-trade:** a new `🪁 Apply Trail` button on the active card (single + PortSim). Opens a modal with the same picker — applying it overrides whatever was there.

Visual: when a trail is active, the stop line gets a small dotted "auto" marker; manually edited stops show solid.

### Implementation sketch

- Per-leg state field: `sim.trailStrategy = { type: 'atr' | 'pct' | 'ma' | 'swing-low' | 'hhv', config: {...} }`.
- New advanceTo step: at the start of each bar's tick, if `sim.trailStrategy` is set, compute the candidate new stop. If it's higher than the current stop (long; lower for short later), `queueAction({ type:'movestop', newStop, pct:1.0 })`. The existing movestop pipeline does the rest.
- Compute helpers reuse the same primitives as feature #2 (ATR, swing-low, MA from `getMaData`).
- Important: trails ratchet, never pull back. A 10MA trail when price is way above 10MA should NOT pull the stop down to 10MA — it stays at the highest stop-so-far.
- Manual `movestop` actions take precedence for the rest of the bar; the trail re-evaluates next bar.

### Acceptance criteria

- [ ] Trail picker on entry modal + mid-trade `🪁 Apply Trail` action.
- [ ] All five trail types ratchet correctly (never pull stops backward).
- [ ] Manual stop overrides interleave correctly — user moves stop manually, next tick the trail respects the manual-set stop as a floor.
- [ ] Stop line on chart visually distinguishes "auto-trailed" vs "manually placed."
- [ ] Saved leg metadata records the trail rule used for later analysis.

### Your notes / execution ideas:

_(fill in: any trails you use that aren't on the list? Should the trail evaluate intraday (using bar.low/high) or end-of-day? Any combos — e.g. "ATR trail until 1R hit, then 10MA trail"?)_

---

## 4. Position sizing rules ★

**Status:** queued · **Priority:** medium · **Estimated effort:** ½ day

### What

In the entry modal, instead of typing a share count, pick a sizing rule. Shares are computed automatically.

### Why this matters

The most-cited rule among swing traders is "1% portfolio risk per trade." It naturally enforces: bigger stops = smaller shares; tighter stops = bigger shares. Surfacing it in the UI makes risk-budgeting the default rather than an afterthought.

### UX sketch

```
Sizing rule:   [ Shares ▾ ]
               ├ Shares (manual, the current default)
               ├ Risk %  (default 1%)
               ├ Fixed $ (default $5,000)
               └ ATR-normalized (k × ATR)
[Risk %]: 1%   [Equity]: $100,000   [Risk $]: $1,000
[Stop $]: 95   [Entry $]: 100   [|stop dist|]: $5
[Shares]: 200  ← computed
```

When the user types in any field, dependent fields recompute.

### Implementation sketch

- Single-ticker sim: read user-configured "starting equity" from settings (already stored as `bm_cfg.simStartEquity` or similar — check). Default $100k.
- PortSim: read `state.cash` (current cash remaining). Sizing rule respects available cash automatically.
- Helper: `_sizingForRule(rule, equity, entry, stop, config) → shares`.
- Modal binds: rule change → recompute shares; equity / risk% / entry / stop change → recompute shares.

### Acceptance criteria

- [ ] Risk-% rule produces shares = `floor((equity × risk%) / |entry − stop|)`.
- [ ] PortSim uses live `state.cash` as the equity input.
- [ ] User can override the computed share count manually (rule reverts to "Shares").
- [ ] Saved metadata records the sizing rule used.

### Your notes / execution ideas:

_(fill in: default risk % — 0.5%, 1%, or 2%? Should ATR-normalized be in v1 or deferred? In PortSim, does "equity" mean cash, or total equity including open positions?)_

---

## 5. Decision log ★

**Status:** queued · **Priority:** medium · **Estimated effort:** 1 day

### What

Before any entry can be submitted, force a free-text "thesis" — why are you taking this trade? At exit time (any kind: stop, manual close, end of sim), reveal the original thesis alongside the actual outcome.

### Why this matters

The highest training-quality return per hour of work. Most traders have no record of their pre-trade reasoning, so they can't audit it. Forcing a written thesis (even one line) at every entry builds a corpus you can grep months later: "show me every short I took where I mentioned 'climax volume'." Patterns in your own thinking emerge that you'd never see otherwise.

### UX sketch

**On entry** — added to setup modals:
```
Thesis (required, why are you entering?):
[ multi-line text input ]
─ Tip: name the pattern, the trigger, what would invalidate it.
```

Empty thesis → submit button disabled.

**On exit** — at stop-out / manual close / sim end summary, the original thesis is shown alongside actual outcome:
```
SMCI · L1 · entry $812 · exit $789 (stop) · −$1,150 · −1.2R
─ Original thesis (Day 0):
  "U&R off the 21EMA after climax volume. Invalidate below
   850 LoD. Hold for 10MA test."
─ What happened:
  Stop fired Day 4 on -3% gap-down. Held 10MA briefly D2-D3.
```

**In the leg metadata + Trade Review:**
- `legSnapshots[i].thesis` is captured.
- Review modal's leg table gains a "thesis" tooltip on hover or expand-row.
- Saved review markdown includes thesis verbatim.

### Implementation sketch

- Schema add: `sim.entry.thesis` (or `sim.legs[i].thesis`).
- Setup modal: required textarea, persists to `ctx.thesis`, threaded to `Sim.createSim` / `startNewLeg`.
- Read out at exit: `_legSnapshots(entry)` already collects per-leg data — add `thesis` to the row.
- Review modal: render thesis in a collapsible row under each leg.
- Saved review meta (`_buildMeta`): include thesis per leg snapshot.

### Acceptance criteria

- [ ] Submit button disabled until thesis has at least N characters (e.g. 20).
- [ ] Thesis persists per leg through stop-out + re-entry (each leg has its own).
- [ ] Trade Review modal surfaces the thesis next to actual outcome.
- [ ] Markdown export includes thesis under each leg.
- [ ] Saved review (loaded view-only) shows thesis correctly.

### Your notes / execution ideas:

_(fill in: minimum thesis length? Optional structured prompts — "pattern", "trigger", "invalidation" as three separate fields? Or fully free-text? Show prior thesis on re-entry as scaffolding, or always blank?)_

---

## Notes for the order of execution

These five aren't fully independent. A few couplings worth flagging:

- **#2 and #3 share primitives** (ATR, swing-low, MA helpers). Build the helpers once, both features consume them. Probably worth doing #2 first (one-shot stop calculation is simpler), then #3 (which adds the per-tick re-evaluation).
- **#4 (sizing) interacts with #2 (stops)** — once you pick a sizing rule, the stop choice changes the share count. UX should make this feedback immediate (the modal recomputes live).
- **#5 (decision log)** is fully independent and could ship at any time.
- **#1 (hide future bars)** is also independent; the sim engine doesn't change, only the chart-painting layer.

Suggested order: **#1 → #5 → #2 → #4 → #3**. (Big realism wins first while the core is still stable; then the cognitive-discipline features; then the math-heavy stop/trail features last.)

---

## Done

_(empty — move features here as they ship.)_
