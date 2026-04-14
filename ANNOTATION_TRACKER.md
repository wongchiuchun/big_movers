# Annotation Tracker & Tradability Analysis

> 50 charts annotated. 43 with structured AI reviews. Updated 2026-04-13.

## What makes a chart tradable for my style?

### The numbers tell a clear story (n=43 reviewed)

| Metric | TRADABLE (n=9) | PARTIAL (n=14) | NOT TRADABLE (n=20) |
|--------|---------------|---------------|---------------------|
| **10EMA adherence** | **80%** (69-85) | 76% (59-92) | 65% (53-77) |
| **50SMA touches** | **2** (0-8) | 8 (1-13) | **16** (7-33) |
| **ADR** | **5.2%** (4.0-6.3) | 5.8% (4.2-8.6) | 7.2% (4.9-10.5) |
| **Worst drawdown** | -27% (-20 to -48) | -28% (-18 to -50) | -37% (-20 to -56) |
| **% time >10% underwater** | ~25% | ~40% | ~65% |

### The three killer metrics

**1. 50SMA touches — the best single predictor**
- Tradable charts average **2 touches**. STRL and CRWV have **zero**.
- Untradable charts average **15 touches**. QURE has 25, AGX has 21.
- This is the AU problem distilled: frequent 50SMA visits = "stopped out a million times."
- **Rule: >10 touches of 50SMA → skip.**

**2. 10EMA adherence — the trend quality gauge**
- Tradable: 79%. Not tradable: 64%. The threshold is ~70%.
- But 10EMA alone isn't enough — AU has 76% and is untradable (retracement ratio problem).
- **Rule: <65% → skip. 65-75% → needs other factors to work. >75% → promising.**

**3. ADR — the holdability gauge**
- Tradable: 5.1%. Not tradable: 7.4%.
- FLNC at 8.9% and SEDG at 8.6% are the most volatile — both untradable.
- STRL at 4.7% is the easiest hold. CRWV at (est ~6%) is tradable but triggers exit instinct.
- **Rule: >7% ADR → very hard to hold. <5.5% → comfortable. 5.5-7% → depends on trend quality.**

### The gold standard chart profile

Based on the 6 tradable charts, the ideal looks like:

| Characteristic | Gold Standard | Examples |
|---------------|---------------|----------|
| 10EMA adherence | >80% | STRL (84%), CLS (85%), HOOD (84%), LITE (83%), STX (80%) |
| 50SMA touches | 0-2 | STRL (0), CRWV (0), CLS (2), STX (2), CAR (2) |
| ADR | <5.5% | STX (4.0%), STRL (4.7%), CLS (5.5%) |
| Clean 10EMA trend duration | >8 weeks | STX (23wk), STRL (16wk), LITE (15wk), CAR (15wk), CLS (12wk) |
| Worst drawdown | >-25% | STRL (-20%), HOOD (-21%), CAR (-21%), CLS (-21%), LITE (-22%) |

**Top 3 charts in the library:**
1. **STX** — 80% 10EMA, 2 50SMA, **4.0% ADR** (lowest), 23-week grind, 0 trap EPs
2. **STRL** — 84% 10EMA, **0 50SMA**, 4.7% ADR, 16-week grind
3. **CLS** — 85% 10EMA, 2 50SMA, 5.5% ADR, 12-week grind

### What gain size does NOT tell you

Gain size has **zero correlation** with tradability:
- QURE +821% → NOT TRADABLE (63% 10EMA, 25 50SMA touches)
- CIFR +1272% → TRADABLE (75% 10EMA, smooth trend)
- STRL +335% → TRADABLE (best chart in library)
- FLNC +647% → NOT TRADABLE (8.9% ADR, 81% underwater)

A +300% smooth grinder beats a +800% choppy mess every time for this style.

### EP close quality filter

Discovered through PL, validated across the library:

