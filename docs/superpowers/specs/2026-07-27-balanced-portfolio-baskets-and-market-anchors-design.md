# Balanced Portfolio Baskets and Market-Anchor Data

**Date:** 2026-07-27
**Status:** Approved design, pending implementation planning

## Purpose

Portfolio simulations currently select a small visible basket, usually six
tickers and rarely more than eight. Because the original catalogue is built
from known historical big movers, an all-catalogue basket can give the trader
an unrealistically favorable opportunity set. The existing cross-year noise
reduces that outcome bias, but it can also select obscure names that were not
useful market-context stocks during the simulated period.

This feature will build balanced baskets from three hidden sources:

1. known big movers from the selected year;
2. liquid, point-in-time market leaders ("anchors"); and
3. liquid cross-year noise.

It will also add safe, resumable data synchronization for a curated 50-symbol
anchor universe. Anchor data lives only in `collected_stocks/`; anchor symbols
must not be inserted into `big_movers_result.csv`.

## Goals

- Preserve at least one genuine mover without filling the basket with known
  winners.
- Give each normal simulation market-context names that were liquid and
  relevant during that period.
- Keep the basket composition uncertain even when the trader understands the
  broad selection policy.
- Support every existing basket size from one through ten, with six as the
  default.
- Prevent look-ahead in anchor eligibility and noise liquidity filtering.
- Backfill approximately ten years of anchor data without truncating any
  existing CSV.
- Keep normal app startup and simulation fully offline. Data synchronization is
  always an explicit command.

## Non-goals

- Reconstruct the full historical membership of every US index.
- Add anchors to the Big Movers study catalogue.
- Guarantee that every basket contains a profitable trade.
- Select anchors based on their performance inside the hidden simulation
  window.
- Increase the portfolio simulator beyond its current ten-card maximum.
- Automate data downloads when the app starts or when the randomizer runs.

## Anchor Universe

The initial universe contains 50 liquid US leaders. It is intentionally split
into two selection groups so that multiple anchors do not always come from the
same growth/technology cluster.

### Nasdaq/growth group

`AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`, `GOOG`, `META`, `AVGO`, `TSLA`,
`AMD`, `MU`, `INTC`, `COST`, `NFLX`, `ADBE`, `CSCO`, `QCOM`, `AMAT`, `TXN`,
`INTU`, `BKNG`, `ISRG`, `PANW`, `PEP`, `PLTR`

### Broad-market group

`JPM`, `V`, `MA`, `LLY`, `WMT`, `XOM`, `UNH`, `JNJ`, `HD`, `PG`, `BAC`, `KO`,
`CRM`, `ORCL`, `IBM`, `CAT`, `GE`, `BA`, `DIS`, `MCD`, `NKE`, `CVX`, `ABBV`,
`MRK`, `GS`

The broad group deliberately includes financials, health care, consumer,
industrial and energy leaders. The universe is not a list of expected future
winners; historically weak periods for these stocks are valid simulation
outcomes.

### Manifest

The tracked file `market_anchor_universe.json` is the only source of truth for
anchor status. It has this logical shape:

```json
{
  "version": 1,
  "data_start": "2015-01-01",
  "data_end": "2025-12-31",
  "symbols": [
    {
      "symbol": "AAPL",
      "group": "growth",
      "sector": "technology",
      "history_start": "2015-01-01",
      "eligibility": [
        {"from": "2015-01-01", "to": null, "basis": "index-membership"}
      ]
    }
  ]
}
```

Every symbol must have:

- one of the two groups, `growth` or `broad`;
- a stable sector label;
- a `history_start` equal to the global data start for securities already
  trading then, or the verified first trading/listing date for a later IPO;
- one or more closed or open eligibility intervals; and
- an eligibility basis.

An interval begins no earlier than the later of the security's listing date and
its effective inclusion in the Nasdaq-100 or S&P 100. A removal closes the
interval; a later re-entry creates a new interval. The selected simulation
window's start date must fall inside an interval. Membership effective dates
must be captured from contemporaneous or official index records, rather than
inferred from future returns. An entry that cannot be verified is not eligible.

The manifest is maintained manually and reviewed like application code. It is
not refreshed from the internet during normal app use.

## Basket Allocation

Let `B` be the requested basket size after clamping it to the existing range
1–10. A composition is a triple `(M, A, N)`:

- `M`: same-period movers;
- `A`: market anchors;
- `N`: cross-year noise.

Special cases:

- `B = 1`: `(1, 0, 0)`
- `B = 2`: `(1, 1, 0)`

For `B >= 3`, enumerate every integer triple satisfying:

