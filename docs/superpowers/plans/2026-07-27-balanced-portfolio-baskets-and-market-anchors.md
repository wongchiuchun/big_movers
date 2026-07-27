# Balanced Portfolio Baskets and Market Anchors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a point-in-time 50-name liquid-leader pool, safely backfill its historical OHLCV, and generate hidden balanced portfolio baskets containing controlled mixtures of same-year movers, anchors, and liquid cross-year noise.

**Architecture:** A tracked JSON manifest owns the anchor universe and eligibility intervals, while a small Flask endpoint exposes it locally. A standalone Python synchronization module and CLI audit, fetch, merge, throttle, and resume anchor-data updates without coupling network access to the app. A pure browser/Node-compatible JavaScript module owns seeded basket allocation and eligibility math; `Big_movers.html` supplies local data, integrates the result with the existing setup wizard, and persists generation metadata through controller and review state.

**Tech Stack:** Python 3.13 standard library, Flask test client, Node.js `node:test`, vanilla browser JavaScript, local CSV/JSON storage, Twelve Data `/time_series`.

---

## File Responsibility Map

**Create**

- `market_anchor_universe.json` — reviewed 50-symbol universe, groups, sectors,
  data boundaries, and point-in-time eligibility intervals.
- `market_anchor_sync.py` — reusable CSV parsing/merging, Twelve Data client,
  coverage audit, throttling, retry, atomic writes, and resumable sync engine.
- `tools/sync_market_anchors.py` — thin command-line argument and exit-code
  adapter over `market_anchor_sync.py`.
- `portfolio_basket.js` — pure seeded allocation, anchor eligibility, pre-window
  liquidity, and role-selection functions usable by browser and Node tests.
- `tests/test_market_anchor_manifest.py` — manifest schema and Flask endpoint
  tests.
- `tests/test_market_anchor_sync.py` — unit tests for merge safety, coverage,
  retries, pacing, state, and CLI validation.
- `tests/portfolio_balanced_basket.test.cjs` — allocator, candidate, UI contract,
  and persistence tests.

**Modify**

- `Big_movers_server.py` — expose the local anchor manifest through
  `GET /api/market-anchors`.
- `Big_movers.html` — load the local module; replace legacy randomization with
  balanced resolution; default to six; preserve offline behavior; carry hidden
  generation metadata into controller and review; reveal it only in review.
- `.gitignore` — ignore the default runtime sync-state file.
- `README.md` — document balanced baskets, the 50-name universe, and explicit
  synchronization/audit commands.
- `tests/offline_local_mode.test.cjs` — retain the guarantee that randomization
  never calls `/api/fetch-ticker` or external URLs.
- `tests/portfolio_setup_defaults.test.cjs` — replace the legacy checkbox
  assertion with Balanced basket enabled and six tickers by default.

**Data updates after code validation**

- Create or backfill the 39 audited paths under `collected_stocks/`:
  `MSFT.csv`, `NVDA.csv`, `GOOGL.csv`, `GOOG.csv`, `META.csv`, `AVGO.csv`,
  `AMD.csv`, `INTC.csv`, `COST.csv`, `ADBE.csv`, `CSCO.csv`, `QCOM.csv`,
  `AMAT.csv`, `TXN.csv`, `INTU.csv`, `PEP.csv`, `PLTR.csv`, `JPM.csv`, `V.csv`,
  `LLY.csv`, `WMT.csv`, `XOM.csv`, `UNH.csv`, `JNJ.csv`, `HD.csv`, `PG.csv`,
  `KO.csv`, `ORCL.csv`, `IBM.csv`, `CAT.csv`, `GE.csv`, `BA.csv`, `DIS.csv`,
  `MCD.csv`, `NKE.csv`, `CVX.csv`, `ABBV.csv`, `MRK.csv`, and `GS.csv`.
- Do not touch the 11 already complete files or `big_movers_result.csv`.

## Execution Safety for the Existing Worktree

Before Task 1, record the user's existing state:

```bash
git status --short
git diff --cached --name-only
```

Treat every pre-existing modified, untracked, or staged path as user-owned.
Never reset, restore, stash, or clean it. Every commit in this plan must use
`git commit --only ... -- <exact task paths>` so unrelated staged paths cannot
enter the commit. New task files still need an exact `git add` first. Before
and after each commit, compare `git diff --cached --name-only` with the recorded
baseline and confirm all unrelated staged paths remain staged and unchanged.

## Task 1: Create and Serve the Reviewed Anchor Manifest

**Files:**

- Create: `market_anchor_universe.json`
- Create: `tests/test_market_anchor_manifest.py`
- Modify: `Big_movers_server.py:25-35`
- Modify: `Big_movers_server.py:448-465`

- [ ] **Step 1: Write failing manifest and endpoint tests**

Create `tests/test_market_anchor_manifest.py` using `unittest`. Load the manifest
directly and exercise the Flask test client:

