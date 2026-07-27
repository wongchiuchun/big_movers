"""Merge-safe CSV storage primitives for historical market-anchor bars."""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import email.utils
import http.client
import json
import math
import os
import pathlib
import re
import ssl
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping


MIN_DAILY_BAR_DENSITY = 0.95
MAX_MISSING_WEEKDAY_GAP = 10
TWELVE_DATA_URL = "https://api.twelvedata.com/time_series"
MAX_ATTEMPTS_PER_SYMBOL = 3


@dataclasses.dataclass(frozen=True)
class Bar:
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def _parse_date(value: object) -> str:
    text = str(value).strip()
    date_text = text[:10]
    if len(text) > 10 and text[10] not in {" ", "T"}:
        raise ValueError(f"invalid bar date: {text!r}")
    try:
        parsed = dt.date.fromisoformat(date_text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid bar date: {text!r}") from exc
    return parsed.isoformat()


def _validated_bar(bar: object) -> Bar:
    if not isinstance(bar, Bar):
        raise ValueError("bars must be Bar instances")

    date = _parse_date(bar.date)
    values = []
    for field_name in ("open", "high", "low", "close"):
        raw_value = getattr(bar, field_name)
        if isinstance(raw_value, bool):
            raise ValueError(f"invalid {field_name} for {date}")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field_name} for {date}") from exc
        if not math.isfinite(value):
            raise ValueError(f"non-finite {field_name} for {date}")
        values.append(value)

    if values[3] <= 0:
        raise ValueError(f"close must be positive for {date}")

    if isinstance(bar.volume, bool):
        raise ValueError(f"invalid volume for {date}")
    try:
        volume_number = float(bar.volume)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid volume for {date}") from exc
    if (
        not math.isfinite(volume_number)
        or volume_number < 0
        or not volume_number.is_integer()
    ):
        raise ValueError(f"invalid volume for {date}")

    return Bar(date, *values, int(volume_number))


def _sorted_unique_bars(bars: Iterable[object]) -> list[Bar]:
    by_date: dict[str, Bar] = {}
    for raw_bar in bars:
        bar = _validated_bar(raw_bar)
        by_date[bar.date] = bar
    return [by_date[date] for date in sorted(by_date)]


