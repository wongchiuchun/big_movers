# Sim Review → Data Flywheel — Implementation Plan

> Status: IMPLEMENTED 2026-05-03 (Phases 0–5, 7 shipped; Phase 6 frequency gate deferred as opt-in).
> Target file: `Big_movers.html` + `STATS_DATA_GUIDE.md`
> Author: planning session 2026-05-03

## 1. Goal

Turn the post-sim review from a free-form note into a structured data layer that powers cross-session analysis. After ~100 sessions, the user should be able to answer questions like:

- *"Which setup types am I best at, by win rate and average R?"*
- *"At what conviction level am I actually calibrated?"*
- *"How often do I follow my plan — and is plan-fidelity correlated with R?"*
- *"What's my discipline cost when MAE touches -0.5R or worse?"*
- *"Which legs in winning sessions actually drove the result?"*

These questions cannot be answered today. The data isn't being captured.

## 2. Current state (audit findings)

### 2a. Two storage systems, decoupled

| System | Key | Indexed by | What it stores | Survives export? |
|---|---|---|---|---|
| SimStats sessions | `bm_sim_sessions_v2` | `sess_<ts>_<rand>` | aggregates per Add-to-Stats click | yes (CSV) |
| SimStats trades | `bm_sim_trades_v2` | `trade_<sessionId>_<i>` | per-leg outcome data | yes (CSV) |
| PortSim Review | `bm_portsim_review_<startDate>__<endDate>__<sortedSymbols>` | **setup config** (window + basket) | free-form per-ticker + portfolio notes | **no** |

The seam: review notes are keyed by *setup*, sessions are keyed by *attempt*. Two attempts on the same basket+window share one notes record — they overwrite each other. Notes never enter the export.

### 2b. Per-leg outcome detail exists but not surfaced

`_extractTradesFromSim` produces clean per-leg rows: entry/exit/qty/risk/holding/R/MFE/MAE plus the `eventsLog` trail (entries, adds, stop moves, partial sells). Sessions reference these via `sessionId`, but the Sim Stats UI shows only session-level aggregates. To drill into "what happened in each leg of session #4" you'd need to manually filter the trades CSV.

### 2c. No decision-quality metadata

Outcome data is rich. Decision data is empty. There's nothing on:
- What setup the user thought they were entering
- How long they intended to hold
- How confident they were
- What their emotional state was
- Whether the exit matched the plan
- Whether they sat through MAE or panicked

The user has explicitly rejected putting these at entry/exit time — too much friction. Capture must be **post-session, in a guided review**.

## 3. Problems to solve

1. **Review-key collision.** Reviews must be per-session, not per-setup, so each attempt has its own reflective record.
2. **Review notes don't export.** They live outside the analytical pipeline. Either promote into session record, or join at export time.
3. **No structured decision-quality data.** Free-form notes can't be aggregated. Need 1-click tags alongside the prose.
4. **Per-leg drill-down missing from UI.** Aggregates hide what actually happened.

## 4. Design principles (guardrails)

These are the user's constraints. The plan must respect them:

1. **Zero added friction at entry/exit.** All metadata is captured post-session, never during trade execution.
2. **Review is guided and structured, not a wall of textareas.** Each prompt has a small set of enum values + optional free-form text.
3. **Mandatory but skippable.** The user can save without reviewing — but the session is flagged `reviewSkipped: true` so analytics can filter or surface them.
4. **Backward compatible.** Existing v2 sessions and existing free-form `bm_portsim_review_*` data must not be lost. Migration is read-time, lazy, and reversible.
5. **Two export tiers.** Summary export (current) stays unchanged. Deep export (new) includes review fields.
6. **Bias avoidance.** Regime classification is captured *after* the session as observation, never before — to preserve the user's unbiased execution philosophy.
7. **Offline-first.** All storage is localStorage. No backend. Quota management handled gracefully (already exists for sessions/trades).

## 5. Data model

### 5a. Session record (extended)

Add a `review` sub-object to the session. All fields optional except `reviewSkipped` flag.