```python
import json
import pathlib
import unittest

from Big_movers_server import app

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "market_anchor_universe.json"
EXPECTED = {
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "GOOG", "META", "AVGO",
    "TSLA", "AMD", "MU", "INTC", "COST", "NFLX", "ADBE", "CSCO", "QCOM",
    "AMAT", "TXN", "INTU", "BKNG", "ISRG", "PANW", "PEP", "PLTR",
    "JPM", "V", "MA", "LLY", "WMT", "XOM", "UNH", "JNJ", "HD", "PG",
    "BAC", "KO", "CRM", "ORCL", "IBM", "CAT", "GE", "BA", "DIS", "MCD",
    "NKE", "CVX", "ABBV", "MRK", "GS",
}

class MarketAnchorManifestTests(unittest.TestCase):
    def test_manifest_has_exact_reviewed_universe(self):
        data = json.loads(MANIFEST.read_text())
        symbols = [row["symbol"] for row in data["symbols"]]
        self.assertEqual(len(symbols), 50)
        self.assertEqual(set(symbols), EXPECTED)
        self.assertEqual(len(symbols), len(set(symbols)))

    def test_manifest_intervals_are_valid_and_non_overlapping(self):
        data = json.loads(MANIFEST.read_text())
        self.assertEqual(data["data_start"], "2015-01-01")
        self.assertEqual(data["data_end"], "2025-12-31")
        for row in data["symbols"]:
            self.assertIn(row["group"], {"growth", "broad"})
            self.assertTrue(row["sector"])
            self.assertTrue(row["history_start"])
            self.assertGreaterEqual(row["history_start"], data["data_start"])
            self.assertTrue(row["eligibility"])
            previous_to = None
            for interval in row["eligibility"]:
                self.assertTrue(interval["from"])
                self.assertTrue(interval["basis"])
                if interval["to"] is not None:
                    self.assertLessEqual(interval["from"], interval["to"])
                if previous_to is not None:
                    self.assertLess(previous_to, interval["from"])
                previous_to = interval["to"]
            open_ended = [
                index for index, interval in enumerate(row["eligibility"])
                if interval["to"] is None
            ]
            self.assertLessEqual(len(open_ended), 1)
            if open_ended:
                self.assertEqual(open_ended[0], len(row["eligibility"]) - 1)

    def test_api_returns_manifest(self):
        response = app.test_client().get("/api/market-anchors")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["symbols"]), 50)
```

- [ ] **Step 2: Run the tests and confirm the expected failure**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_manifest -v
```

Expected: failure because `market_anchor_universe.json` and
`/api/market-anchors` do not exist.

- [ ] **Step 3: Research and write the exact manifest**

Use official Nasdaq annual reconstitution/index-change releases and official
S&P 100 change announcements to verify intervals. Rules:

- eligibility begins no earlier than listing and effective membership;
- `history_start` is `2015-01-01` for a security already trading at the global
  start, otherwise its verified first trading/listing date;
- removals close an interval;
- re-entry opens another interval;
- an unverified interval is omitted, not guessed;
- `basis` records the index and effective-change source description.

Use the exact 25/25 group lists from the spec. Start with this structure:

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
        {
          "from": "2015-01-01",
          "to": null,
          "basis": "Nasdaq-100 member at target-period start"
        }
      ]
    }
  ]
}
```

Keep symbols alphabetized within each group so changes remain reviewable.

- [ ] **Step 4: Add the local Flask endpoint**

Near the other JSON file constants:

```python
MARKET_ANCHORS_FILE = os.path.join(SCRIPT_DIR, "market_anchor_universe.json")
```

Add a read-only route near `/api/stock-list`:

```python
@app.route("/api/market-anchors")
def api_market_anchors():
    try:
        with open(MARKET_ANCHORS_FILE, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return jsonify(payload)
    except FileNotFoundError:
        return jsonify({"error": "market anchor manifest not found"}), 404
    except (OSError, ValueError) as exc:
        return jsonify({"error": f"market anchor manifest invalid: {exc}"}), 500
```

- [ ] **Step 5: Run manifest, endpoint, and existing server tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_manifest tests.test_shutdown -v
```

Expected: all tests pass; endpoint returns exactly 50 symbols.

- [ ] **Step 6: Commit the manifest boundary**

```bash
git add market_anchor_universe.json Big_movers_server.py \
  tests/test_market_anchor_manifest.py
git commit --only -m "feat: add point-in-time market anchor manifest" -- \
  market_anchor_universe.json Big_movers_server.py \
  tests/test_market_anchor_manifest.py
```

## Task 2: Build Merge-Safe Coverage and CSV Primitives

**Files:**

- Create: `market_anchor_sync.py`
- Create: `tests/test_market_anchor_sync.py`

- [ ] **Step 1: Write failing coverage and merge tests**

Use temporary directories and standard-library `unittest`. Cover:

```python
class MarketAnchorSyncTests(unittest.TestCase):
    def test_audit_marks_complete_short_and_missing(self): ...
    def test_later_listing_changes_required_coverage_start(self): ...
    def test_merge_preserves_rows_outside_requested_range(self): ...
    def test_fetched_rows_win_inside_requested_range(self): ...
    def test_invalid_payload_does_not_modify_original(self): ...
    def test_atomic_write_uses_standard_header_and_sorted_unique_dates(self): ...
