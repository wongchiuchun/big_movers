"""Point-in-time candidate selection for the Entry R:R Trainer."""

import csv
import logging
import math
import os
import random
import threading


GAIN_LOOKBACK = 63
MIN_GAIN = 0.50
EMA_PERIODS = (10, 20)
CONTEXT_BARS = 85
FORWARD_BARS = 90
EXCLUDED_SYMBOLS = {"SPX", "SPY", "NDQ", "NDX"}

RULES = {
    "gainLookback": GAIN_LOOKBACK,
    "minGain": MIN_GAIN,
    "emaPeriods": list(EMA_PERIODS),
    "contextBars": CONTEXT_BARS,
    "forwardBars": FORWARD_BARS,
}

LOGGER = logging.getLogger(__name__)


def _rules_snapshot():
    """Return an independent serializable copy of the fixed v1 rules."""
    snapshot = dict(RULES)
    snapshot["emaPeriods"] = list(RULES["emaPeriods"])
    return snapshot


def resolve_stock_csv_paths(stock_dirs, symbol):
    """Return existing local CSVs in the same priority order as playback."""
    paths = []
    for directory in stock_dirs:
        for filename in (f"{symbol}.csv", f"{symbol.lower()}.csv"):
            path = os.path.join(directory, filename)
            if os.path.isfile(path):
                paths.append(os.path.abspath(path))
                break
    return paths


class CandidateAvailabilityError(Exception):
    """Raised when the fixed candidate pool cannot fill a requested batch."""

    def __init__(self, requested, available):
        self.requested = requested
        self.available = available
        super().__init__(
            "Only {} eligible Entry Trainer candidates are available; {} required."
            .format(available, requested)
        )


class EntryTrainerScanner:
    """Scan local OHLCV CSVs and select fixed-rule, point-in-time candidates."""

    def __init__(self, stock_dirs, parse_bars):
        self._stock_dirs = tuple(stock_dirs)
        self._parse_bars = parse_bars
        self._cache_lock = threading.RLock()
        self._cache_fingerprint = None
        self._cache_candidates = ()

    @property
    def rules(self):
        """Return a fresh serializable snapshot of the fixed version-one rules."""
        return _rules_snapshot()

    def select_candidates(self, count=3):
        """Return a shuffled, unique-symbol batch or raise availability error."""
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            raise ValueError("count must be a positive integer")

        candidates = list(self._eligible_candidates())
        if len(candidates) < count:
            raise CandidateAvailabilityError(count, len(candidates))

        random.SystemRandom().shuffle(candidates)
        return [dict(candidate) for candidate in candidates[:count]]

    def _eligible_candidates(self):
        """Return the fully built cache, publishing it only after a stable scan."""
        with self._cache_lock:
            sources, fingerprint = self._sources_and_fingerprint()
            if fingerprint == self._cache_fingerprint:
                return self._cache_candidates

            # A CSV can be atomically replaced while the catalogue is scanning.
            # Do not publish that scan unless the source fingerprint still matches.
            while True:
                rebuilt = self._build_catalogue(sources)
                current_sources, current_fingerprint = self._sources_and_fingerprint()
                if current_fingerprint == fingerprint:
                    self._cache_candidates = tuple(rebuilt)
                    self._cache_fingerprint = fingerprint
                    return self._cache_candidates
                sources, fingerprint = current_sources, current_fingerprint

    def _sources_and_fingerprint(self):
        symbols = set()
        for directory in self._stock_dirs:
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    if not entry.name.endswith(".csv"):
                        continue
                    symbol = entry.name[:-4].upper()
                    if not symbol or symbol in EXCLUDED_SYMBOLS:
                        continue
                    if not entry.is_file():
                        continue
                    symbols.add(symbol)

        source_groups = []
        sources = []
        for symbol in sorted(symbols):
            paths = []
            for path in resolve_stock_csv_paths(self._stock_dirs, symbol):
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                paths.append(path)
                sources.append((path, stat.st_mtime_ns, stat.st_size))
            if paths:
                # Keep source grouping in STOCKS_DIRS order; it controls
                # duplicate fallback and must stay aligned with playback.
                source_groups.append((symbol, tuple(paths)))

        sources.sort()
        fingerprint = tuple(sources)
        return source_groups, fingerprint

    def _build_catalogue(self, sources):
        candidates = []
        for symbol, paths in sources:
            usable_bars = None
            fatal_source_error = False
            for path in paths:
                try:
                    bars = self._valid_bars(self._parse_bars(path))
                except (OSError, UnicodeError, csv.Error) as exc:
                    LOGGER.warning("Skipping Entry Trainer source %s (%s): %s", symbol, path, exc)
                    fatal_source_error = True
                    break
                if bars:
                    usable_bars = bars
                    break

            # A usable higher-priority source is what playback will load. Its
            # lack of qualification must not cause a lower-priority fallback.
            if fatal_source_error or usable_bars is None:
                continue
            candidate = self._find_candidate(symbol, usable_bars)
            if candidate is not None:
                candidates.append(candidate)
        return candidates

    @staticmethod
    def _valid_bars(raw_bars):
        valid = []
        for bar in raw_bars or ():
            try:
                close = float(bar["close"])
                time = str(bar["time"]).strip()
            except (KeyError, TypeError, ValueError):
                continue
            if not time or not math.isfinite(close) or close <= 0:
                continue
            valid.append({"time": time, "close": close})
        valid.sort(key=lambda bar: bar["time"])
        return valid

    @staticmethod
    def _find_candidate(symbol, bars):
        if len(bars) <= CONTEXT_BARS + FORWARD_BARS:
            return None

        ema_values = {period: None for period in EMA_PERIODS}
        for index, bar in enumerate(bars):
            close = bar["close"]
            for period in EMA_PERIODS:
                ema = ema_values[period]
                if ema is None:
                    ema_values[period] = close
                else:
                    alpha = 2.0 / (period + 1)
                    ema_values[period] = alpha * close + (1.0 - alpha) * ema

            if index < CONTEXT_BARS or index + FORWARD_BARS >= len(bars):
                continue
            gain = close / bars[index - GAIN_LOOKBACK]["close"] - 1.0
            if (
                gain >= MIN_GAIN
                and close > ema_values[10]
                and close > ema_values[20]
            ):
                return {
                    "symbol": symbol,
                    "qualificationDate": bar["time"],
                    "qualificationBar": index,
                    "contextStartDate": bars[index - CONTEXT_BARS]["time"],
                    "endDate": bars[index + FORWARD_BARS]["time"],
                    "rules": _rules_snapshot(),
                }
        return None