```text
M + A + N = B
ceil(0.25 * B) <= M <= floor(0.50 * B)
max(1, round(0.20 * B)) <= A <= min(3, max(1, floor(0.40 * B)))
N >= 1
```

This produces, for example, four valid six-ticker compositions:

```text
2 movers / 1 anchor  / 3 noise
2 movers / 2 anchors / 2 noise
3 movers / 1 anchor  / 2 noise
3 movers / 2 anchors / 1 noise
```

The allocator selects among valid triples with a seeded pseudo-random generator.
All valid triples have non-zero probability. Balanced triples receive twice the
weight of boundary triples, where a boundary triple has either the maximum
mover count or the minimum anchor count. The exact triple is saved with the run
but is not shown until review.

The random seed is created from browser cryptographic randomness when
available, then used for composition, candidate shuffling and final card order.
Saving the seed makes a completed basket reproducible for debugging without
making a live run predictable.

## Candidate Pools

### Same-period movers

- Source: `big_movers_result.csv`.
- The row's year must equal the selected year.
- The symbol must have local OHLCV covering four calendar months before the
  simulation start through the simulation end.
- Duplicate catalogue rows for one symbol collapse to one candidate.
- Movers are selected first. If a manifest anchor is also selected from the
  same-period mover pool, its saved role for that run is `mover`, and it is
  removed from the anchor pool. This precedence preserves the requested mover
  quota while preventing duplicate symbols and ambiguous review metadata.

### Market anchors

- Source: `market_anchor_universe.json`.
- The simulation start must be inside an eligibility interval.
- Local OHLCV must cover the required context and simulation window.
- A symbol in the manifest is excluded from the noise pool, even if it also
  appears in the Big Movers catalogue.

Anchor group selection:

- one anchor: choose `growth` or `broad` with equal probability, falling back
  only when the chosen group has no eligible candidate;
- two anchors: choose one from each group;
- three anchors: randomly choose which group supplies two, while the other
  supplies one. If the chosen 2:1 split cannot be filled, try the opposite 2:1
  split before rejecting the window.

Symbols are sampled without replacement. The final basket is shuffled so card
position does not reveal role.

### Cross-year noise

- Source: symbols appearing in `big_movers_result.csv` in a year other than the
  selected year.
- Manifest anchors and already selected movers are excluded.
- Local OHLCV must cover the required context and simulation window.
- Liquidity is measured only with bars strictly before the simulation start.

A noise candidate passes when:

- at least 20 pre-window daily bars are available, using at most the most recent
  60;
- the final pre-window close is at least $5; and
- median daily dollar volume (`close * volume`) across those bars is at least
  $20 million.

No price, volume or return from the hidden window may affect eligibility.

## Window Resolution and Failure Handling

The randomizer continues to choose a four-to-six-month window inside the
selected year. It then builds the three eligible pools for that window.

If no valid composition can be filled:

1. discard the tentative window;
2. generate another window in the same year; and
3. retry up to 12 distinct windows.

The randomizer must not silently increase the mover quota or download missing
data. If all attempts fail, it shows a concise error explaining which pool was
insufficient and suggests choosing another year, reducing the basket size, or
running the explicit anchor-data synchronizer.

The randomizer never returns a partial basket.

## User Interface

- Change the default random ticker count from four to six.
- Replace the current "Cross-year noise" checkbox with **Balanced basket**,
  enabled by default.
- Its help text explains that the basket mixes period movers, liquid market
  leaders and liquid comparison names.
- Disabling it retains the legacy behavior of selecting only same-year movers.
- During setup and simulation, do not label tickers by source and do not report
  category counts.
- The success message says only that a balanced basket is ready and lists the
  chosen date range and symbols.
- The final review shows each symbol's role (`mover`, `anchor`, or `noise`), the
  overall composition and the random seed.

Saved and legacy simulations without role metadata continue to load. Their role
is displayed as `unknown` rather than inferred after the fact.

## Anchor Data Synchronization

### Coverage target

- Start: `2015-01-01`, providing context before the earliest 2016 simulations.
- Initial end: `2025-12-31`. Current-day data is not required for this
  historical simulation pool.
- Interval: daily.
- Maximum requested output: 5,000 rows.

Both coverage boundaries come from the tracked manifest, so a future annual
maintenance pass can advance `data_end` deliberately without making normal app
use or synchronization depend on today's date. The initial target is
comfortably below 5,000 daily rows. Twelve Data documents the
`/time_series` maximum as 5,000 points and charges one API credit per symbol:
<https://twelvedata.com/docs>.

The current local audit found:

- 11 anchor symbols already covering the target;
- 8 existing but starting too late; and
- 31 missing.