```

The central merge assertion should use:

```python
existing = [
    Bar("2014-12-31", 9, 10, 8, 9.5, 100),
    Bar("2020-01-02", 10, 11, 9, 10.5, 200),
    Bar("2026-01-02", 20, 21, 19, 20.5, 300),
]
fetched = [
    Bar("2020-01-02", 100, 101, 99, 100.5, 999),
    Bar("2020-01-03", 101, 102, 100, 101.5, 998),
]
merged = merge_bars(existing, fetched, "2015-01-01", "2025-12-31")
self.assertEqual([b.date for b in merged],
                 ["2014-12-31", "2020-01-02", "2020-01-03", "2026-01-02"])
self.assertEqual(merged[1].close, 100.5)
```

- [ ] **Step 2: Run the focused tests and verify red**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_sync.MarketAnchorSyncTests -v
```

Expected: import failure because `market_anchor_sync.py` does not exist.

- [ ] **Step 3: Implement the small data model and tolerant CSV reader**

In `market_anchor_sync.py`, add:

```python
@dataclasses.dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int

def read_csv_bars(path: pathlib.Path) -> list[Bar]:
    # Accept DateTime/Date and existing index-column layouts.
    # Reject non-finite or non-positive closes.
    # Return ascending unique dates.

def coverage_status(path, start, end) -> str:
    # "missing", "short", or "complete"

def required_range_for_symbol(manifest_row, global_start, global_end):
    # required_start is max(global_start, manifest_row["history_start"])
    # required_end remains global_end
```

Reuse the server's format tolerance, but do not import Flask or pandas.
Every audit call must use the per-symbol required range. A legitimately later
listing therefore becomes `complete` once its local file covers from
`history_start`; it must not remain permanently `short` merely because no bars
exist before its IPO. Anchor eligibility remains separate and must not shorten
the history requested for a company already trading at `data_start`.

- [ ] **Step 4: Implement deterministic merge and atomic writing**

```python
def merge_bars(existing, fetched, requested_start, requested_end):
    by_date = {bar.date: bar for bar in existing}
    for bar in fetched:
        if requested_start <= bar.date <= requested_end:
            by_date[bar.date] = bar
    return [by_date[key] for key in sorted(by_date)]

def atomic_write_csv(path, bars):
    # tempfile.NamedTemporaryFile in path.parent, flush, fsync, os.replace
    # header: DateTime,Open,High,Low,Close,Volume
```

Validate the complete fetched payload before calling `atomic_write_csv`.

- [ ] **Step 5: Run sync primitive tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_sync -v
```

Expected: coverage, merge, preservation, invalid-response, and atomic-write
tests pass.

- [ ] **Step 6: Commit the safe storage layer**

```bash
git add market_anchor_sync.py tests/test_market_anchor_sync.py
git commit --only -m "feat: add merge-safe anchor data storage" -- \
  market_anchor_sync.py tests/test_market_anchor_sync.py
```

## Task 3: Add the Throttled, Resumable Twelve Data Synchronizer

**Files:**

- Modify: `market_anchor_sync.py`
- Create: `tools/sync_market_anchors.py`
- Modify: `tests/test_market_anchor_sync.py`
- Modify: `.gitignore`

- [ ] **Step 1: Write failing client, pacing, retry, and CLI tests**

Inject `opener`, `sleep`, and `clock` dependencies so tests never use the
network or wait:

```python
def test_dry_run_never_calls_opener_or_writes(self): ...
def test_complete_symbol_consumes_no_request(self): ...
def test_attempts_are_at_least_nine_seconds_apart(self): ...
def test_429_uses_retry_after(self): ...
def test_5xx_retries_at_most_three_times(self): ...
def test_transient_retry_waits_increase(self): ...
def test_invalid_key_stops_entire_run(self): ...
def test_credit_exhaustion_stops_run(self): ...
def test_permanent_symbol_error_continues_to_next_symbol(self): ...
def test_resume_reaudits_disk_instead_of_trusting_state(self): ...
def test_max_requests_counts_retries(self): ...
def test_cli_rejects_min_interval_below_nine(self): ...
```

Use a fake response containing a small Twelve Data `values` array and fake
errors for 429, 5xx, invalid key, and API-credit exhaustion.

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_sync -v
```

Expected: failures for missing client, runner, state, and parser functions.

- [ ] **Step 3: Implement manifest/environment loading and API parsing**

Add:

```python
def load_manifest(path): ...
def load_api_key(project_root): ...
def parse_twelve_values(payload) -> list[Bar]: ...

class TwelveDataClient:
    def __init__(self, api_key, opener=None, ssl_context=None): ...
    def fetch_daily(self, symbol, start, end, outputsize=5000): ...
```

Match the existing server's `.env` search and certificate handling. Detect
provider error payloads before parsing `values`.

- [ ] **Step 4: Implement the synchronization runner**

Expose:

