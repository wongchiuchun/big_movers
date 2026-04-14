# Chart Review Guide

> How to produce a structured retrospective review of a big-winner move.
> Updated 2026-04-12 after calibration across 11 annotated tickers.

## How to trigger a review

Pass a ticker and year:

> "Review HOOD 2025"

The reviewer (Claude in conversation) follows the process below, outputs a structured review stored in `reviews.json`, and visible in the Study drawer's Review panel and Compare Side-by-Side popup.

---

## Core principles (learned through calibration)

### 1. Three dimensions — use all together
- **General rules**: Setup definitions, entry criteria, EMA alignment patterns. Guiding, not definitive.
- **Data**: EMA adherence, retracement ratios, gap sizes, volume, slope. Tells a lot but lacks visual context.
- **Visual chart**: Use agent-browser to screenshot and SEE how things align — MAs overlaying price, base shapes, breakout levels. This is where all information comes together.

**Never annotate from data alone.** Take a screenshot, look at the chart, then overlay quantitative analysis.

### 2. Map ALL setups in the move
A single move can contain multiple entry opportunities serving different purposes:
- **Consolidation/VCP breakout** (early): lower cost basis, defined risk below range, captures the whole move
- **EP catalyst** (later): momentum entry, tight stop below gap-day low, 20-30% run if gap holds
- **Both are valid** — annotate all of them with context on which is a position entry vs a momentum trade

### 3. EP timing principle
The longer a stock has been basing and the more it has run up, the more likely an EP is in the MIDDLE or LATE part of the move:
- HOOD: Sep 8 EP was the last leg before Oct trend break
- CIEN: Sep 4 EP came after 5-month grind — only entry because base was untradable
- ASTS: Oct 8 EP after stock had already 5x'd
- **Rule**: If a clean VCP/base breakout exists earlier → that's the position entry. EP is the add or momentum trade.

### 4. Hindsight bias warning
These are ALL successful examples. In real-time:
- A wide-range bar that punches through 10EMA looks like a crash, not a shakeout
- Morning and afternoon candles can tell completely different stories
- Don't assume the daily close tells the whole story — intraday, a loss can go from 10% to 50%
- Super wide range days and long wicks = potential intraday stop-out events
- **Flag these in reviews** as "intraday shakeout risk" rather than dismissing them because the close held

### 5. The user's strengths vs AI's strengths
- **User excels at**: Reading the big picture, the full move, identifying which part has what characteristics, spotting base patterns visually
- **AI excels at**: Quantitative analysis (volume changes, retracement ratios, EMA adherence), noticing what happened before/after, comparing across many examples
- **The review should combine both**: AI provides the structured quantitative framework; user provides the subjective style assessment. Disagreements are the most valuable data points.

---

## Review process

### Step 1 — Visual inspection (NEW — do this FIRST)

Use agent-browser to open the chart in the study tool:
1. Screenshot the full chart at daily timeframe
2. Look at: base shapes, EMA alignment, consolidation ranges, gap events, trend character
3. Note your initial visual read BEFORE running numbers

This prevents the data from biasing the visual assessment.

### Step 2 — Load the data

```python
from classifier.indicators import load_ticker_bars, load_spy_benchmark, compute_all_indicators
import pandas as pd

spy = load_spy_benchmark('SPY Historical Data.csv')
bars = load_ticker_bars(SYMBOL, 'collected_stocks')
indic = compute_all_indicators(bars, benchmark=spy)
```

Also read the move's row from `big_movers_result.csv` to get the low_date, high_date, gain_pct.

### Step 3 — Quantitative snapshot

Compute these metrics for the move window (low_date → high_date):

| Metric | What it tells you |
|--------|-------------------|
| Price range (low → high, % gain) | Scale of the move |
| 10 EMA adherence (% days above) | Trend cleanliness — user's threshold is ~65-70% for tradable |
| 20 EMA adherence (% days above) | Intermediate trend quality |
| 50 SMA touches (days within 3%) | How often it revisits 50SMA — user hates frequent visits |
| Worst drawdown from running high | Pain tolerance required |
| Days >10% underwater | Duration of pain |
| Big gap-ups (>5% open vs prior close) | Catalyst events — EP candidates |
| Trend slope ($/day, %/day) | Speed/tempo of the move — key differentiator |
| Swing retracement ratios | **Critical**: pullback as % of preceding advance. >60% = AU-type (psychologically untradable) |

### Step 4 — Break the move into legs

Walk through the chart chronologically. Identify:
- **Where the character changes**: gap event, sharp reversal, consolidation starts/ends, EMA alignment shift
- **For each leg**: date range, % gain/loss, dominant behavior
- **Typically 3-5 legs** for a major winner