```js
{
  // existing v2 fields unchanged: id, ts, simType, symbols, year, sessionPnL, ...
  v: 3,                          // bumped from 2
  review: {
    completedAt: 1714752000000,
    reviewSkipped: false,        // true if user dismissed the review modal
    schemaVersion: 1,            // for future review-schema evolution

    // session-level reflective fields
    session: {
      emotionalScore: 4,         // 1-5: "if real money, would I have stuck with this?"
      regimeFelt: 'choppy',      // POST-HOC: trending|choppy|declining|mixed|recovery
      streakBefore: 2,           // auto-computed: # losing sessions before this one
      gateOverridden: false,     // auto: true if user bypassed frequency gate

      // structured pain-calibration prompts (3 short answers)
      painCalibration: {
        next24h: '...',          // "if real $, what would I be doing for next 24h?"
        nextDayAction: 'step_away',  // enum: enter_more | hold_steady | step_away | unsure
        outOfHowMany: '...',     // "out of how many sessions like this would I expect this?"
      },

      // free-form (legacy compatibility — preserves existing review modal text)
      portfolioNote: '...'
    },

    // per-leg structured tags (keyed by tradeId)
    legs: {
      'trade_sess_xxx_1': {
        // intent (what user thought they were doing — captured post-hoc but described as-of-entry)
        setupType: 'breakout_VCP',  // EP | breakout_VCP | pullback_10EMA | pullback_20EMA | continuation | parabolic | other
        intendedHold: 'core_swing_10_30d',  // scalp_intraday | short_swing_3_10d | core_swing_10_30d | runner_30d_plus
        conviction: 4,             // 1-5
        entryState: 'calm',        // calm | itchy | fomo | revenge

        // execution quality
        planFidelity: 'as_planned',  // as_planned | cut_early_nervous | held_past_plan | added_unplanned | moved_stop_wider
        wouldHoldReal: true,       // "if real money, would I have held to this exit?"
        atHeatResponse: 'held',    // held | widened_stop | panic_cut | none_needed (only meaningful if MAE <= -0.5R)

        // optional context
        thesis: '...',             // one sentence: what had to be true for this to work
        legNote: '...'             // free-form per-leg
      }
    }
  }
}
```

### 5b. Per-leg trade record (unchanged)

The `bm_sim_trades_v2` records stay as outcome-only. Review tags live on the session, indexed by tradeId. This keeps trade rows lean and makes review optional.

### 5c. Storage migration

| Old key | New treatment |
|---|---|
| `bm_portsim_review_<setupKey>` | Read once on first session-review load. If found and matches the session's setup, port `portfolio` + `notes` text into `session.review.session.portfolioNote` and `session.review.legs[*].legNote`. Mark old key as `migrated_to_session_<sessionId>`. Don't delete (safety net). |
| `bm_sim_sessions_v2` records with `v: 2` | Treated as legacy. UI shows them in stats but flagged as "no review". User can retroactively review (opens review modal for that session). |
| New sessions | Written as `v: 3` from the next code load. |

## 6. UX flow — guided review

### 6a. Save flow

When user clicks **📊 Add to Stats**:

1. **Frequency gate check** (optional, opt-in via toolbar toggle):
   - If `now < lastSession.review.session.nextSessionAvailableAfter`, show soft block: *"Last session ended {N}h ago. Override?"*
   - Override allowed but stored as `gateOverridden: true`.

2. **Mandatory review modal** opens:
   - **Step 1 — Per-leg tags.** One row per leg, with enum dropdowns + optional 1-line note.
     - Compact: setup, intent, conviction, plan-fidelity, would-hold-real
     - Defaults pre-filled where possible (e.g., conviction = null prompts for input)
   - **Step 2 — Session reflection.** Three pain-calibration prompts + emotional score + regime-felt selector + portfolio-level free-form.
   - **Step 3 — Save or Skip.**
     - **Save**: writes `session.review` and persists.
     - **Skip with reason**: writes `reviewSkipped: true` with optional reason. Session still saves.
   - Streak detector: if `streakBefore >= 3`, modal shows a banner — *"3rd losing session in a row. State the bet you're making before saving."* — with one extra textarea.