```python
def synchronize(
    manifest_path,
    stocks_dir,
    state_path,
    *,
    dry_run=False,
    symbols=None,
    max_requests=50,
    min_interval=9.0,
    start=None,
    end=None,
    client=None,
    sleep=time.sleep,
    clock=time.monotonic,
):
    ...
```

Required behavior:

- reject `min_interval < 9`;
- derive each symbol's required start from manifest `history_start` and
  re-audit that effective range before every decision;
- request the whole configured range once for missing/short files;
- merge, validate, and atomically replace;
- persist attempt/result/range/error after each attempt;
- count retries toward the request cap;
- respect `Retry-After`, otherwise 60 seconds for 429;
- retry transient network/5xx errors at most three times;
- stop for invalid key or credit exhaustion;
- continue after permanent symbol-specific failure;
- return structured skipped/updated/failed/remaining counts.

- [ ] **Step 5: Add the thin CLI**

`tools/sync_market_anchors.py` should only parse arguments, call
`synchronize()`, print the audit/summary, and map fatal errors to non-zero exit
codes. Default paths resolve relative to the project root, not the caller's
working directory.

- [ ] **Step 6: Ignore runtime state**

Append:

```gitignore
.market_anchor_sync_state.json
```

- [ ] **Step 7: Run all synchronizer tests**

Run:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_sync -v
```

Expected: all tests pass instantly with no real network calls or sleeps.

- [ ] **Step 8: Run the real dry-run**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py --dry-run
```

Expected before synchronization: 11 complete and approximately 39 requiring
work after applying each symbol's eligibility-aware required start. Confirm
`git status --short` shows no CSV changes and no tracked state file.

- [ ] **Step 9: Commit the synchronizer**

```bash
git add market_anchor_sync.py tools/sync_market_anchors.py \
  tests/test_market_anchor_sync.py .gitignore
git commit --only -m "feat: add resumable anchor data synchronizer" -- \
  market_anchor_sync.py tools/sync_market_anchors.py \
  tests/test_market_anchor_sync.py .gitignore
```

## Task 4: Synchronize and Verify the 50-Name Historical Dataset

**Files:**

- Create/modify: the 39 audited `collected_stocks/*.csv` paths listed in the
  file responsibility map.
- Must not modify: `big_movers_result.csv`

- [ ] **Step 1: Record the catalogue checksum before network work**

Run:

```bash
shasum -a 256 big_movers_result.csv
git status --short
```

Save the checksum in the task notes/output.

- [ ] **Step 2: Run explicit rate-limited synchronization**

This is the only task that contacts Twelve Data:

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py \
  --max-requests 50 \
  --min-interval 9
```

Expected: no more than 39 successful symbol calls in the first run, attempts
spaced by at least nine seconds, and a final per-symbol summary. If the sandbox
blocks network access, rerun this exact command with the required network
approval rather than changing the implementation.

- [ ] **Step 3: Resume after any provider interruption**

If the first run stops because of a transient/provider limit, rerun the same
command. It must re-audit and skip completed files. Do not manually edit the
state file or CSVs.

- [ ] **Step 4: Run post-sync dry-run and coverage audit**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py --dry-run
```

Expected: all 50 complete, except a symbol whose verified listing/eligibility
legitimately begins after `2015-01-01`; its effective required start is the
manifest `history_start`, and it must be reported as complete rather than
silently short.

- [ ] **Step 5: Verify no catalogue mutation and inspect CSV quality**

Run:

```bash
shasum -a 256 big_movers_result.csv
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest tests.test_market_anchor_sync -v
git diff --check
```

Expected: catalogue checksum unchanged; tests pass; CSVs use the standard
header, ascending unique dates, and no whitespace errors.

- [ ] **Step 6: Commit only the audited data files**

Stage the exact paths printed as updated by the synchronizer. Review
`git diff --stat --cached` before committing, and use the explicit path list so
pre-existing staged changes remain outside the commit.