| Type | Close position | Examples | Result |
|------|---------------|----------|--------|
| **Real EP** | Close at 70-100% of day's range | DAVE May 8 (98%), JOBY May 28 (81%), PL Sep 8 (99%) | Held and ran |
| **Trap EP** | Close at 0-30% of day's range | PL Jun 5 (17%), QURE Apr 17 (28%), SEDG May 6 (11%) | Reversed/filled |

**Rule: If EP day closes in the bottom third of its range → it's a trap, skip.**

### Post-entry trend quality

Entry hierarchy (VCP > EP > Pullback) only applies when the subsequent trend matches the style:
- **HOOD**: Early VCP → clean trend → early entry was right
- **NBIS**: Early Jun EP → 2 months chop → later Sep entry was better
- **Rule: The best entry is the one followed by clean 10EMA tracking, not necessarily the earliest one.**

---

## All 30 Annotated Charts

### TRADABLE (6)

| Ticker | Gain | 10EMA | 50SMA | DD | ADR | Setup | Best Entry | Key Feature |
|--------|------|-------|-------|-----|-----|-------|------------|-------------|
| **STRL** | +335% | 84% | **0** | -20% | 4.7% | Breakout + EP | 10EMA pullbacks May-Jul | BEST CHART. 16wk clean grind. Zero 50SMA. Low ADR = easy hold. |
| **CLS** | +526% | 85% | 2 | -21% | 5.5% | Breakout + EP | 50SMA reclaim May (~$94) | CIFR-quality. 12wk 10EMA trend. Aug+Sep EPs accelerated. |
| **HOOD** | +419% | 84% | 8 | -21% | — | VCP | May 8 VCP breakout | Classic VCP. CALIBRATION: AI picked Sep EP, user corrected to May VCP. |
| **CIFR** | +1272% | 75% | — | -36% | — | Round Bottom | Round bottom breakout | User's ideal chart. Respects 10MA throughout. Very tradable. |
| **CRWV** | +800% | 77% | **0** | -48% | — | IPO Base | IPO base breakout | Perfect 10EMA, zero 50SMA. But wide intraday range triggers exit instinct. |
| **CIEN** | +404% | 69% | — | -29% | — | EP, VCP, C&H | Sep 4 EP | EP entry when 5-month base was untradable. Best of first reviewed set. |
| **LITE** | +780% | 83% | 3 | -22% | 5.6% | Breakout + EP | 50SMA reclaim May | CLS-quality. 15wk 10EMA trend. 2 good EPs. |
| **STX** | +389% | 80% | 2 | -23% | **4.0%** | Breakout + EP | 50SMA reclaim, 10EMA pullbacks | Rivals STRL. Lowest ADR (4.0%). 23wk grind, 0 trap EPs. |
| **CAR** | +294% | 81% | 2 | -21% | 6.3% | Breakout | Base breakout ~$78 | Clean short move. 15wk 10EMA trend. Only 2 50SMA touches. |

### PARTIALLY TRADABLE (7)

