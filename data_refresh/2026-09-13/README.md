# 2026 YTD stock-list refresh

Price cutoff: **September 11, 2026**, the last completed US trading session before this refresh on September 13.

## Outputs

- `2026_ytd_over_100.csv`: 988 screened common-stock/ADR matches with current daily data and no flagged discontinuity. This is the clean refresh subset, not a claim that every US stock has been verified.
- `needs_review.csv`: 397 candidates or existing entries held out of the refresh for split adjustment, large daily discontinuities, stale data, or incompatible existing price scales. A flag is not proof that a move is invalid: real episodic pivots can also trigger it.
- `import_summary.json`: exact import counts, retained legacy entries, and study-file integrity hashes.
- `before_refresh.zip`: pre-import catalogue and every overwritten chart file.
- `cross_checks.json`: eight liquid-name maximum gains independently recomputed with Twelve Data; all match the Yahoo calculation within 0.02 percentage points through September 11.
- `fetch_status.json`: five daily-history fetch failures: ACLX, DAWN, EVTV, NGD, RAPT.
- `universe.json`, `candidates.json`, `raw/`, `twelve/`, `analysis.json`: source snapshots and audit evidence.

## Definition and scope

The qualifying move is strictly **greater than 100%**, measured from an earlier daily **close** to a later daily **close** within January 1–September 11, 2026. Find the running minimum close chronologically and maximize `(later close / earlier minimum close - 1) * 100`. It is not January-to-current return, an unordered annual high/low range, or an intraday low-to-high measure. Prices use the provider close series, not dividend-adjusted total return.

The discovery universe contains 6,103 securities from TradingView's NASDAQ/NYSE/AMEX stock and depositary-receipt universe. The inexpensive prefilter keeps securities with a 52-week high/low ratio greater than 2, missing range fields, and all existing 2026 catalogue entries. Since the 52-week window contains 2026 YTD, an accurate range is a necessary bound for a YTD doubling. Daily history was requested for 3,094 candidates; 3,089 succeeded. New additions are restricted to common stocks and depositary receipts; existing catalogue instruments are retained. No minimum price, market capitalization, or liquidity requirement was added.

This is a current-listing screen, so delisted names, ticker changes, omissions in the source universe, and incorrect prefilter fields can prevent discovery. 397 flagged rows and five failed histories remain unresolved; this refresh is not exhaustive market coverage. Existing 2026 entries that could not be refreshed safely remain unchanged in the application and are listed in `import_summary.json`; they are not included in the clean CSV.

Conservative quality gates hold out all candidates with recorded 2026 splits, extreme daily changes/gaps (more than 2x or below 0.25x previous close), stale last bars, or a median overlapping-history price-scale difference above 2%. This deliberately leaves some real movers for review rather than guessing corporate-action adjustments. A concrete known issue: Aspire's May 2026 1-for-30 split was missing from the returned Yahoo split-event list, and both vendors retained a large price discontinuity. See [the issuer's SEC filing](https://www.sec.gov/Archives/edgar/data/1847345/000149315226023069/form8-k.htm).

## Application changes

Added 898 qualifying 2026 rows and refreshed 122 existing rows, including 32 existing entries below the cutoff. Existing lower-gain entries are retained for study continuity; choose year 2026 and a minimum-gain filter in the app, or use the standalone clean CSV for the strict >100% subset.

For existing chart files, pre-2026 parsed OHLCV history is preserved and 2026 bars are replaced with the fetched daily series. New files include available 2025 history for moving-average and base context. Earlier-year catalogue rows, drawings, metadata, and reviews are not rewritten. Chart-file backups allow rollback.

`avg_vol_b` is estimated monthly dollar turnover in billions: mean(2026 daily close × volume) × 21 / 1e9, rounded to two decimals. This follows the application's `$B/mo` display. It is a 21-session approximation, not actual calendar-month turnover. Very illiquid names can round to 0.00.

## Sources

- [TradingView US screener](https://www.tradingview.com/screener/), snapshot from `https://scanner.tradingview.com/america/scan`.
- [Yahoo Finance historical prices](https://finance.yahoo.com/quote/AAOI/history/), daily JSON from `https://query2.finance.yahoo.com/v8/finance/chart/{symbol}` with January 1, 2025–September 12, 2026 exclusive bounds.
- [Twelve Data time-series documentation](https://twelvedata.com/docs#time-series). Account limits observed: 8 credits/minute and 800/day. Used for independent spot checks; credentials are not stored in these audit files.