```bash
git add \
  collected_stocks/MSFT.csv collected_stocks/NVDA.csv \
  collected_stocks/GOOGL.csv collected_stocks/GOOG.csv \
  collected_stocks/META.csv collected_stocks/AVGO.csv \
  collected_stocks/AMD.csv collected_stocks/INTC.csv \
  collected_stocks/COST.csv collected_stocks/ADBE.csv \
  collected_stocks/CSCO.csv collected_stocks/QCOM.csv \
  collected_stocks/AMAT.csv collected_stocks/TXN.csv \
  collected_stocks/INTU.csv collected_stocks/PEP.csv \
  collected_stocks/PLTR.csv collected_stocks/JPM.csv \
  collected_stocks/V.csv collected_stocks/LLY.csv \
  collected_stocks/WMT.csv collected_stocks/XOM.csv \
  collected_stocks/UNH.csv collected_stocks/JNJ.csv \
  collected_stocks/HD.csv collected_stocks/PG.csv \
  collected_stocks/KO.csv collected_stocks/ORCL.csv \
  collected_stocks/IBM.csv collected_stocks/CAT.csv \
  collected_stocks/GE.csv collected_stocks/BA.csv \
  collected_stocks/DIS.csv collected_stocks/MCD.csv \
  collected_stocks/NKE.csv collected_stocks/CVX.csv \
  collected_stocks/ABBV.csv collected_stocks/MRK.csv \
  collected_stocks/GS.csv
git commit --only -m "data: backfill liquid market anchors through 2025" -- \
  collected_stocks/MSFT.csv collected_stocks/NVDA.csv \
  collected_stocks/GOOGL.csv collected_stocks/GOOG.csv \
  collected_stocks/META.csv collected_stocks/AVGO.csv \
  collected_stocks/AMD.csv collected_stocks/INTC.csv \
  collected_stocks/COST.csv collected_stocks/ADBE.csv \
  collected_stocks/CSCO.csv collected_stocks/QCOM.csv \
  collected_stocks/AMAT.csv collected_stocks/TXN.csv \
  collected_stocks/INTU.csv collected_stocks/PEP.csv \
  collected_stocks/PLTR.csv collected_stocks/JPM.csv \
  collected_stocks/V.csv collected_stocks/LLY.csv \
  collected_stocks/WMT.csv collected_stocks/XOM.csv \
  collected_stocks/UNH.csv collected_stocks/JNJ.csv \
  collected_stocks/HD.csv collected_stocks/PG.csv \
  collected_stocks/KO.csv collected_stocks/ORCL.csv \
  collected_stocks/IBM.csv collected_stocks/CAT.csv \
  collected_stocks/GE.csv collected_stocks/BA.csv \
  collected_stocks/DIS.csv collected_stocks/MCD.csv \
  collected_stocks/NKE.csv collected_stocks/CVX.csv \
  collected_stocks/ABBV.csv collected_stocks/MRK.csv \
  collected_stocks/GS.csv
```

Do not stage unrelated working-tree files.

## Task 5: Implement the Pure Seeded Basket Engine

**Files:**

- Create: `portfolio_basket.js`
- Create: `tests/portfolio_balanced_basket.test.cjs`

- [ ] **Step 1: Write failing composition and reproducibility tests**

The Node test imports `portfolio_basket.js` directly. Cover sizes 1–10:

```javascript
test('valid compositions obey the reviewed constraints for sizes 1-10', () => {
  for (let size = 1; size <= 10; size++) {
    for (const c of Basket.validCompositions(size)) {
      assert.equal(c.mover + c.anchor + c.noise, size);
      // Assert special cases or exact percentage/integer bounds.
    }
  }
});

test('all valid compositions are reachable across many seeds', () => { ... });
test('one seed reproduces composition selections and final order', () => { ... });
test('basket selection tries all valid triples with full role constraints', () => { ... });
test('mover takes precedence over anchor for overlapping symbols', () => { ... });
test('three anchors try the opposite 2:1 split before failing', () => { ... });
```

- [ ] **Step 2: Run the Node test and verify red**

```bash
node --test tests/portfolio_balanced_basket.test.cjs
```

Expected: module-not-found failure.

- [ ] **Step 3: Add a browser/Node-compatible module shell**

Use a tiny UMD-style wrapper:

```javascript
(function (root, factory) {
  var api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.PortSimBasket = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';
  // implementation
  return {
    createRng,
    validCompositions,
    orderedCompositions,
    selectBasket,
    selectRoles
  };
});
```

- [ ] **Step 4: Implement seeded allocation**

Implement:

- normalized string/number seeds;
- deterministic PRNG;
- exact special cases for sizes one and two;
- enumeration of reviewed triples for sizes three through ten;
- weight 1 for boundary triples and 2 for non-boundary triples;
- weighted seeded ordering of all valid triples.

Keep cryptographic seed creation outside this pure module; accept a seed value.
Do not use aggregate pool counts as a proxy for fillability: group splits,
mover-over-anchor removal, and deduplication can make a numerically plausible
triple fail.

- [ ] **Step 5: Implement role selection and final shuffling**

`selectRoles()` receives already eligible, shuffled-independent candidate
arrays and:

- selects movers first;
- removes selected movers from anchor candidates;
- enforces anchor group rules and opposite 2:1 fallback;
- excludes all manifest symbols from noise;
- never duplicates a symbol;
- returns `null` instead of a partial basket;
- returns shuffled rows, `roles`, and `composition`.

Add `selectBasket()` above it. It obtains the complete seeded composition order
and calls `selectRoles()` with the actual candidates for each triple. It returns
the first non-null basket and continues to the next triple whenever group
splits, precedence, or deduplication make one fail. It returns `null` only after
every valid triple has been evaluated for that same window.

- [ ] **Step 6: Run module tests**

```bash
node --test tests/portfolio_balanced_basket.test.cjs
```

Expected: all composition, reachability, precedence, fallback, deduplication,
and reproducibility tests pass.

- [ ] **Step 7: Commit the pure engine**

```bash
git add portfolio_basket.js tests/portfolio_balanced_basket.test.cjs
git commit --only -m "feat: add seeded balanced basket engine" -- \
  portfolio_basket.js tests/portfolio_balanced_basket.test.cjs
```

