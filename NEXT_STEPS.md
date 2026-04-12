# Next Steps — Setup Classifier POC

> Written 2026-04-12. Read `SESSION_CONTEXT.md` first for full context.

## Where we are

Branch `feature/setup-classifier-poc` has:
- Indicator layer, pivot detection, 8 setup detectors (VCP, Flat Base, Cup&Handle, Double Bottom, HTF, Pocket Pivot, EP, Gap&Go)
- Chart overlays (MAs, swings, pivot marker) with independent toggles (AI/Sw/Piv)
- Setup definitions modal (Defs button, 18 setups)
- AI Suggested section in study drawer with accept/reject
- Review system: `reviews.json` storage, `/api/reviews` endpoints, collapsible Review panel in study drawer
- 3 backfilled reviews: IREN, LEU, CIEN (2025)
- Review guide at `REVIEW_GUIDE.md`
- 2025 classification: 62/97 matched (35 none)

## Immediate UI fixes needed

These were flagged during the session and should be done first:

### 1. Review panel visibility
- **Problem:** Review section is collapsed by default — user can't see the review side-by-side with their notes without manually clicking "expand"
- **Fix:** Auto-expand when a review exists for the current move. Only show "expand/collapse" toggle if there's content. If no review, show a compact "Not yet reviewed" line.

### 2. Notes readability
- **Problem:** The notes textarea is fine for input but poor for reading. Long notes are cramped in a small textarea.
- **Fix:** Add a "View" button next to the Notes label that opens the notes in a larger readable popover/modal. Keep the textarea for editing, but provide a readable view.

### 3. AI Suggested accept/reject clarity
- **Problem:** "Accept primary" is ambiguous — does it accept just VCP, or all three matched setups? What gets added to tags?
- **Fix:**
  - Rename "Accept primary" → "Accept VCP" (show the actual setup name)
  - Add "Accept all (3)" button that adds all matched setups to tags
  - Each chip should be individually clickable to toggle accept/reject for that specific setup
  - After accepting, chip should visually confirm (checkmark or color change)
  - Accepted setups get added to the tag system (existing tag chips in the Tags section)
  - Show a brief "Added to tags" confirmation message

### 4. Review vs Notes side-by-side layout
- **Problem:** User wants to see their notes and the AI review at the same time for comparison
- **Fix:** Consider a two-column layout within the study drawer, or tabs (My Notes | AI Review), or simply ensure both sections are visible without excessive scrolling. The review panel should auto-expand and the notes section should be directly below or alongside it.

## Chart review workflow (primary near-term activity)

The user will review ~200-300 charts from 2025 (and potentially other years). Process:

1. User selects a chart in the tool
2. User reads the chart, forms their own opinion, writes notes using the convention:
   ```
   [VCP] 2025-03-15 → 2025-05-20 | leg 1 of 3
   Entry: 48.50 (range break) | Stop: 45.00
   Structure: 3 contractions, VDU last week
   Subjective: textbook tight. To my liking — would trade.
   ```
3. User says "Review [TICKER] [YEAR]" in conversation with Claude
4. Claude follows `REVIEW_GUIDE.md`, produces structured review, saves to `reviews.json`
5. Review appears in the study drawer alongside user's notes
6. User compares, provides feedback, refines understanding
7. Over time, the accumulated reviews + notes become the playbook library

## Remaining classifier work (lower priority)

These can be done as-needed but aren't blocking the review workflow:

### Add tier-B/C detectors (optional)
- Low Cheat, IPO Base, Ascending Base, Base-on-Base
- Pullback-to-MA, Break & Retest, Undercut & Rally
- Only build when the user encounters these setups during review and wants automated detection

### Tune existing detectors
- Double Bottom is over-represented (23/62) — likely false positives
- VCP swing detection may need lookback tuning for longer bases
- EP post-gap consolidation window might need adjustment
- **Do this AFTER 20-30 reviews** when we have enough human-labeled ground truth to measure against

### Analysis layer (Phase 8 from the plan)
- Criterion → outcome correlation tables
- Claim verification ("does breakout volume > 1.5x actually correlate with better outcomes?")
- **Do this AFTER 50+ reviews** with enough labeled legs to aggregate meaningfully

## Stage 2 vision (future, not now)

After 100+ reviewed moves with labeled legs:
- **Retrieval:** "Show me all EP legs I consider tradable" → filtered query
- **Co-pilot:** User presents a live chart, system pulls similar historical legs, debates the setup
- **Playbook:** Distilled rules per setup, tailored to user's style preferences (e.g., "prefers clean 10EMA trends, skeptical of volume as primary signal")
- **Myth-busting report:** Which textbook claims hold up, which don't, based on the labeled library

## Key files to know

| File | Purpose |
|------|---------|
| `SESSION_CONTEXT.md` | Full project context (architecture, what's built, strategic direction) |
| `REVIEW_GUIDE.md` | How to produce structured chart reviews |
| `NEXT_STEPS.md` | This file — immediate action items |
| `reviews.json` | Stored reviews (3 so far: IREN, LEU, CIEN 2025) |
| `ai_classifications.json` | Automated detector output for 2025 (97 moves) |
| `setup_definitions.json` | 18 setup definitions (spec, criteria, A+ filters) |
| `classify.py` | CLI to re-run detectors: `python3 classify.py --year 2025` |
| `Big_movers_server.py` | Flask server, port 5051 |
| `Big_movers.html` | Single-file frontend |

## How to start next session

```
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
# Read context
cat SESSION_CONTEXT.md
cat NEXT_STEPS.md
# Start server
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py
# Open http://localhost:5051/
```

Then either:
- **Fix the UI issues** listed above (start here if continuing development)
- **Start reviewing charts** — pick a ticker, say "Review [TICKER] [YEAR]"
- **Both** — fix UI first, then start reviewing