### Step 5 — Identify ALL potential entries (not just one)

For each leg, ask: **is there a tradable entry here?**

**Entry hierarchy (learned from calibration):**

1. **Consolidation/VCP breakout** — preferred when:
   - Base is clean with tightening contractions
   - Stock is above 10/20 EMA during the base
   - EMAs are realigning (converging and turning up)
   - Gives defined risk below the consolidation range

2. **EP catalyst** — preferred when:
   - Base phase was untradable (choppy, visiting 50SMA, narrow range)
   - Gap is >5% on >2x average volume
   - **EP close quality filter (from PL calibration):** Close must be at or near high of bar. If close is in the lower half of the range with a long upper wick, it's likely a TRAP EP — skip. PL had three trap EPs (+31%, +15%, +17% gaps that all reversed) before one real EP (+18% with close near high) that actually held.
   - **Entry timing**: Day 2 is usually better than Day 1 (gaps tend to retrace ~2/3 on Day 1). Enter Day 1 only if intraday action shows strength (tests low, holds, closes strong)

3. **Pullback-to-MA** — for adds or re-entries:
   - Clean pullback to 10EMA in a fast-moving trend
   - Pullback to 20EMA after a shakeout (like HOOD Aug)
   - Consolidation at 50SMA as a "reset" entry (like HOOD Sep 2-5 before the Sep 8 EP)

**Post-entry trend quality qualifier (from NBIS calibration):**
The entry hierarchy (early > late) only applies when the **subsequent trend matches this user's style**. If an early entry leads to choppy consolidation (20EMA tracking, deep retracements, repeated MA violations), a later clean-trend entry is actually better. HOOD: early VCP → clean trend → early was right. NBIS: early Jun EP → 2 months chop → later Sep entry was actually more tradable.

**For untradable legs, explain why:** no structure, too choppy, frequent 50SMA visits, high retracement ratios, etc.

### Step 6 — Assess style fit

**What makes a move tradable for this user:**
- Clean 10EMA trend (>65-70% adherence)
- Good tempo/speed — fast, decisive moves, not slow grinds
- Low retracement ratios (pullback < 50% of prior advance)
- Doesn't constantly revisit 50SMA
- Has defined-risk entry points (consolidation range bottom or gap-day low)

**What makes it NOT tradable:**
- Frequent 50SMA visits (AU pattern — "stopped out a million times")
- High retracement ratios (advance 20%, retrace 18% — "gains evaporate")
- Super wide intraday range days that trigger exit instinct (even if close holds 10EMA)
- Slow grind with constant back-and-forth (even if technically trending)
- Long sideways periods that test patience

**The CRWV paradox:** Even a perfect chart (77% 10EMA, zero 50SMA touches) can trigger the exit instinct if intraday ranges are extreme. Flag this when it applies — the holding problem is partially about daily volatility tolerance, not just trend quality. (Stage 2 topic.)

### Step 7 — Compare to textbook + note the macro pattern

- Which textbook criteria are met/violated for each classified setup?
- Does the violation matter?
- **Note the macro pattern**: Is this a round bottom with EP entry? A VCP with successive tightening? An IPO base breakout? The macro shape matters alongside the individual setup labels.
- **Myth-bust notes**: Any textbook claim that doesn't hold here?

---

## Output format

The review is stored as structured JSON in `reviews.json` under the key `{SYMBOL}_{YEAR}`.

```json
{
  "reviewed_at": "YYYY-MM-DD",
  "gain_pct": 418.75,
  "period": "YYYY-MM-DD to YYYY-MM-DD",
  "snapshot": {
    "price_range": "$X -> $Y",
    "ema10_adherence_pct": 84,
    "ema20_adherence_pct": 87,
    "worst_drawdown_pct": -21.4,
    "days_over_10pct_underwater": 14,
    "sma50_touches": 8,
    "trend_slope_per_day": "$0.86/day (2.44%/day)",
    "big_gaps": ["date: +X% gap, Nx vol"]
  },
  "legs": [
    {
      "leg": 1, "of": 4,
      "period": "date to date",
      "pct_gain": "~X%",
      "setup": "VCP / EP / NO SETUP / etc",
      "entry": "price area and rationale (or null)",
      "stop": "price and rationale (or null)",
      "tradable": true/false/"Partially — reason",
      "rationale": "paragraph explaining the leg"
    }
  ],
  "style_fit": {
    "overall": "TRADABLE / PARTIALLY TRADABLE / NOT TO MY STYLE",
    "best_leg": "which leg and why",
    "concern": "what would shake this user out"
  },
  "textbook_comparison": "how it maps to setup definitions",
  "myth_bust_notes": "any claim that doesn't hold"
}
```

### New fields (add when applicable):

