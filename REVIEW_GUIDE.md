# Chart Review Guide

How to request and produce a structured retrospective review of a big-winner move.

## How to trigger a review

Pass a ticker and year:

> "Review CIEN 2025"

The reviewer (Claude in conversation) follows the process below and outputs a structured review that gets stored alongside your own chart annotations.

---

## Review Process

### Step 1 — Load the data

```python
from classifier.indicators import load_ticker_bars, load_spy_benchmark, compute_all_indicators
import pandas as pd

spy = load_spy_benchmark('SPY Historical Data.csv')
bars = load_ticker_bars(SYMBOL, 'collected_stocks')
indic = compute_all_indicators(bars, benchmark=spy)
```

Also read the move's row from `big_movers_result.csv` to get the low_date, high_date, gain_pct.

### Step 2 — Quantitative snapshot

Compute these metrics for the move window (low_date → high_date):

| Metric | What it tells you |
|--------|-------------------|
| Price range (low → high, % gain) | Scale of the move |
| Big gap-ups (>5% open vs prior close) | Catalyst events — potential EP/Gap&Go entries |
| % of days above 10 EMA | Trend cleanliness — higher = more holdable |
| % of days above 20 EMA | Intermediate trend quality |
| Worst drawdown from running high | Pain tolerance required to hold |
| Count of days >10% underwater | How often you'd be deeply offside |
| Avg daily price change (slope) | Speed of the move |
| Key MA relationships at start | Was it already in Stage 2? Above 50/150/200? |

### Step 3 — Break the move into legs

Walk through the chart chronologically. A "leg" is a distinct phase of the move — either an advance or a consolidation/pullback. Identify:

- **Leg boundaries**: where the character of the price action changes (big gap, sharp reversal, extended consolidation)
- **Number of legs**: typically 2-5 for a major winner
- **For each leg**: date range, % gain/loss, dominant behavior (trending, consolidating, gapping)

### Step 4 — Classify each leg

For each leg, ask: **was there a tradable entry here?**

If yes:
- **What setup?** (VCP, EP, Flat Base, Pullback-to-MA, Gap & Go, etc.)
- **Where specifically?** (entry date/price, stop level)
- **What made it tradable?** (the structure: contractions, gap + volume, MA bounce, etc.)
- **What leg position?** (leg 1 of 4, leg 3 of 4 — later legs are riskier)

If no:
- **Why not?** (no structure, too choppy, gap-and-run with no entry, etc.)

### Step 5 — Assess style fit

After the per-leg analysis, give an overall style assessment:

- **10 EMA behavior**: Did it hold? How many times did it drop through?
- **Trend character**: Clean trending vs choppy with deep pullbacks
- **Holdability**: Could you realistically sit through the drawdowns?
- **Best leg for your style**: Which specific leg (if any) matches a clean, holdable entry?

### Step 6 — Compare to textbook definitions

For each classified leg, note where it matches or deviates from the setup definitions in `setup_definitions.json`:

- Which criteria from the spec were met?
- Which were violated?
- Does the violation matter, or is the textbook too rigid?

---

## Output Format

The review output is a structured text block. One per move, stored alongside the chart.

```
=== REVIEW: {SYMBOL} {YEAR} ===
Gain: {gain_pct}% ({low_price} → {high_price})
Period: {low_date} → {high_date}
Reviewed: {date}

QUANTITATIVE SNAPSHOT
  10 EMA adherence: {pct}% of days above
  Worst drawdown: {dd}%
  Days >10% underwater: {n}
  Big gaps (>5%): {list with dates, pct, rel_vol}
  Trend slope: ${slope}/day

LEGS
  Leg 1: {start_date} → {end_date} | {pct_gain}%
    Setup: {setup_name} or NO SETUP
    Entry: {price} ({rationale})
    Stop: {price} ({rationale})
    Tradable: YES/NO
    Why: {one paragraph}

  Leg 2: {start_date} → {end_date} | {pct_gain}%
    Setup: {setup_name} or NO SETUP
    ...

STYLE FIT
  Overall: {TRADABLE / PARTIALLY TRADABLE / NOT TO MY STYLE}
  Best leg: Leg {n} — {why}
  Concern: {what would shake you out}

TEXTBOOK COMPARISON
  {setup_name}: met {criteria}, violated {criteria}
  Myth-bust note: {any claim that doesn't hold here}
```

---

## After the review

1. The review text gets pasted into the chart's notes panel (or a dedicated review field if we build one later)
2. You (the human) read the review side-by-side with the chart
3. You add your own annotations:
   - Your subjective take on each leg ("would trade" / "too choppy" / "missed it")
   - Your preferred entry/stop if different from the review's suggestion
   - Any pattern you notice that the review missed
4. Over 200-300 reviews, the accumulated notes + reviews become the playbook library

## What this is NOT

- Not a forward-looking prediction
- Not a rating system (ratings come later, from empirical analysis of the labeled library)
- Not automated via API — it's a conversation between you and Claude, following this guide
- Not a replacement for your own chart reading — it's a structured second opinion

## Filtering the library (Stage 2)

Once enough reviews accumulate, you should be able to query:
- "Show me all legs I marked as EP + tradable" → pulls up those specific legs
- "Show me all moves where 10 EMA adherence > 70%" → cleanest trends
- "Show me all Leg 1 entries vs Leg 3+ entries" → compare early vs late entries
- "Show me all moves where I disagreed with the textbook" → myth-busting evidence

The exact query mechanism (tags, search, structured JSON) will be designed after we see 10-15 real reviews and know what fields you actually use.

---

## Quick reference: setup taxonomy

Refer to `setup_definitions.json` or click the **Defs** button in the chart topbar for full definitions. Summary:

| Setup | One-liner |
|-------|-----------|
| VCP | Shrinking contractions + volume dry-up → breakout |
| Cup & Handle | U-shaped cup + shallow handle in upper half → breakout |
| Flat Base | Tight sideways ≤15% deep, 5+ weeks → breakout |
| Double Bottom | W-shape, two lows within 3%, breakout above middle peak |
| HTF | 100%+ pole in 4-8 weeks → shallow flag → breakout |
| EP | ≥5% gap on ≥2.5x vol + tight post-gap consolidation → buy Day 2-10 |
| Gap & Go | ≥10% gap on ≥3x vol, buy Day 1 if holds above open |
| Pocket Pivot | Up-day vol > max down-day vol in prior 10, near key MA |
| Pullback to MA | Low-vol pullback to rising 10/20/50 in Stage 2 uptrend |
| No Setup | Big winner with no identifiable tradable structure |