The initial synchronization therefore needs approximately 39 successful symbol
requests.

### Command

Add an explicit command:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py
```

Supported options:

```text
--dry-run              audit without network calls or writes
--symbol SYMBOL        limit work to one symbol; repeatable
--max-requests N       stop after N attempted external requests
--min-interval SECONDS default 9; values below 9 are rejected
--start YYYY-MM-DD     default from manifest
--end YYYY-MM-DD       default from manifest; explicit override allowed
--state PATH           override resumable-state location
```

The normal app never invokes this command.

### Synchronization behavior

For each manifest symbol:

1. inspect its local coverage;
2. skip it when the requested range is already present;
3. otherwise make one full-range Twelve Data request;
4. parse and validate the response;
5. merge returned bars with all existing bars by date;
6. preserve existing history outside the requested range;
7. sort ascending and remove duplicate dates; and
8. atomically replace the CSV using the standard
   `DateTime,Open,High,Low,Close,Volume` layout.

The synchronizer never uses the current non-extend fetch endpoint's destructive
replacement behavior. It has its own merge-safe path. Existing CSVs are not
changed until the complete response has parsed and passed validation.

Runtime state records each attempt, result, requested range and error. A later
run re-audits the CSV rather than trusting state alone, so it is safe after an
interrupted write or manual file replacement. Runtime state is ignored by Git.

### Rate limits and remote errors

- Wait at least nine seconds between external attempts.
- Count retries against `--max-requests`.
- On HTTP 429, respect `Retry-After`; otherwise wait 60 seconds.
- Retry transient network and 5xx failures at most three times with increasing
  waits.
- Stop the whole run on API-credit exhaustion or an invalid API key.
- Continue to the next symbol after a permanent symbol-specific error.
- Print a final summary of skipped, updated, failed and remaining symbols.

An IPO or later listing may legitimately return less than the full target
range. The synchronizer audits each symbol from the later of global
`data_start` and its manifest `history_start`. Eligibility intervals control
when a symbol may enter a basket; they do not shorten the history requested for
an already-listed company. If returned history begins materially after the
effective history start, the symbol remains incomplete and is reported as a
coverage failure.

## Persistence

Each new portfolio run saves:

```json
{
  "basketGeneration": {
    "version": 1,
    "mode": "balanced",
    "seed": "...",
    "composition": {"mover": 2, "anchor": 2, "noise": 2},
    "roles": {
      "AAPL": "anchor",
      "XYZ": "mover"
    }
  }
}
```

This object travels with saved simulations and final review data. It does not
change trade calculations or existing statistics.

## Testing

### Allocator tests

- Check every basket size 1–10 against its exact constraints.
- Generate thousands of seeds and prove every valid composition is reachable.
- Confirm no invalid or partial composition is returned.
- Confirm a saved seed reproduces composition, selections and card order.

### Candidate tests

- Enforce anchor eligibility at the window start.
- Exclude anchors from cross-year noise.
- Deduplicate symbols across all pools.
- Give `mover` precedence when a same-period mover is also a manifest anchor.
- Try the opposite 2:1 group split before rejecting a three-anchor window.
- Use only pre-window bars for noise price and dollar-volume filters.
- Require full context and window coverage.
- Verify retrying windows never relaxes category constraints.

### UI and persistence tests

- Default basket count is six and Balanced basket is enabled.
- Live setup, cards and status text do not expose roles.
- Review reveals roles, composition and seed.
- Legacy runs display `unknown` roles without failing.
- Disabling Balanced basket preserves same-year-only selection.

### Synchronizer tests

- Dry-run makes no network calls and writes no files.
- Complete files are skipped without consuming a request.
- Backfills merge with, rather than replace, existing history.
- Existing rows outside the requested range survive unchanged.
- Duplicate dates resolve deterministically to fetched bars within the requested
  range and existing bars outside it.
- Invalid or incomplete responses leave the original file byte-for-byte
  unchanged.
- Atomic replacement, resumption, request caps, throttling, retries and
  permanent-error handling behave as specified.
- Command validation rejects `--min-interval` values below nine seconds.
- Neither synchronization nor randomization modifies
  `big_movers_result.csv`.

## Acceptance Criteria

The feature is complete when:

1. the 50-symbol manifest and verified eligibility intervals are tracked;
2. explicit synchronization can safely bring every eligible anchor to the
   target coverage without truncation;
3. the balanced randomizer works for basket sizes 1–10 and defaults to six;
4. baskets respect the mover, anchor and noise constraints without look-ahead;
5. ticker roles remain hidden until review;
6. saved runs reproduce and reveal their original basket generation; and
7. the existing offline default and Big Movers catalogue remain unchanged.