3. After save, the existing PortSim Review modal (free-form, per-run) remains accessible for revisits — but writes into `session.review.session.portfolioNote` rather than the old `bm_portsim_review_*` key.

### 6b. Drill-down view

Add to the existing Sim Stats modal:

- Click a session row → expand to show:
  - All legs (one per row): symbol, dates, R, exit reason, **plus** review tags (setup, intent, conviction, planFidelity)
  - Session-level review summary
  - Free-form notes
- "Re-review" button on legacy sessions, opens modal in retrospective mode.

### 6c. Two export modes

- **Summary CSV** (existing): unchanged. One row per trade with session aggregates. No review fields.
- **Deep CSV** (new): one row per trade, all existing columns **plus** every per-leg review field, plus session.review.session fields denormalized.

Both exports available from the Sim Stats modal as separate buttons.

## 7. Implementation phases

Each phase is one commit. Tests added per phase where feasible.

### Phase 0 — Baseline
- Confirm with user: commit current WIP (`Big_movers.html` + `STATS_DATA_GUIDE.md` + data refreshes) as separate baseline commits, OR have user commit before proceeding. Plan modifies these files; merge conflicts cheap to avoid.

### Phase 1 — Per-session review keying
**Commit:** `feat(review): key reviews by sessionId, not setup config`
- Replace `bm_portsim_review_<setupKey>` with `bm_portsim_review_<sessionId>`.
- Add lazy migration: on first load of a session's review, look up old setup-keyed entry and port over if present.
- Update `PortSim.Review._computeRunId` to take an optional sessionId.
- No UI change yet.
- **Test:** unit-style — open same setup twice, save different notes, confirm both persist.

### Phase 2 — Schema bump + session.review skeleton
**Commit:** `feat(stats): add session.review sub-object (v3 schema)`
- Bump session.v to 3 on new writes.
- `addCurrent` and `addCurrentPortfolio` initialize `review: { reviewSkipped: true, completedAt: null }` by default (so the field always exists).
- Update STATS_DATA_GUIDE.md to document v3 and the review object.
- No UI change yet — purely schema.
- **Test:** save a session, confirm record has v:3 and review object.

### Phase 3 — Guided review modal
**Commit:** `feat(review): mandatory guided review on Add to Stats`
- Replace current free-form modal with two-step guided flow.
- Per-leg row component with enum dropdowns.
- Session-level form with pain-calibration prompts + emotional score.
- "Skip" path that writes reviewSkipped + reason.
- Pre-populate from old `bm_portsim_review_*` if migrated.
- **Test:** complete review flow end-to-end, verify session.review populated.

### Phase 4 — Drill-down view
**Commit:** `feat(stats): expandable session rows with leg + review detail`
- Click session row in stats modal → expand to show legs with review tags.
- "Re-review" button on sessions with `reviewSkipped: true`.
- Read-only view for sessions with completed reviews.
- **Test:** expand a reviewed session, confirm leg tags display.

### Phase 5 — Deep CSV export
**Commit:** `feat(stats): deep CSV export with review fields`
- Add second export button.
- Denormalize session.review.session onto every trade row (mirrors existing pattern).
- Per-leg review tags joined by tradeId.
- Append columns at the end of the existing summary export schema.
- **Test:** export CSV, open in spreadsheet, verify review columns populated.

### Phase 6 — Streak + frequency gate (optional polish)
**Commit:** `feat(review): streak banner + frequency gate (opt-in)`
- Compute streakBefore from sessions array on review modal open.
- Frequency gate as toolbar toggle, default off.
- Streak banner (≥3 losing sessions) shown unconditionally in review modal.

### Phase 7 — Documentation
**Commit:** `docs(stats): document v3 schema, guided review, deep export`
- STATS_DATA_GUIDE.md: full v3 reference.
- Add a section on common deep-CSV analyses (setup × conviction × R, plan-fidelity correlation, etc.).
- Update REVIEW_GUIDE.md if it references session schema (it currently doesn't — it's about historical chart annotation, separate system).