## Task 6: Add Point-in-Time and Pre-Window Candidate Filters

**Files:**

- Modify: `portfolio_basket.js`
- Modify: `tests/portfolio_balanced_basket.test.cjs`

- [ ] **Step 1: Write failing eligibility and liquidity tests**

Add exact cases:

```javascript
test('anchor is eligible only when window start is inside an interval', () => {
  const row = { eligibility: [
    { from: '2018-01-01', to: '2020-12-31' },
    { from: '2023-01-01', to: null }
  ]};
  assert.equal(Basket.isAnchorEligible(row, '2017-12-31'), false);
  assert.equal(Basket.isAnchorEligible(row, '2018-01-01'), true);
  assert.equal(Basket.isAnchorEligible(row, '2021-06-01'), false);
  assert.equal(Basket.isAnchorEligible(row, '2024-01-01'), true);
});

test('noise liquidity ignores every bar on or after hidden start', () => { ... });
test('noise needs 20 bars, $5 close and $20m median dollar volume', () => { ... });
test('coverage requires four calendar months of context through end', () => { ... });
```

Include a test that changes hidden-window prices/volume dramatically and proves
the eligibility result does not change.

- [ ] **Step 2: Run focused tests and verify red**

```bash
node --test tests/portfolio_balanced_basket.test.cjs
```

Expected: missing filter functions.

- [ ] **Step 3: Implement pure candidate predicates**

Add:

```javascript
function isAnchorEligible(anchor, windowStart) { ... }
function hasWindowCoverage(bars, windowStart, windowEnd, contextMonths) { ... }
function noiseLiquidity(bars, windowStart, options) { ... }
```

`noiseLiquidity()` must:

- select only `bar.time < windowStart`;
- retain at most the last 60;
- require at least 20;
- use the last pre-window close;
- compute median of `close * volume`;
- default to `$5` and `$20,000,000`.

- [ ] **Step 4: Run the filter tests**

```bash
node --test tests/portfolio_balanced_basket.test.cjs
```

Expected: all tests pass, including the no-look-ahead mutation test.

- [ ] **Step 5: Commit the candidate filters**

```bash
git add portfolio_basket.js tests/portfolio_balanced_basket.test.cjs
git commit --only -m "feat: add point-in-time basket candidate filters" -- \
  portfolio_basket.js tests/portfolio_balanced_basket.test.cjs
```

## Task 7: Integrate Balanced Resolution into Portfolio Setup

**Files:**

- Modify: `Big_movers.html:7-9`
- Modify: `Big_movers.html:18880-20140`
- Modify: `Big_movers.html:29705-29730`
- Modify: `tests/portfolio_setup_defaults.test.cjs`
- Modify: `tests/offline_local_mode.test.cjs`
- Modify: `tests/portfolio_balanced_basket.test.cjs`

- [ ] **Step 1: Replace default/UI contract tests first**

Assert:

- `<script src="portfolio_basket.js"></script>` is local;
- `#portsim-rand-count` defaults to `6`;
- the checked control is named/labeled Balanced basket;
- old "Cross-year noise" copy is absent;
- randomization source contains `/api/market-anchors` and local
  `/api/ohlcv`;
- randomization contains neither `/api/fetch-ticker` nor an external URL;
- success text does not expose mover/anchor/noise counts;
- when one valid triple lacks capacity but another fits, the same window is
  retained and the first triple that passes full `selectRoles()` constraints is
  used;
- failure retries exactly 12 distinct windows without relaxing quotas; and
- no thirteenth window is attempted.

Update `tests/portfolio_setup_defaults.test.cjs` rather than keeping a stale
legacy-name assertion. Factor the integration resolver as
`_resolveBalancedBasket(options)` with injectable window generation and local
bar loading so the last two behaviors can be tested without DOM or network.

- [ ] **Step 2: Run the three frontend files and confirm red**

```bash
node --test \
  tests/portfolio_setup_defaults.test.cjs \
  tests/offline_local_mode.test.cjs \
  tests/portfolio_balanced_basket.test.cjs
```

Expected: failures for the missing module tag, count `4`, and legacy UI/logic.

- [ ] **Step 3: Load and cache the local manifest**

Add `portfolio_basket.js` after the bundled chart script. In the setup module,
add a per-page cached promise:

```javascript
var _anchorManifestPromise = null;
function _getAnchorManifest() {
  if (!_anchorManifestPromise) {
    _anchorManifestPromise = fetch('/api/market-anchors')
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      });
  }
  return _anchorManifestPromise;
}
```

This is localhost-only and must never fall back to remote data.

- [ ] **Step 4: Add a per-randomization local OHLCV cache**

Replace `_ensureNoiseDataCovers`/`_collectNoiseTickers` with a general local
candidate loader that fetches each symbol at most once during one randomization:

```javascript
function _makeLocalBarsCache() {
  var cache = Object.create(null);
  return function load(sym) {
    if (!cache[sym]) {
      cache[sym] = fetch('/api/ohlcv?symbol=' + encodeURIComponent(sym))
        .then(/* normalize local response; missing becomes [] */);
    }
    return cache[sym];
  };
}
```

