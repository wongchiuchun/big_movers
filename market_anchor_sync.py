"""Merge-safe CSV storage primitives for historical market-anchor bars."""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import math
import os
import pathlib
import tempfile
from collections.abc import Iterable, Mapping


MIN_DAILY_BAR_DENSITY = 0.95
MAX_MISSING_WEEKDAY_GAP = 10


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
            writer = csv.writer(handle)
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
