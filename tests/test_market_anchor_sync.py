#!/usr/bin/env python3
import csv
import datetime as dt
import math
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from market_anchor_sync import (
    Bar,
    atomic_write_csv,
    coverage_status,
    merge_bars,
    read_csv_bars,
    required_range_for_symbol,
    update_csv_bars,
)


class MarketAnchorSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = pathlib.Path(self.temporary_directory.name)

    def write_bars(self, name, dates):
        path = self.directory / name
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["DateTime", "Open", "High", "Low", "Close", "Volume"])
            for index, date in enumerate(dates, start=1):
                writer.writerow([date, index, index + 1, index - 0.5, index, 100])
        return path

    def weekday_dates(self, start, end):
        current = dt.date.fromisoformat(start)
        final = dt.date.fromisoformat(end)
        dates = []
        while current <= final:
            if current.weekday() < 5:
                dates.append(current.isoformat())
            current += dt.timedelta(days=1)
        return dates

    def weekday_span(self, start, count):
        current = dt.date.fromisoformat(start)
        dates = []
        while len(dates) < count:
            if current.weekday() < 5:
                dates.append(current.isoformat())
            current += dt.timedelta(days=1)
        return dates

    def test_audit_marks_complete_short_and_missing(self):
        exchange_holidays = {
            "2020-01-01",
            "2020-01-20",
            "2020-02-17",
            "2020-04-10",
            "2020-05-25",
            "2020-07-03",
        }
        complete = self.write_bars(
            "complete.csv",
            [
                date
                for date in self.weekday_dates("2020-01-01", "2020-07-03")
                if date not in exchange_holidays
            ],
        )
        short = self.write_bars("short.csv", ["2020-01-06", "2020-06-30"])

        self.assertEqual(
            coverage_status(complete, "2020-01-01", "2020-07-04"), "complete"
        )
        self.assertEqual(
            coverage_status(short, "2020-01-01", "2020-07-04"), "short"
        )
        self.assertEqual(
            coverage_status(
                self.directory / "missing.csv", "2020-01-01", "2020-07-04"
            ),
            "missing",
        )

    def test_audit_marks_boundary_only_history_short(self):
        boundary_only = self.write_bars(
            "boundary-only.csv", ["2020-01-02", "2020-07-02"]
        )

        self.assertEqual(
            coverage_status(boundary_only, "2020-01-01", "2020-07-04"),
            "short",
        )

    def test_audit_ignores_pre_range_rows_for_start_boundary(self):
        dates = ["2014-12-31"]
        dates.extend(self.weekday_dates("2015-03-16", "2025-12-31"))
        path = self.write_bars("late-in-range-start.csv", dates)

        self.assertEqual(
            coverage_status(path, "2015-01-01", "2025-12-31"),
            "short",
        )

    def test_audit_enforces_95_percent_weekday_density(self):
        dates = self.weekday_span("2020-01-06", 100)
        at_threshold = [
            date
            for index, date in enumerate(dates)
            if index not in {10, 25, 40, 55, 70}
        ]
        below_threshold = [
            date
            for index, date in enumerate(dates)
            if index not in {10, 25, 40, 55, 70, 85}
        ]
        complete = self.write_bars("95-percent.csv", at_threshold)
        short = self.write_bars("94-percent.csv", below_threshold)

        self.assertEqual(
            coverage_status(complete, dates[0], dates[-1]), "complete"
        )
        self.assertEqual(coverage_status(short, dates[0], dates[-1]), "short")

    def test_audit_rejects_long_interior_weekday_gap(self):
        dates = self.weekday_span("2020-01-06", 260)
        with_long_hole = [
            date for index, date in enumerate(dates) if not 100 <= index <= 110
        ]
        path = self.write_bars("long-hole.csv", with_long_hole)

        self.assertEqual(
            coverage_status(path, dates[0], dates[-1]),
            "short",
        )

    def test_later_listing_changes_required_coverage_start(self):
        manifest_row = {
            "history_start": "2020-09-30",
            "eligibility": [{"from": "2023-12-18", "to": None}],
        }

        self.assertEqual(
            required_range_for_symbol(
                manifest_row, "2015-01-01", "2025-12-31"
            ),
            ("2020-09-30", "2025-12-31"),
        )
        self.assertEqual(
            required_range_for_symbol(
                {"history_start": "2010-01-01"}, "2015-01-01", "2025-12-31"
            ),
            ("2015-01-01", "2025-12-31"),
        )

    def test_merge_preserves_rows_outside_requested_range(self):
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

        self.assertEqual(
            [bar.date for bar in merged],
            ["2014-12-31", "2020-01-02", "2020-01-03", "2026-01-02"],
        )

    def test_fetched_rows_win_inside_requested_range(self):
        existing = [
            Bar("2014-12-31", 9, 10, 8, 9.5, 100),
            Bar("2020-01-02", 10, 11, 9, 10.5, 200),
            Bar("2026-01-02", 20, 21, 19, 20.5, 300),
        ]
        fetched = [
            Bar("2020-01-02", 100, 101, 99, 100.5, 999),
            Bar("2020-01-03", 101, 102, 100, 101.5, 998),
            Bar("2026-01-02", 200, 201, 199, 200.5, 997),
        ]

        merged = merge_bars(existing, fetched, "2015-01-01", "2025-12-31")

        self.assertEqual(merged[1].close, 100.5)
        self.assertEqual(merged[-1].close, 20.5)

    def test_invalid_payload_does_not_modify_original(self):
        path = self.write_bars("original.csv", ["2020-01-02"])
        original = path.read_bytes()

        with self.assertRaises(ValueError):
            update_csv_bars(
                path,
                [Bar("2020-01-03", 10, math.nan, 9, 10.5, 200)],
                "2020-01-01",
                "2020-12-31",
            )

        self.assertEqual(path.read_bytes(), original)

    def test_bool_is_rejected_for_each_ohlc_field(self):
        field_names = ("open", "high", "low", "close")
        for field_index, field_name in enumerate(field_names, start=1):
            values = [10, 11, 9, 10.5]
            values[field_index - 1] = True
            with self.subTest(field=field_name):
                with self.assertRaises(ValueError):
                    merge_bars(
                        [],
                        [Bar("2020-01-02", *values, 200)],
                        "2020-01-01",
                        "2020-12-31",
                    )

    def test_invalid_volume_values_are_rejected(self):
        for volume in (True, -1, 1.5, math.inf, math.nan, "not-a-number"):
            with self.subTest(volume=volume):
                with self.assertRaises(ValueError):
                    merge_bars(
                        [],
                        [Bar("2020-01-02", 10, 11, 9, 10.5, volume)],
                        "2020-01-01",
                        "2020-12-31",
                    )

    def test_atomic_write_uses_standard_header_and_sorted_unique_dates(self):
        path = self.directory / "bars.csv"
        bars = [
            Bar("2020-01-03", 11, 12, 10, 11.5, 300),
            Bar("2020-01-02", 9, 10, 8, 9.5, 100),
            Bar("2020-01-02", 10, 11, 9, 10.5, 200),
        ]

        atomic_write_csv(path, bars)

        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(
            rows[0], ["DateTime", "Open", "High", "Low", "Close", "Volume"]
        )
        self.assertEqual([row[0] for row in rows[1:]], ["2020-01-02", "2020-01-03"])
        self.assertEqual(float(rows[1][4]), 10.5)

    def test_atomic_write_replace_failure_preserves_original_and_removes_temp(self):
        path = self.write_bars("original.csv", ["2020-01-02"])
        original = path.read_bytes()

        with mock.patch(
            "market_anchor_sync.os.replace",
            side_effect=OSError("replace unavailable"),
        ):
            with self.assertRaises(OSError):
                atomic_write_csv(
                    path,
                    [Bar("2020-01-03", 11, 12, 10, 11.5, 300)],
                )

        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(set(self.directory.iterdir()), {path})

    def test_reader_accepts_date_header_and_optional_index_column(self):
        path = self.directory / "indexed.csv"
        path.write_text(
            ",Date,Open,High,Low,Close,Volume\n"
            "7,2020-01-03,11,12,10,11.5,300\n"
            "8,2020-01-02,10,11,9,10.5,200\n"
            "9,2020-01-02,100,101,99,100.5,999\n",
            encoding="utf-8",
        )

        bars = read_csv_bars(path)

        self.assertEqual([bar.date for bar in bars], ["2020-01-02", "2020-01-03"])
        self.assertEqual(bars[0].close, 100.5)

    def test_reader_rejects_malformed_or_unsafe_bars(self):
        malformed = self.directory / "malformed.csv"
        malformed.write_text(
            "DateTime,Open,High,Low,Close,Volume\n"
            "2020-01-02,10,not-a-number,9,10.5,200\n",
            encoding="utf-8",
        )
        non_positive = self.directory / "non-positive.csv"
        non_positive.write_text(
            "DateTime,Open,High,Low,Close,Volume\n"
            "2020-01-02,10,11,9,0,200\n",
            encoding="utf-8",
        )

        with self.assertRaises(ValueError):
            read_csv_bars(malformed)
        with self.assertRaises(ValueError):
            read_csv_bars(non_positive)


if __name__ == "__main__":
    unittest.main()