Use `PortSimBasket.hasWindowCoverage()` for every category and
`noiseLiquidity()` only for noise.

- [ ] **Step 5: Implement up-to-12-window resolution**

Refactor `handleRandomize()` so Balanced basket mode:

1. creates a cryptographic random seed;
2. chooses a tentative 4–6 month window;
3. resolves coverage-eligible movers;
4. resolves date-eligible anchors from both groups;
5. resolves cross-year noise with the pre-window filter;
6. calls `PortSimBasket.selectBasket()` so every valid composition is attempted
   with actual group, precedence, and deduplication constraints;
7. accepts the first non-null role selection;
8. records that selection's composition;
9. retries a distinct window only when no valid composition can fill it, up to
   12; and
10. reports the limiting pool when all attempts fail.

Do not relax quotas and do not return partial baskets. Preserve legacy
same-year-only selection when Balanced basket is disabled.

- [ ] **Step 6: Update setup defaults and neutral status text**

- change `INITIAL_ROWS` only if needed for setup row seeding, but change random
  count value to six;
- rename the checkbox while retaining its stable DOM id if that minimizes
  migration risk;
- status says `Balanced basket ready` with date range and shuffled symbols;
- do not show category counts or per-symbol roles.

- [ ] **Step 7: Run focused frontend tests**

```bash
node --test \
  tests/portfolio_setup_defaults.test.cjs \
  tests/offline_local_mode.test.cjs \
  tests/portfolio_balanced_basket.test.cjs
```

Expected: all pass; no implicit data fetch route is present.

- [ ] **Step 8: Commit setup integration**

```bash
git add Big_movers.html tests/portfolio_setup_defaults.test.cjs \
  tests/offline_local_mode.test.cjs tests/portfolio_balanced_basket.test.cjs
git commit --only -m "feat: generate balanced portfolio simulation baskets" -- \
  Big_movers.html tests/portfolio_setup_defaults.test.cjs \
  tests/offline_local_mode.test.cjs tests/portfolio_balanced_basket.test.cjs
```

## Task 8: Persist Hidden Generation Metadata and Reveal It in Review

**Files:**

- Modify: `Big_movers.html:18940-19340`
- Modify: `Big_movers.html:19830-19950`
- Modify: `Big_movers.html:20805-20930`
- Modify: `Big_movers.html:27380-27520`
- Modify: `Big_movers.html:27990-28130`
- Modify: `Big_movers.html:28320-28370`
- Modify: `tests/portfolio_balanced_basket.test.cjs`
- Modify: `tests/portfolio_review_execution.test.cjs`

- [ ] **Step 1: Write failing metadata and review tests**

Assert:

- randomization attaches `basketGeneration.version = 1`, mode, seed,
  composition, and roles to the setup config;
- `_bootstrapFromConfig` copies it into `PortSim._state`;
- `_buildMeta` deep-copies it into saved review metadata;
- rerun restores it;
- manual symbol/date edits invalidate it rather than preserving wrong roles;
- legacy review context renders `unknown`;
- live setup/status/card text does not contain role labels;
- review overview contains roles, composition, and seed.

- [ ] **Step 2: Run focused tests and confirm red**

```bash
node --test \
  tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_review_execution.test.cjs
```

Expected: missing metadata propagation and reveal behavior.

- [ ] **Step 3: Carry generation metadata through setup**

Add `basketGeneration: null` to setup state. When balanced randomization
commits a basket, store:

```javascript
{
  version: 1,
  mode: 'balanced',
  seed: String(seed),
  composition: { mover: M, anchor: A, noise: N },
  roles: { AAPL: 'anchor', XYZ: 'mover' }
}
```

Include a deep copy in gathered/published config. Clear it on manual symbol,
row, start-date, or end-date changes. Legacy same-year mode stores
`mode: 'same-year'` with mover roles, but it remains hidden live.

- [ ] **Step 4: Carry metadata into controller and saved review**

Add `_state.basketGeneration = null`; reset it during bootstrap and set it from
the config. Attach `role` to each basket entry for review convenience, while
never rendering it on cards. `_buildMeta()` returns a deep copy of the complete
generation object and includes each basket row's role.

`_onRerun()` copies `meta.basketGeneration` into the reconstructed config.
Legacy metadata produces no inferred role.

- [ ] **Step 5: Reveal only in final review**

In review overview:

- show a compact `BASKET ORIGIN` block;
- display `mover`, `anchor`, or `noise` beside each ticker;
- show the three counts and seed;
- display `unknown` for legacy runs;
- do not add role labels to ticker tabs or live card headers.

Ensure print/PDF uses the same resolved review context.

- [ ] **Step 6: Run metadata and existing review tests**

```bash
node --test \
  tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_review_execution.test.cjs \
  tests/review_form.test.cjs \
  tests/sim_run_stats.test.cjs
```

Expected: all pass, including legacy review compatibility.

- [ ] **Step 7: Commit metadata/review integration**