| Ticker | Gain | 10EMA | 50SMA | DD | ADR | Setup | Best Entry | Why Partial |
|--------|------|-------|-------|-----|-----|-------|------------|-------------|
| **DAVE** | +338% | 86% | 1 | -24% | 6.6% | EP | May 8 EP (close@98%) | Textbook EP but Jul -31% collapse. Validates EP close quality filter. |
| **JOBY** | +322% | 80% | 7 | -21% | 6.2% | EP chain | May 28 EP | Mixed EP quality. May 28 (81%) real, Jun 3 (9%) trap, Jun 9 (80%) real. |
| **COHR** | +339% | 77% | 10 | -32% | 5.1% | Breakout | 10EMA pullback Jun-Jul | Tradable until Aug -32% weekly shakeout. Recovery required re-entry. |
| **SEZL** | +651% | **92%** | 4 | -25% | 8.6% | Breakout | 10EMA pullbacks | Highest 10EMA (92%) but CRWV paradox — 8.6% ADR. Perfect on paper, scary in practice. |
| **TSEM** | +352% | 82% | 10 | **-18%** | 4.2% | Breakout | 20EMA pullbacks | Shallowest DD (-18%). Low ADR. But 10 50SMA touches add friction. |
| **TTMI** | +411% | 79% | 8 | -23% | 4.7% | Breakout | 10EMA pullbacks | Steady grinder, no catalysts. Low ADR = holdable but boring. |
| **W** | +463% | 77% | 11 | -29% | 5.6% | EP chain | EP entries (4 good, 0 trap) | Best EP hit rate in library but 11 50SMA touches. EP-trade stock, not hold stock. |
| **PI** | +306% | 73% | 9 | -22% | 5.1% | 20EMA trend | 20EMA pullbacks | Tracks 20EMA (75%), not 10EMA. Different trailing stop needed. |
| **KTOS** | +371% | 78% | 11 | -23% | 4.9% | 20EMA trend | 20EMA pullbacks | 87% 20EMA adherence. 10EMA trader would struggle, 20EMA approach works. |
| **ARWR** | +656% | 77% | 13 | -26% | 5.9% | Breakout | 10EMA pullbacks May-Aug | Borderline. 13 50SMA touches. Would need wider stops. |
| **NBIS** | +671% | 75% | 2 | -21% | 7.0% | EP chain | Sep onwards (user corrected) | CALIBRATION: AI picked Jun EP, user said Sep. Post-entry trend quality matters. |
| **MU** | +386% | 69% | — | -26% | — | Flat Base | Flat base breakout | Textbook flat base but tempo too slow. Jul disappointing. |
| **LEU** | +840% | 59% | — | -49% | — | EP, VCP | May EP cluster | Weak VCP, more EP. Aug pullback painful. Don't drop from watchlist. |
| **ALAB** | +500% | 60% | 12 | -50% | — | VCP, Flat Base | Aug EP | Gap-ups held. But Leg 4 destroyed. Kinda tradable. |

### NOT TO MY STYLE (10)

| Ticker | Gain | 10EMA | 50SMA | DD | ADR | Why Not |
|--------|------|-------|-------|-----|-----|---------|
| **AU** | +350% | 76% | 7 | -20% | — | Retracement ratio problem. 76% 10EMA but retraces 80%+ of each advance. |
| **AVAV** | +370% | 63% | 19 | -43% | — | Only final leg tradable. AI's double bottom label was wrong. |
| **ASTS** | +487% | 53% | — | -49% | — | News-driven. 73% underwater. Only late EP. Lowest 10EMA in library. |
| **PL** | +652% | 66% | 15 | -37% | 6.7% | 3 trap EPs before 1 real one. EP close quality filter discovered here. |
| **AGX** | +295% | 69% | 21 | -26% | 5.4% | AU-type slow grinder. 21 50SMA touches. Trap EP (close@20%). |
| **RKLB** | +443% | 63% | 15 | -49% | 7.3% | AU on steroids. Every metric below threshold. -49% DD. |
| **FLNC** | +647% | 64% | 14 | -39% | **8.9%** | Highest ADR in library. Daily volatility makes holding impossible. |
| **QURE** | +821% | 63% | **25** | -38% | 7.5% | Most 50SMA touches. +38% trap EP (close@28%). Biotech gap-fade. |
| **SEDG** | +342% | **61%** | 7 | **-44%** | 8.6% | Worst 10EMA and worst DD in library. Two trap EPs (close@11-12%). |
| **IREN** | +1400% | 61% | — | -56% | — | Round bottom with micro-setups inside. Macro untradable, micro-entries possible. |
| **CRDO** | +635% | 72% | 7 | -36% | 6.5% | 0 good EPs, 4 traps. Worst EP stock — every gap failed. |
| **PRAX** | +1090% | 66% | 16 | -39% | 6.9% | +1090% but untradable. 60% underwater. Gain size vs tradability disconnect. |
| **SNDK** | +856% | 77% | **33** | -20% | 6.0% | 33 50SMA touches — new library record. Despite decent 10EMA. |
| **SATS** | +648% | 64% | 15 | -24% | 4.9% | Below threshold on all key metrics. 69% underwater. |
| **VSCO** | +314% | 71% | 20 | -26% | 5.5% | 20 50SMA touches. Retail AU-type. |
| **KSS** | +318% | 65% | 15 | **-52%** | 6.7% | 2nd worst DD (-52%). 87% underwater. Retail macro-driven. |
| **OUST** | +557% | 63% | 9 | -33% | 8.2% | 8.2% ADR. Lidar volatility. 75% underwater. |
| **IONQ** | +373% | 62% | 17 | -32% | 8.1% | Quantum narrative stock. 79% underwater. All metrics fail. |
| **PONY** | +506% | 61% | 17 | -50% | **10.5%** | NEW RECORD: 10.5% ADR. 95% underwater. Most extreme chart. |
| **VSAT** | +492% | 66% | 13 | -26% | 6.7% | Tracks 20EMA (77%), not 10EMA. Below threshold. |