def read_csv_bars(path: pathlib.Path | str) -> list[Bar]:
    """Read a supported bar CSV and return validated, sorted, unique bars.

    DateTime and Date headers are accepted. Extra columns, including blank or
    ``Unnamed`` index columns produced by common CSV writers, are ignored.
    Duplicate dates resolve deterministically in favor of the last row.
    """

    csv_path = pathlib.Path(path)
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {csv_path}")

        fields_by_name = {
            field.strip().lower(): field
            for field in reader.fieldnames
            if field is not None
        }
        date_field = fields_by_name.get("datetime") or fields_by_name.get("date")
        required_fields = {
            name: fields_by_name.get(name.lower())
            for name in ("Open", "High", "Low", "Close", "Volume")
        }
        if date_field is None or any(field is None for field in required_fields.values()):
            raise ValueError(f"CSV is missing required bar columns: {csv_path}")

        bars = []
        for line_number, row in enumerate(reader, start=2):
            try:
                bars.append(
                    Bar(
                        _parse_date(row[date_field]),
                        float(row[required_fields["Open"]]),
                        float(row[required_fields["High"]]),
                        float(row[required_fields["Low"]]),
                        float(row[required_fields["Close"]]),
                        _parse_volume(row[required_fields["Volume"]]),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"malformed bar at {csv_path}:{line_number}"
                ) from exc

    return _sorted_unique_bars(bars)


def _parse_volume(value: object) -> int:
    number = float(value)
    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError("volume must be a non-negative integer")
    return int(number)


def _weekday_on_or_after(value: dt.date) -> dt.date:
    while value.weekday() >= 5:
        value += dt.timedelta(days=1)
    return value


def _weekday_on_or_before(value: dt.date) -> dt.date:
    while value.weekday() >= 5:
        value -= dt.timedelta(days=1)
    return value


def _shift_weekdays(value: dt.date, count: int) -> dt.date:
    direction = 1 if count >= 0 else -1
    remaining = abs(count)
    while remaining:
        value += dt.timedelta(days=direction)
        if value.weekday() < 5:
            remaining -= 1
    return value


def _count_weekdays(start: dt.date, end: dt.date) -> int:
    count = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            count += 1
        current += dt.timedelta(days=1)
    return count


def _max_missing_weekday_gap(
    start: dt.date, end: dt.date, covered_dates: set[dt.date]
) -> int:
    maximum_gap = 0
    current_gap = 0
    current = start
    while current <= end:
        if current.weekday() < 5:
            if current in covered_dates:
                current_gap = 0
            else:
                current_gap += 1
                maximum_gap = max(maximum_gap, current_gap)
        current += dt.timedelta(days=1)
    return maximum_gap


def coverage_status(
    path: pathlib.Path | str, start: str, end: str
) -> str:
    """Return ``missing``, ``short``, or ``complete`` for a requested range.

    Weekend boundaries move inward to a weekday. One further weekday of grace
    is allowed at each edge for exchange holidays. In addition, valid unique
    rows must cover at least ``MIN_DAILY_BAR_DENSITY`` of weekdays in the
    adjusted interval, with no run longer than ``MAX_MISSING_WEEKDAY_GAP``.
    These checks tolerate normal holidays and modest gaps while rejecting
    hollow histories that contain only boundary rows.
    """

    csv_path = pathlib.Path(path)
    if not csv_path.is_file():
        return "missing"

    start_date = dt.date.fromisoformat(_parse_date(start))
    end_date = dt.date.fromisoformat(_parse_date(end))
    if start_date > end_date:
        raise ValueError("coverage start must not be after end")

    try:
        bars = read_csv_bars(csv_path)
    except (OSError, ValueError):
        return "short"
    if not bars:
        return "short"

    effective_start = _weekday_on_or_after(start_date)
    effective_end = _weekday_on_or_before(end_date)
    latest_acceptable_start = _shift_weekdays(effective_start, 1)
    earliest_acceptable_end = _shift_weekdays(effective_end, -1)

    in_range_bars = [
        bar
        for bar in bars
        if effective_start.isoformat() <= bar.date <= effective_end.isoformat()
    ]
    if not in_range_bars:
        return "short"

    required_weekdays = _count_weekdays(effective_start, effective_end)
    covered_dates = {
        date
        for bar in in_range_bars
        if (date := dt.date.fromisoformat(bar.date)).weekday() < 5
    }
    covered_weekdays = len(covered_dates)
    density_complete = (
        required_weekdays == 0
        or covered_weekdays / required_weekdays >= MIN_DAILY_BAR_DENSITY
    )
    gap_complete = (
        _max_missing_weekday_gap(
            effective_start, effective_end, covered_dates
        )
        <= MAX_MISSING_WEEKDAY_GAP
    )
    return (
        "complete"
        if in_range_bars[0].date <= latest_acceptable_start.isoformat()
        and in_range_bars[-1].date >= earliest_acceptable_end.isoformat()
        and density_complete
        and gap_complete
        else "short"
    )


def required_range_for_symbol(
    manifest_row: Mapping[str, object], global_start: str, global_end: str
) -> tuple[str, str]:
    """Return the symbol's history range, independent of eligibility dates."""

    start = dt.date.fromisoformat(_parse_date(global_start))
    history_start = dt.date.fromisoformat(_parse_date(manifest_row["history_start"]))
    end = dt.date.fromisoformat(_parse_date(global_end))
    required_start = max(start, history_start)
    if required_start > end:
        raise ValueError("required history start must not be after end")
    return required_start.isoformat(), end.isoformat()


def merge_bars(
    existing: Iterable[object],
    fetched: Iterable[object],
    requested_start: str,
    requested_end: str,
) -> list[Bar]:
    """Merge fetched bars into the requested range without discarding history."""

    start = _parse_date(requested_start)
    end = _parse_date(requested_end)
    if start > end:
        raise ValueError("requested start must not be after end")

    existing_bars = _sorted_unique_bars(existing)
    fetched_bars = _sorted_unique_bars(fetched)
    by_date = {bar.date: bar for bar in existing_bars}
    for bar in fetched_bars:
        if start <= bar.date <= end:
            by_date[bar.date] = bar
    return [by_date[date] for date in sorted(by_date)]


def atomic_write_csv(path: pathlib.Path | str, bars: Iterable[object]) -> None:
    """Atomically write fully validated bars in the standard CSV layout."""

    csv_path = pathlib.Path(path)
    validated_bars = _sorted_unique_bars(bars)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=csv_path.parent,
            prefix=f".{csv_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = pathlib.Path(handle.name)
            writer = csv.writer(handle, lineterminator="\n")
            writer.writerow(["DateTime", "Open", "High", "Low", "Close", "Volume"])
            for bar in validated_bars:
                writer.writerow(
                    [
                        bar.date,
                        bar.open,
                        bar.high,
                        bar.low,
                        bar.close,
                        bar.volume,
                    ]
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, csv_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def update_csv_bars(
    path: pathlib.Path | str,
    fetched: Iterable[object],
    requested_start: str,
    requested_end: str,
) -> list[Bar]:
    """Validate, merge, and atomically persist a fetched payload."""

    fetched_bars = _sorted_unique_bars(fetched)
    csv_path = pathlib.Path(path)
    existing_bars = read_csv_bars(csv_path) if csv_path.exists() else []
    merged = merge_bars(
        existing_bars, fetched_bars, requested_start, requested_end
    )
    atomic_write_csv(csv_path, merged)
    return merged


class MarketAnchorSyncError(Exception):
    """Base class for expected synchronization errors."""


class ProviderError(MarketAnchorSyncError):
    """Base class for typed Twelve Data failures."""


class TransientError(ProviderError):
    """A retryable transport or provider failure."""


class TransientNetworkError(TransientError):
    """A retryable network failure."""


class TransientHTTPError(TransientError):
    """A retryable HTTP server failure."""

    def __init__(self, status: int):
        self.status = status
        super().__init__(f"temporary HTTP {status} response")


class RateLimitError(TransientError):
    """A retryable rate limit with an optional provider delay."""

    def __init__(self, retry_after: float | None = None):
        self.retry_after = retry_after
        super().__init__("Twelve Data rate limit reached")


class FatalProviderError(ProviderError):
    """A provider failure that makes further requests unsafe or useless."""


class InvalidAPIKeyError(FatalProviderError):
    """The configured Twelve Data credential is invalid."""


class CreditExhaustedError(FatalProviderError):
    """The account has no usable API credits or quota."""


# A descriptive compatibility spelling for callers that prefer the noun form.
CreditExhaustionError = CreditExhaustedError


class PermanentSymbolError(ProviderError):
    """A non-retryable response affecting the current symbol."""


def load_manifest(path: pathlib.Path | str) -> dict[str, object]:
    """Load and validate the synchronization fields in an anchor manifest."""

    manifest_path = pathlib.Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load manifest: {manifest_path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("manifest must be a JSON object")

    try:
        data_start = _parse_date(payload["data_start"])
        data_end = _parse_date(payload["data_end"])
        raw_symbols = payload["symbols"]
    except KeyError as exc:
        raise ValueError(f"manifest is missing {exc.args[0]}") from exc
    if data_start > data_end:
        raise ValueError("manifest data_start must not be after data_end")
    if not isinstance(raw_symbols, list) or not raw_symbols:
        raise ValueError("manifest symbols must be a non-empty list")

    normalized_rows = []
    seen_symbols: set[str] = set()
    for index, raw_row in enumerate(raw_symbols):
        if not isinstance(raw_row, Mapping):
            raise ValueError(f"manifest symbol at index {index} must be an object")
        symbol = str(raw_row.get("symbol", "")).strip().upper()
        if (
            not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]*", symbol)
            or ".." in symbol
        ):
            raise ValueError(f"invalid manifest symbol: {symbol!r}")
        if symbol in seen_symbols:
            raise ValueError(f"duplicate manifest symbol: {symbol}")
        seen_symbols.add(symbol)
        try:
            history_start = _parse_date(raw_row["history_start"])
        except KeyError as exc:
            raise ValueError(f"{symbol} is missing history_start") from exc
        if history_start > data_end:
            raise ValueError(f"{symbol} history_start must not be after data_end")

        row = dict(raw_row)
        row["symbol"] = symbol
        row["history_start"] = history_start
        normalized_rows.append(row)

    manifest = dict(payload)
    manifest["data_start"] = data_start
    manifest["data_end"] = data_end
    manifest["symbols"] = normalized_rows
    return manifest


def load_api_key(project_root: pathlib.Path | str) -> str | None:
    """Load TWELVE_API_KEY using the server's project, then parent, search."""

    root = pathlib.Path(project_root)
    for env_path in (root / ".env", root.parent / ".env"):
        try:
            lines = env_path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"cannot read environment file: {env_path}") from exc
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("TWELVE_API_KEY="):
                key = stripped.split("=", 1)[1].strip()
                if key:
                    return key
                break
    return None


def _provider_exception(
    payload: Mapping[str, object], *, force: bool = False
) -> ProviderError | None:
    status = str(payload.get("status", "")).strip().lower()
    has_error = (
        status == "error"
        or ("code" in payload and "message" in payload)
        or (force and ("code" in payload or "message" in payload))
    )
    if not has_error:
        return None

    message = str(payload.get("message") or "Twelve Data provider error").strip()
    lowered = message.lower()
    try:
        code = int(payload.get("code", 0))
    except (TypeError, ValueError):
        code = 0

    if any(term in lowered for term in ("credit", "quota", "run out")):
        return CreditExhaustedError("Twelve Data API credits are exhausted")
    if code in {401, 403} or any(
        term in lowered
        for term in ("api key", "apikey", "authentication", "unauthorized")
    ):
        return InvalidAPIKeyError("invalid Twelve Data API key")
    if code == 429 or "rate limit" in lowered or "too many requests" in lowered:
        return RateLimitError()
    if 500 <= code <= 599:
        return TransientHTTPError(code)
    return PermanentSymbolError(message)


def parse_twelve_values(payload: object) -> list[Bar]:
    """Parse, fully validate, and normalize a Twelve Data time series."""

    if not isinstance(payload, Mapping):
        raise PermanentSymbolError("Twelve Data payload must be an object")
    provider_error = _provider_exception(payload)
    if provider_error is not None:
        raise provider_error

    values = payload.get("values")
    if not isinstance(values, list) or not values:
        raise PermanentSymbolError("Twelve Data payload has no values")

    bars = []
    required_fields = ("datetime", "open", "high", "low", "close", "volume")
    for index, value in enumerate(values):
        if not isinstance(value, Mapping):
            raise PermanentSymbolError(
                f"Twelve Data value at index {index} must be an object"
            )
        missing = [field for field in required_fields if field not in value]
        if missing:
            raise PermanentSymbolError(
                f"Twelve Data value at index {index} is missing {missing[0]}"
            )
        try:
            bar = Bar(
                _parse_date(value["datetime"]),
                float(value["open"]),
                float(value["high"]),
                float(value["low"]),
                float(value["close"]),
                _parse_volume(value["volume"]),
            )
            validated_bar = _validated_bar(bar)
        except (TypeError, ValueError):
            pass
        else:
            bars.append(validated_bar)
            continue
        raise PermanentSymbolError(
            f"invalid Twelve Data value at index {index}"
        )
    return _sorted_unique_bars(bars)


def _retry_after_seconds(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    try:
        seconds = float(text)
    except ValueError:
        try:
            retry_at = email.utils.parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=dt.timezone.utc)
        seconds = (
            retry_at - dt.datetime.now(dt.timezone.utc)
        ).total_seconds()
    if not math.isfinite(seconds):
        return None
    return max(0.0, seconds)


def _decode_json_bytes(body: bytes) -> Mapping[str, object] | None:
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _default_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        context.load_verify_locations(certifi.where())
    return context


def _redact_provider_error(error: ProviderError, api_key: str) -> None:
    message = str(error).replace(api_key, "[redacted]")
    error.args = (message,)


class TwelveDataClient:
    """Small injectable client for Twelve Data's official time-series API."""

    def __init__(
        self,
        api_key: str,
        opener=None,
        ssl_context: ssl.SSLContext | None = None,
    ):
        key = str(api_key).strip()
        if not key:
            raise ValueError("Twelve Data API key is required")
        self.api_key = key
        self.opener = opener or urllib.request.urlopen
        self.ssl_context = (
            ssl_context if ssl_context is not None else _default_ssl_context()
        )

    def fetch_daily(
        self,
        symbol: str,
        start: str,
        end: str,
        outputsize: int = 5000,
    ) -> list[Bar]:
        if isinstance(outputsize, bool) or not isinstance(outputsize, int):
            raise ValueError("outputsize must be an integer")
        if outputsize < 1 or outputsize > 5000:
            raise ValueError("outputsize must be between 1 and 5000")
        start_date = _parse_date(start)
        end_date = _parse_date(end)
        if start_date > end_date:
            raise ValueError("request start must not be after end")

        query = urllib.parse.urlencode(
            {
                "symbol": str(symbol).strip().upper(),
                "interval": "1day",
                "start_date": start_date,
                "end_date": end_date,
                "outputsize": str(outputsize),
            }
        )
        request = urllib.request.Request(
            f"{TWELVE_DATA_URL}?{query}",
            headers={
                "Authorization": f"apikey {self.api_key}",
                "User-Agent": "BigMoversAnchorSync/1.0",
            },
        )
        try:
            with self.opener(
                request, timeout=30, context=self.ssl_context
            ) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            body_read_failure: BaseException | None = None
            try:
                error_body = exc.read()
            except (http.client.IncompleteRead, OSError) as read_error:
                body_read_failure = read_error
                error_body = b""
            payload = (
                _decode_json_bytes(error_body)
                if body_read_failure is None
                else None
            )
            provider_error = (
                _provider_exception(payload, force=True)
                if payload is not None
                else None
            )
            if isinstance(
                provider_error, (InvalidAPIKeyError, CreditExhaustedError)
            ):
                raise provider_error from exc
            if exc.code == 429:
                retry_after = _retry_after_seconds(
                    exc.headers.get("Retry-After") if exc.headers else None
                )
                raise RateLimitError(retry_after) from (
                    body_read_failure or exc
                )
            if exc.code in {401, 403}:
                raise InvalidAPIKeyError(
                    "invalid Twelve Data API key"
                ) from (body_read_failure or exc)
            if 500 <= exc.code <= 599:
                if body_read_failure is not None:
                    raise TransientNetworkError(
                        "temporary Twelve Data network failure"
                    ) from body_read_failure
                raise TransientHTTPError(exc.code) from exc
            if body_read_failure is not None:
                raise PermanentSymbolError(
                    f"Twelve Data HTTP {exc.code} response"
                ) from body_read_failure
            if provider_error is not None:
                _redact_provider_error(provider_error, self.api_key)
                raise provider_error from exc
            raise PermanentSymbolError(
                f"Twelve Data HTTP {exc.code} response"
            ) from exc
        except (
            urllib.error.URLError,
            http.client.IncompleteRead,
            TimeoutError,
            OSError,
        ) as exc:
            raise TransientNetworkError(
                "temporary Twelve Data network failure"
            ) from exc

        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            invalid_json = True
        else:
            invalid_json = False
        if invalid_json:
            raise TransientNetworkError(
                "invalid or incomplete Twelve Data JSON response"
            )
        try:
            return parse_twelve_values(payload)
        except ProviderError as exc:
            _redact_provider_error(exc, self.api_key)
            raise


def _atomic_write_json(path: pathlib.Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: pathlib.Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = pathlib.Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _load_state(path: pathlib.Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, Mapping):
        payload = {}
    state = dict(payload)
    if not isinstance(state.get("attempts"), list):
        state["attempts"] = []
    if not isinstance(state.get("symbols"), Mapping):
        state["symbols"] = {}
    state["version"] = 1
    return state


def _safe_error_message(error: BaseException, client: object) -> str:
    message = str(error) or type(error).__name__
    api_key = getattr(client, "api_key", None)
    if api_key:
        message = message.replace(str(api_key), "[redacted]")
    return message


def _normalized_requested_symbols(
    symbols: object, rows: list[Mapping[str, object]]
) -> list[Mapping[str, object]]:
    if symbols is None:
        return rows
    if isinstance(symbols, str):
        raw_values = [symbols]
    else:
        try:
            raw_values = list(symbols)
        except TypeError as exc:
            raise ValueError("symbols must be a string or iterable") from exc

    requested = []
    for raw_value in raw_values:
        requested.extend(
            part.strip().upper()
            for part in str(raw_value).split(",")
            if part.strip()
        )
    if not requested:
        raise ValueError("symbols must not be empty")
    if len(requested) != len(set(requested)):
        raise ValueError("symbols must not contain duplicates")

    rows_by_symbol = {str(row["symbol"]): row for row in rows}
    unknown = [symbol for symbol in requested if symbol not in rows_by_symbol]
    if unknown:
        raise ValueError(f"symbols are not in the manifest: {', '.join(unknown)}")
    requested_set = set(requested)
    return [row for row in rows if str(row["symbol"]) in requested_set]


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
    """Audit and safely synchronize manifest symbols with global throttling."""

    if isinstance(min_interval, bool):
        raise ValueError("min_interval must be a number")
    try:
        interval = float(min_interval)
    except (TypeError, ValueError) as exc:
        raise ValueError("min_interval must be a number") from exc
    if not math.isfinite(interval) or interval < 9:
        raise ValueError("min_interval must be at least 9 seconds")
    if (
        isinstance(max_requests, bool)
        or not isinstance(max_requests, int)
        or max_requests < 1
    ):
        raise ValueError("max_requests must be a positive integer")

    manifest_file = pathlib.Path(manifest_path)
    manifest = load_manifest(manifest_file)
    rows = _normalized_requested_symbols(symbols, list(manifest["symbols"]))
    configured_start = _parse_date(
        start if start is not None else manifest["data_start"]
    )
    configured_end = _parse_date(
        end if end is not None else manifest["data_end"]
    )
    if configured_start > configured_end:
        raise ValueError("synchronization start must not be after end")

    work = []
    for row in rows:
        history_start = _parse_date(row["history_start"])
        if history_start > configured_end:
            work.append(
                (row, configured_start, configured_end, False)
            )
        else:
            required_start, required_end = required_range_for_symbol(
                row, configured_start, configured_end
            )
            work.append((row, required_start, required_end, True))

    stocks_path = pathlib.Path(stocks_dir)
    runtime_state_path = pathlib.Path(state_path)
    result = {
        "complete": 0,
        "skipped": 0,
        "updated": 0,
        "failed": 0,
        "remaining": 0,
        "requests": 0,
        "fatal": None,
        "error": None,
        "details": [],
    }
    state = None if dry_run else _load_state(runtime_state_path)
    active_client = client
    last_attempt_started: float | None = None
    global_rate_limit_ready_at: float | None = None

    def add_detail(
        symbol: str,
        status: str,
        required_start: str,
        required_end: str,
        *,
        coverage: str | None = None,
        error: str | None = None,
    ) -> None:
        detail = {
            "symbol": symbol,
            "status": status,
            "range": {"start": required_start, "end": required_end},
        }
        if coverage is not None:
            detail["coverage"] = coverage
        if error is not None:
            detail["error"] = error
        result["details"].append(detail)

    def record_attempt(
        symbol: str,
        attempt: int,
        required_start: str,
        required_end: str,
        attempt_result: str,
        error: str | None,
    ) -> None:
        event = {
            "symbol": symbol,
            "attempt": attempt,
            "request": result["requests"],
            "range": {"start": required_start, "end": required_end},
            "result": attempt_result,
            "error": error,
            "at_monotonic": clock(),
        }
        state["attempts"].append(event)
        state["symbols"] = dict(state["symbols"])
        state["symbols"][symbol] = event
        _atomic_write_json(runtime_state_path, state)

    fatal_index: int | None = None
    for work_index, (
        row,
        required_start,
        required_end,
        applicable,
    ) in enumerate(work):
        symbol = str(row["symbol"])
        if not applicable:
            result["skipped"] += 1
            add_detail(
                symbol,
                "skipped",
                required_start,
                required_end,
                coverage="not_applicable",
            )
            continue
        csv_path = stocks_path / f"{symbol}.csv"
        coverage = coverage_status(csv_path, required_start, required_end)
        if coverage == "complete":
            result["complete"] += 1
            result["skipped"] += 1
            add_detail(
                symbol,
                "skipped",
                required_start,
                required_end,
                coverage=coverage,
            )
            continue
        if dry_run:
            result["remaining"] += 1
            add_detail(
                symbol,
                "remaining",
                required_start,
                required_end,
                coverage=coverage,
            )
            continue
        if result["requests"] >= max_requests:
            result["remaining"] += 1
            add_detail(
                symbol,
                "remaining",
                required_start,
                required_end,
                coverage=coverage,
                error="request cap reached",
            )
            continue

        if active_client is None:
            api_key = load_api_key(manifest_file.parent)
            if not api_key:
                result["fatal"] = "missing_api_key"
                result["error"] = "TWELVE_API_KEY not found in .env"
                fatal_index = work_index
                break
            active_client = TwelveDataClient(api_key)

        attempt = 0
        retry_ready_at: float | None = None
        while True:
            # State is diagnostic only: re-audit the file before every request.
            coverage = coverage_status(csv_path, required_start, required_end)
            if coverage == "complete":
                result["complete"] += 1
                result["skipped"] += 1
                add_detail(
                    symbol,
                    "skipped",
                    required_start,
                    required_end,
                    coverage=coverage,
                )
                break
            if result["requests"] >= max_requests:
                result["remaining"] += 1
                add_detail(
                    symbol,
                    "remaining",
                    required_start,
                    required_end,
                    coverage=coverage,
                    error="request cap reached",
                )
                break

            if last_attempt_started is not None:
                ready_at = last_attempt_started + interval
                if global_rate_limit_ready_at is not None:
                    ready_at = max(ready_at, global_rate_limit_ready_at)
                if retry_ready_at is not None:
                    ready_at = max(ready_at, retry_ready_at)
                wait = ready_at - clock()
                if wait > 0:
                    sleep(wait)

            last_attempt_started = clock()
            retry_ready_at = None
            attempt += 1
            result["requests"] += 1
            try:
                fetched = active_client.fetch_daily(
                    symbol, required_start, required_end, outputsize=5000
                )
            except RateLimitError as exc:
                message = _safe_error_message(exc, active_client)
                retry_delay = (
                    exc.retry_after if exc.retry_after is not None else 60.0
                )
                rate_limit_ready_at = clock() + retry_delay
                global_rate_limit_ready_at = max(
                    global_rate_limit_ready_at or rate_limit_ready_at,
                    rate_limit_ready_at,
                )
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "rate_limited",
                    message,
                )
                if attempt >= MAX_ATTEMPTS_PER_SYMBOL:
                    result["failed"] += 1
                    add_detail(
                        symbol,
                        "failed",
                        required_start,
                        required_end,
                        coverage=coverage,
                        error=message,
                    )
                    break
                continue
            except TransientError as exc:
                message = _safe_error_message(exc, active_client)
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "transient_error",
                    message,
                )
                if attempt >= MAX_ATTEMPTS_PER_SYMBOL:
                    result["failed"] += 1
                    add_detail(
                        symbol,
                        "failed",
                        required_start,
                        required_end,
                        coverage=coverage,
                        error=message,
                    )
                    break
                retry_ready_at = clock() + interval * attempt
                continue
            except InvalidAPIKeyError as exc:
                message = _safe_error_message(exc, active_client)
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "invalid_api_key",
                    message,
                )
                result["failed"] += 1
                result["fatal"] = "invalid_api_key"
                result["error"] = message
                add_detail(
                    symbol,
                    "failed",
                    required_start,
                    required_end,
                    coverage=coverage,
                    error=message,
                )
                fatal_index = work_index + 1
                break
            except CreditExhaustedError as exc:
                message = _safe_error_message(exc, active_client)
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "credit_exhausted",
                    message,
                )
                result["failed"] += 1
                result["fatal"] = "credit_exhausted"
                result["error"] = message
                add_detail(
                    symbol,
                    "failed",
                    required_start,
                    required_end,
                    coverage=coverage,
                    error=message,
                )
                fatal_index = work_index + 1
                break
            except PermanentSymbolError as exc:
                message = _safe_error_message(exc, active_client)
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "permanent_error",
                    message,
                )
                result["failed"] += 1
                add_detail(
                    symbol,
                    "failed",
                    required_start,
                    required_end,
                    coverage=coverage,
                    error=message,
                )
                break

            try:
                update_csv_bars(
                    csv_path, fetched, required_start, required_end
                )
                final_coverage = coverage_status(
                    csv_path, required_start, required_end
                )
            except (OSError, ValueError) as exc:
                message = _safe_error_message(exc, active_client)
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "local_error",
                    message,
                )
                result["failed"] += 1
                result["fatal"] = "local_error"
                result["error"] = message
                add_detail(
                    symbol,
                    "failed",
                    required_start,
                    required_end,
                    coverage=coverage,
                    error=message,
                )
                fatal_index = work_index + 1
                break

            if final_coverage == "complete":
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "updated",
                    None,
                )
                result["complete"] += 1
                result["updated"] += 1
                add_detail(
                    symbol,
                    "updated",
                    required_start,
                    required_end,
                    coverage=final_coverage,
                )
            else:
                message = (
                    "fetched history does not completely cover the required range"
                )
                record_attempt(
                    symbol,
                    attempt,
                    required_start,
                    required_end,
                    "coverage_failure",
                    message,
                )
                result["failed"] += 1
                add_detail(
                    symbol,
                    "failed",
                    required_start,
                    required_end,
                    coverage=final_coverage,
                    error=message,
                )
            break

        if result["fatal"] is not None:
            break

    if fatal_index is not None:
        for (
            row,
            required_start,
            required_end,
            applicable,
        ) in work[fatal_index:]:
            symbol = str(row["symbol"])
            if not applicable:
                result["skipped"] += 1
                add_detail(
                    symbol,
                    "skipped",
                    required_start,
                    required_end,
                    coverage="not_applicable",
                )
                continue
            coverage = coverage_status(
                stocks_path / f"{symbol}.csv",
                required_start,
                required_end,
            )
            if coverage == "complete":
                result["complete"] += 1
                result["skipped"] += 1
                add_detail(
                    symbol,
                    "skipped",
                    required_start,
                    required_end,
                    coverage=coverage,
                )
            else:
                result["remaining"] += 1
                add_detail(
                    symbol,
                    "remaining",
                    required_start,
                    required_end,
                    coverage=coverage,
                    error="run stopped after fatal error",
                )

    return result