```bash
git add Big_movers.html tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_review_execution.test.cjs
git commit --only -m "feat: reveal basket origins in portfolio review" -- \
  Big_movers.html tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_review_execution.test.cjs
```

## Task 9: Document, Exercise Offline, and Run the Full Regression Suite

**Files:**

- Modify: `README.md`
- Modify: tests only if verification exposes a real regression

- [ ] **Step 1: Update user documentation**

Document:

- Balanced basket as the default and its three hidden source pools;
- default six and supported range 1–10;
- roles revealed only during review;
- 50-name anchor manifest and fixed `2015-01-01`–`2025-12-31` target;
- `--dry-run`, explicit sync, rate limit, resume, and state behavior;
- anchor CSVs are not added to `big_movers_result.csv`;
- normal simulation remains offline.

- [ ] **Step 2: Run all automated tests**

```bash
node --test tests/*.test.cjs
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  -m unittest discover -s tests -p 'test_*.py' -v
zsh tests/macos_app_lifecycle.test.sh
zsh tests/macos_process_control.test.sh
```

Expected: all JavaScript, Python, and macOS lifecycle/process tests pass.

- [ ] **Step 3: Parse every inline script**

```bash
node -e 'const fs=require("fs"); const h=fs.readFileSync("Big_movers.html","utf8"); const scripts=[...h.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(m=>m[1]).filter(Boolean); scripts.forEach((s,i)=>{try{new Function(s)}catch(e){throw new Error("inline script "+(i+1)+": "+e.message)}}); console.log("Parsed "+scripts.length+" inline scripts")'
```

Expected: all inline scripts parse.

- [ ] **Step 4: Verify offline browser behavior**

Start the local server in a managed terminal session:

```bash
PORTNUM=5063 \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  Big_movers_server.py
```

In another terminal, check the manifest and drive the browser:

```bash
curl -s http://127.0.0.1:5063/api/market-anchors
agent-browser --session bm-balanced open http://127.0.0.1:5063/
agent-browser --session bm-balanced network route 'https://**' --abort
agent-browser --session bm-balanced reload
agent-browser --session bm-balanced wait 700
agent-browser --session bm-balanced eval \
  "document.getElementById('portsim-start-btn').click()"
agent-browser --session bm-balanced eval \
  "document.getElementById('portsim-rand-year').value='2020';document.getElementById('portsim-rand-count').value='6';document.getElementById('portsim-rand-btn').click()"
agent-browser --session bm-balanced wait 5000
agent-browser --session bm-balanced eval \
  "JSON.stringify({count:document.querySelectorAll('.portsim-basket-row').length,status:document.getElementById('portsim-setup-status').textContent})"
agent-browser --session bm-balanced eval \
  "document.getElementById('portsim-setup-submit').click()"
agent-browser --session bm-balanced wait 1000
agent-browser --session bm-balanced eval \
  "document.getElementById('portsim-btn-review').click()"
agent-browser --session bm-balanced wait 500
agent-browser --session bm-balanced eval \
  "document.getElementById('portsim-review-body').innerText"
agent-browser --session bm-balanced network requests --filter '/api/fetch-ticker'
agent-browser --session bm-balanced network requests --filter 'https://'
agent-browser --session bm-balanced errors
agent-browser --session bm-balanced close
```

Stop the managed server session after the browser closes. Confirm:

- the app and local chart library load;
- `/api/market-anchors` returns 50 entries;
- Balanced basket defaults to six and is enabled;
- a representative six-ticker randomization completes;
- setup/status/cards reveal no roles;
- no `/api/fetch-ticker` or external request occurs;
- review reveals the saved roles and seed;
- no browser console errors occur.

- [ ] **Step 5: Verify the data and catalogue invariants**

```bash
/Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  tools/sync_market_anchors.py --dry-run
git diff --check
git status --short
```

Expected: all 50 anchors complete for their eligible target coverage, no
catalogue changes, no runtime state tracked, and only intended files modified.

- [ ] **Step 6: Commit documentation and final test adjustments**

```bash
git add README.md
git commit --only -m "docs: explain balanced basket simulations" -- README.md
```

If verification required a legitimate test correction, commit it separately
with only the exact possible regression paths:

```bash
git add tests/offline_local_mode.test.cjs \
  tests/portfolio_setup_defaults.test.cjs \
  tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_review_execution.test.cjs \
  tests/test_market_anchor_manifest.py \
  tests/test_market_anchor_sync.py
git commit --only -m "test: align balanced basket regressions" -- \
  tests/offline_local_mode.test.cjs \
  tests/portfolio_setup_defaults.test.cjs \
  tests/portfolio_balanced_basket.test.cjs \
  tests/portfolio_review_execution.test.cjs \
  tests/test_market_anchor_manifest.py \
  tests/test_market_anchor_sync.py
```

Skip this second commit when no test file changed.

- [ ] **Step 7: Perform verification-before-completion**

Invoke `superpowers:verification-before-completion`, rerun the relevant final
commands fresh, inspect their output, and only then report the implementation
complete.
