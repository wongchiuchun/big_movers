# Next Steps — Setup Classifier POC

> Updated 2026-04-12 (end of session). Read `SESSION_CONTEXT.md` first for full context.

## The big picture — what we're building and why

We're building a **personalized trading co-pilot** through structured retrospective chart review. The ultimate goal isn't prediction — it's a system that can **debate, challenge, and recall** when evaluating new opportunities.

### The three problems we're solving
1. **Weighing between opportunities** — user is good at spotting setups but not at ranking/choosing between them
2. **Holding with conviction** — user tends to overtrade/scalp to avoid pullbacks, wants to swing trade instead
3. **Applying consistent methodology** — building data-backed confidence in a repeatable approach

## Current state

### Phase transition: Python classifier → Library building

The Python classifier phase is **done** — it served its purpose for initial 2025 categorization (97 moves) but has hit diminishing returns:
- Pivots are backward-looking (need `high_date`) — useless for real-time
- Classifications often disagree with user's read (AVAV not double bottom, LEU more EP than VCP)
- Further detector tuning not worth the investment

**What's still useful from the Python side:**
- Quantitative snapshot computation (EMA adherence, retracement ratios, gap analysis, slope) — used in every review
- Chart overlays (MAs on chart) — used actively during annotation
- The setup detectors themselves are retired

**We're now in the "build the library through annotation and calibration" phase.**

### What's been annotated (20 tickers, 13 with AI reviews)

| Ticker | Tags | Style verdict | Key insight |
|--------|------|--------------|-------------|
| CIFR | Round Bottom | ✅ Tradable | 75% 10EMA, "very tradable, respects 10MA" |
| CIEN | EP, VCP, C&H | ✅ Tradable | EP entry when base untradable. Best of reviewed set. |
| HOOD | VCP | ✅ Tradable | **CALIBRATION**: AI said Sep EP best entry, user corrected: May VCP breakout. |
| ABVX | Gap and Go | ✅ Tradable | EP-type. Traded cleanly, 4-month hold. Not fast but patient trade. |
| ALAB | VCP, Flat Base | ⚠️ Kinda tradable | Gap-ups held. Aug EP was explosive but Leg 4 destroyed. |
| CRWV | IPO Base | ⚠️ Tradable but scary | Perfect 10EMA chart but wide range triggers exit instinct. |
| LEU | VCP, EP | ⚠️ Partially | EP > weak VCP. Aug pullback painful. Don't drop from watchlist. |
| MU | Flat Base | ⚠️ Partially | Textbook flat base but tempo doesn't match user's style. |
| IREN | Round Bottom, VCP | ⚠️ Partial | Micro-setups within round bottom (undercut & rally, Aug 22 breakout). |
| BE | Flat Base, EP | ⚠️ Partially | Jul EP tradable until Sept, then price action too loose. |
| NBIS | EP | ⚠️ Partially | **CALIBRATION**: AI picked Jun EP, user corrected: Sep onwards. Post-entry trend quality matters. |
| ASTS | Breakout | ❌ Not tradable | News-driven, 73% of time >10% underwater. Only late EP. |
| AU | VCP, Breakout | ❌ Not tradable | 76% 10EMA but AU-type retracement (80%+). Gains evaporate. |
| AVAV | Breakout | ❌ Not tradable | Only final leg tradable. AI's double bottom label was wrong. |
| AAOI | Cup & Handle | ❌ Not tradable in 2025 | No setup until 2026 breakout. 4-5 deep round trips. |
| APLD | Breakout | ❌ Not tradable | Weak momentum May-Sep, repeated 50EMA pullbacks. Only final leg. |
| GLXY | Cup & Handle | ❌ Not tradable | Only Sep tradable, hard to hold. User traded and failed to profit. |
| MP | EP, Breakout | ❌ Not tradable | Intraday selloffs brutal. User traded it, not profitable. Need to be spot-on. |
| OKLO | Cup & Handle | ❌ Not tradable | Chops were real for a long time. Sep pullup at stretched valuation. |
| PL | EP, Gap and Go | ❌ Not tradable | **CALIBRATION**: 3 trap EPs before 1 real one. EP close quality filter discovered. |

### Key calibration lessons learned