### USER-ANNOTATED ONLY (no AI review yet — 7)

| Ticker | Tags | User Notes Summary |
|--------|------|--------------------|
| **ABVX** | Gap and Go | EP-type. Traded cleanly with patience. 4-month hold. |
| **AAOI** | Cup & Handle | No setup until 2026 breakout. 4-5 deep round trips in 2025. |
| **APLD** | Breakout | Weak momentum May-Sep. Repeated 50EMA pullbacks. Only final leg. |
| **BE** | Flat Base, EP | Jul EP tradable until Sept. Then price action too loose. |
| **GLXY** | Cup & Handle | Only Sep tradable. User traded and failed to profit. Not my trade. |
| **MP** | EP, Breakout | Intraday selloffs brutal. User traded it, not profitable. |
| **OKLO** | Cup & Handle | Chops were real. Sep pullup at stretched valuation. |

---

## Calibration Log (11 lessons)

1. **HOOD**: VCP base breakout > EP catalyst when base is clean. EP late in move = last leg.
2. **AU vs CIFR**: Retracement ratio > absolute EMA adherence. AU retraces 80%+; CIFR doesn't.
3. **CRWV paradox**: Perfect chart can trigger exit instinct if intraday ranges are extreme.
4. **Entry hierarchy**: VCP/base breakout > EP > Pullback-to-MA. But only when post-entry trend is clean (#8).
5. **EP timing**: Longer the base, later in the move the EP falls.
6. **Day 2 entry**: Gaps retrace ~2/3 on Day 1. Day 2 is default EP entry.
7. **Forward vs backward**: Pivots and classifiers are retrospective. Real value = pre-move characteristics.
8. **NBIS — Post-entry trend quality**: Early entry wins ONLY when subsequent trend is clean. NBIS Jun EP → chop → Sep was better.
9. **PL — EP close quality filter**: Trap EPs close in lower half of range. Real EPs close near high. Gap size + volume alone insufficient.
10. **DAVE — EP close quality validation**: May 8 close@98% = textbook strong EP. Confirms the filter.
11. **JOBY — Mixed EP quality**: Same stock can have both real (81%) and trap (9%) EPs in the same week. Filter works per-event.

---

## Quick-filter checklist (for new charts)

Before deep analysis, run these filters:

1. **10EMA adherence >70%?** — If no, likely untradable. (Exception: CIEN at 69% was tradable because the EP leg was clean.)
2. **50SMA touches <10?** — If >10, almost certainly untradable. Zero = gold.
3. **ADR <7%?** — If >7%, holding will be extremely uncomfortable regardless of trend quality.
4. **Any EP with close >70% of day's range?** — If not, the gaps are traps.
5. **Is there a continuous 8+ week stretch of clean 10EMA tracking?** — If yes, that's the tradable leg.

If a chart passes all 5, it's worth a detailed review. If it fails 2+, it's probably a skip.