## 8. Backward compatibility

| Scenario | Behavior |
|---|---|
| Old v2 session loaded | Treated as legacy. Stats UI shows it; review fields appear as "no review captured". Re-review button available. |
| Old `bm_portsim_review_*` exists for a setup that matches a v2 session | On first review-modal open of that session, migration prompt: "Found legacy notes for this setup — port them in?" One-click port, old key marked migrated, never auto-deleted. |
| User downgrades app version | New v3 records are forward-compatible — old code reads them as v2 and ignores `review` field. Worst case: review data orphaned, not lost. |
| Quota exceeded after schema bump | Session size grows ~30% with review object. Existing halve-on-quota fallback still applies. New cap math: 5,000 sessions × ~3KB each = ~15MB, well within localStorage limits. |

## 9. Open questions / decisions to validate

1. **Mandatory vs skippable.** Plan says mandatory-with-skip. Should the skip button require a reason, or be a single click? Argument for reason: forces friction that might convert to actual review. Argument against: if skip is too painful, user abandons sim altogether.

2. **Per-leg tags for losing legs that stopped out fast.** A leg that stopped at -1R in 2 days probably doesn't need full setup tagging. Should review modal collapse stopped-out short-hold legs into a single "stopped out as planned" toggle? Reduces friction, may lose data.

3. **Conviction calibration.** Plan captures conviction post-hoc (after seeing the outcome). This biases self-rating. Mitigation: conviction prompt phrased as *"at the moment of entry, how confident were you?"* and presented BEFORE the user sees the leg outcome in the modal. Worth testing.

4. **Regime classification — really post-hoc?** User said no regime classification because it would bias execution. But capturing it post-session is fine — it's observation, not signal. Open question: should regime tagging be per-session or per-leg? Per-session is simpler; per-leg is more granular but can be derived from session for portfolio sims.

5. **Re-review of legacy sessions.** When user clicks "Re-review" on an old session, the original sim state is gone. Can they rate setup/conviction without re-running? Probably yes, from memory + the trade row data. But quality may be poor. Should legacy reviews carry a `retroactive: true` flag for filtering?

6. **CSV column count creep.** Deep CSV will be ~50 columns. Acceptable for AI ingestion (no problem) but unwieldy in spreadsheet. Consider: pivot output (one row per session, review fields columns) vs current (one row per trade). Or both.

## 10. Acceptance criteria

The plan is complete when:

1. ✅ A new sim session can be Add-to-Stats'd, the guided review modal opens, the user fills it in (or skips with flag), and the data persists in `session.review`.
2. ✅ Existing PortSim Review notes (if any) are migrated on first encounter, not lost.
3. ✅ Sim Stats modal shows session rows that expand to per-leg + review detail.
4. ✅ Deep CSV export contains: every existing column + per-leg review tags + session-level review fields.
5. ✅ Old v2 sessions still display correctly, marked as "no review".
6. ✅ A user with 0 reviewed sessions today can produce 30 reviewed sessions in a month and run an analysis like *"R by setup type, by conviction level"* on the deep CSV.
7. ✅ STATS_DATA_GUIDE.md describes the v3 schema, the migration, and at least 5 example analyses.

## 11. Risks

- **User abandons reviews after first few sessions.** Mitigation: modal must be fast (~30 seconds for a typical 3-leg session). Defaults pre-filled where possible. Skip path always available.
- **Review data quality is low** (random tags, not thoughtful). Mitigation: not solvable in code. Surfaced via emotional-score and would-hold-real fields — if those skew, the data is decorative.
- **Schema thrash if review fields evolve.** Mitigation: `review.schemaVersion: 1` lets us migrate review-only fields without bumping session.v.
- **Legacy free-form notes that don't fit new structure** are migrated as plain text into `portfolioNote` — preserving them but not retro-fitting structure. Acceptable.

---

## Next step

1. Get codex-rescue to review this plan for blind spots / over-engineering / missed scenarios.
2. Address findings.
3. Confirm Phase 0 with user (commit existing WIP first, or work on top).
4. Implement phase by phase, one commit per phase.