1. **HOOD (most important):** VCP base breakout (May 8) > EP catalyst (Sep 8) when the base is clean. EP late in move = last leg. Don't wait for perfection.
2. **AU vs CIFR:** EMA adherence alone doesn't determine tradability. Retracement ratio (pullback/advance) and TEMPO matter more. AU at 76% rejected, CIFR at 75% embraced.
3. **CRWV paradox:** Even a perfect chart triggers exit instinct if intraday ranges are extreme.
4. **Entry hierarchy:** Consolidation/VCP breakout (early, position entry) > EP (later, momentum trade or re-entry) > Pullback-to-MA (adds). **But only when the post-entry trend is clean** (see #8).
5. **EP timing:** The longer the base and the more the stock has run, the later in the move the EP falls.
6. **Day 2 entry:** Gaps tend to retrace ~2/3 on Day 1. Day 2 is the default EP entry.
7. **Forward vs backward:** Pivots and classifications are retrospective. Real value is in identifying setups as they form — pre-move characteristics, not post-move confirmation.
8. **NBIS — Post-entry trend quality:** Early entry > late EP ONLY when the subsequent trend matches the user's style. NBIS Jun EP led to 2-month chop (20EMA tracking, 58% retracements); Sep EP led to clean 10EMA tracking. Later clean entry was actually better. Qualifier on #4.
9. **PL — EP close quality filter:** Not all EPs are real entries. Trap EPs close in the lower half of their range with long upper wicks (PL had 3 trap EPs: +31%, +15%, +17% that all reversed). Real EPs close near the high (PL Sep 8: $9.67 vs $9.71 high). Gap size + volume alone are insufficient — check WHERE the EP day closes.

### User's style profile

**The ideal setup pattern:**
1. Stock climbs along 20MA — clear, orderly
2. Breaks down to 50MA, holds, consolidates
3. Accelerates — transitions to tracking along 10MA
4. **"That's my shot"** — the 10MA tracking phase is the entry zone

**Key metrics:**
- 10EMA adherence threshold: ~65-70% for "tradable"
- Retracement ratio: <50% of preceding advance = acceptable. >60% = AU-type, skip.
- 50SMA touches: frequent visits = untradable for this user
- Tempo: fast, decisive moves preferred over slow grinds
- ATR: high is OK if trend is clean (CIFR), not OK if choppy (ASTS)

**Stop logic (heuristic, Stage 2):** ~8% below consolidation range bottom or gap-day low.

**Current execution pattern (to improve):** Exits on ~4% pullback, swings 1-2 days, heavily reliant on day-1 momentum. Wants data to prove 10EMA trailing > day-trading.

## Staged approach

### Stage 1: Library building (THRESHOLD REACHED — 20 annotations)

**User:** Annotate charts freely. Flag what catches your eye. No forced structure.
**AI:** Produce structured reviews + chart annotations. Independent annotation attempts every 5-6 new examples.
**Focus:** ENTRY only. Exit/stop refinement deferred to Stage 2.

**Three dimensions of annotation (use all together):**
1. General rules (setup definitions, EMA patterns)
2. Data (quantitative metrics — AI's strength)
3. Visual chart (screenshot + overlay — essential, don't skip)

**Progress:** 20 annotated, 13 reviewed, 3 AI annotation attempts with calibration. Hit the 20-annotation threshold for Stage 1.5 reassessment.

**What helps most now:**
- Continue annotating toward 30 for richer calibration data
- AI annotation attempts are converging — 3rd attempt (PL) aligned with user on best entry
- Failed examples — setups that looked right but broke down (still zero failures in the library)
- AI now annotates charts directly (notes, stop levels) — getting closer to user's style

### Stage 1.5: Calibration (APPROACHING)

At ~20 annotations:
- AI attempts 3-5 independent annotations
- User grades them — disagreements are highest-value data
- Update REVIEW_GUIDE.md with confirmed patterns
- Assess readiness for Stage 2

### Stage 2: Strategy refinement (FUTURE)

Deferred topics:
- Exit strategy (10EMA trailing? 20EMA? Adaptive?)
- Stop logic refinement (8% rule vs data-driven)
- Position sizing (partial vs full, scaling)
- Strategy simulation against labeled library
- Rating/filtering system for opportunity ranking
- Shakeout tolerance modeling

### Stage 3: Live co-pilot (FUTURE)

- Evaluate setups in real-time (only see data up to current point)
- Pull historical parallels from library
- Challenge user's read with counter-examples
- Help rank 20-name watchlist
- Provide holding conviction through data-backed confidence

### Forward-looking exercises (STARTED)

We did initial forward-looking analysis on:
- **ASTS 2026:** Not yet tradable. EMAs converging but no clean tracking. Watchlist.
- **IREN 2026:** Still in downtrend. Below 50SMA. Too early.
- **CIFR 2026:** Getting interesting. Apr 8 gap above all MAs after undercut low. Watch for consolidation.

These exercises are the bridge to Stage 3 — practicing the real-time evaluation skill.

## Key files

| File | Purpose |
|------|---------|
| `SESSION_CONTEXT.md` | Full project context (architecture, what's built) |
| `NEXT_STEPS.md` | This file — staged approach and action items |
| `REVIEW_GUIDE.md` | How to produce structured chart reviews (updated with calibration lessons) |
| `reviews.json` | 11 reviews: IREN, LEU, CIEN, ASTS, CIFR, MU, AVAV, AU, ALAB, CRWV, HOOD |
| `metadata.json` | Per-move user tags, rating, direction, notes (11 annotated) |
| `ai_classifications.json` | Automated detector output for 2025 (97 moves) — reference only |
| `setup_definitions.json` | 18 setup definitions |
| `Big_movers_server.py` | Flask server, port 5051 |
| `Big_movers.html` | Single-file frontend |

## How to start next session

```
cd "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
cat NEXT_STEPS.md
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 Big_movers_server.py
# Open http://localhost:5051/
```

Then: annotate more charts, or ask for an AI annotation attempt, or do a forward-looking exercise on a current chart.