```json
{
  "ai_vs_user_comparison": {
    "ai_best_entry": "what AI identified",
    "user_best_entry": "what user identified",
    "who_was_right": "assessment and lesson learned",
    "lesson": "what this teaches about annotation approach"
  }
}
```

---

## After the review

1. Review appears in the Study drawer's Review panel and Compare Side-by-Side popup
2. User reads side-by-side with their own notes and chart
3. User adds/updates their annotations — agreements and disagreements
4. Over time, the combined reviews + user notes become the playbook library
5. Disagreements between AI and user annotations are the highest-value calibration data

## What this is NOT

- Not a forward-looking prediction
- Not a rating system (ratings come later, from empirical analysis — skipped for now)
- Not automated — it's a conversation between user and Claude
- Not a replacement for the user's chart reading — it's a structured complement
- **Not purely quantitative** — visual chart inspection is a required step

---

## Stop logic (heuristic, to be refined in Stage 2)

- Breakout from consolidation: ~8% below the range bottom
- Gap-up (EP) entry: ~8% below the gap-day low
- These are rules of thumb, not yet data-validated
- Exit/trailing stop strategy is deferred to Stage 2

---

## Quick reference: setup taxonomy

Refer to `setup_definitions.json` or click **Defs** in the chart topbar. Summary:

| Setup | One-liner | Entry preference |
|-------|-----------|-----------------|
| VCP | Shrinking contractions + VDU → breakout | Consolidation range breakout |
| Cup & Handle | U-shaped cup + shallow handle → breakout | Handle breakout |
| Flat Base | Tight sideways ≤15% deep, 5+ weeks → breakout | Range breakout |
| Double Bottom | W-shape, two lows within 3%, breakout above peak | Middle peak breakout |
| HTF | 100%+ pole in 4-8 weeks → shallow flag → breakout | Flag breakout |
| EP | ≥5% gap on ≥2.5x vol + tight post-gap consolidation | Day 2 (preferred) or Day 1 if holds |
| Gap & Go | ≥10% gap on ≥3x vol, buy Day 1 if holds above open | Day 1 if strong |
| Pocket Pivot | Up-day vol > max down-day vol, near key MA | At the MA |
| Pullback to MA | Low-vol pullback to rising 10/20/50 in uptrend | At the MA bounce |
| Round Bottom | Rounding accumulation base | Micro-setups within (trendline break, undercut & rally, tight consolidation breakout) |
| No Setup | Big winner with no identifiable tradable structure | Skip or wait for EP |

---

## Calibration log

Key lessons from annotation calibration (13 tickers reviewed, 3 AI annotation attempts as of 2026-04-12):

1. **HOOD**: AI called Sep 8 EP "best entry." User corrected: May 8 VCP breakout is the real position entry. Sep 8 is the last leg. **Lesson**: Don't wait for perfection — earlier structural entry captures more of the move.

2. **AU vs CIFR**: Both ~75% 10EMA adherence, but user rejects AU and embraces CIFR. **Lesson**: Retracement ratio (pullback/advance) matters more than absolute EMA adherence. AU retraces 80%+ of each advance; CIFR doesn't.

3. **CRWV**: Perfect chart (77% 10EMA, zero 50SMA touches) but user would exit early. **Lesson**: Even the best charts can trigger exit instinct if intraday ranges are extreme. Holding problem is partly about daily volatility tolerance.

4. **CIEN/LEU**: User skips the base-formation phase entirely, only enters on EP. **Lesson**: When the base is untradable (choppy, visiting 50SMA), EP is the entry. Don't mark base legs as tradable.

5. **IREN**: User sees micro-setups within the round bottom (trendline break, undercut & rally, tight consolidation breakout on Aug 22). **Lesson**: "Round bottom" is the macro shape; the entries are specific structural events within it.

6. **ALAB**: User enters Day 2 after gap, not Day 1. **Lesson**: Gaps tend to retrace ~2/3 on Day 1. Day 2 is the default EP entry unless Day 1 shows clear strength.

7. **NBIS** (AI annotation attempt #2): AI picked Jun 5 EP as best entry (earliest above all MAs). User corrected: Sep onwards was the most tradable leg. **Lesson**: Entry hierarchy (early > late) needs a qualifier — only when post-entry trend is clean. NBIS Jun EP led to 2 months of faith-testing chop. The later Sep EP had clean 10EMA tracking. User actually traded this name and confirmed the difficulty.

8. **PL** (AI annotation attempt #3): Three massive EP traps (+31%, +15%, +17% gaps) all reversed before one real EP (+18%) held. **Lesson**: EP close quality is a critical filter. Real EPs close near the high of the day. Trap EPs close in the lower half with long upper wicks. Gap size and volume multiplier alone are necessary but not sufficient.
