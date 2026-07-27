#!/usr/bin/env python3
import csv
import contextlib
import datetime as dt
import email.message
import http.client
import io
import json
import math
import pathlib
import subprocess
import sys
import tempfile
import traceback
import types
import unittest
import urllib.error
import urllib.parse
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import market_anchor_sync as sync
from tools import sync_market_anchors as sync_cli
from market_anchor_sync import (
    Bar,
    atomic_write_csv,
    coverage_status,
    merge_bars,
    read_csv_bars,
    required_range_for_symbol,
    update_csv_bars,
)


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ReadErrorResponse(FakeResponse):
    def __init__(self, error):
        self.error = error

    def read(self):
        raise self.error

    def close(self):
        pass


class RawResponse(FakeResponse):
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body


class FakeSSLContext:
    def __init__(self):
        self.check_hostname = True
        self.verify_mode = sync.ssl.CERT_REQUIRED
        self.loaded_locations = []

    def load_verify_locations(self, path):
        self.loaded_locations.append(path)


class ScriptedOpener:
    def __init__(self, clock, outcomes):
        self.clock = clock
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, request, **kwargs):
        self.calls.append((self.clock.monotonic(), request, kwargs))
        outcome = self.outcomes.pop(0)
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, FakeResponse):
            return outcome
        return FakeResponse(outcome)


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

    def write_manifest(self, symbols=("AAA",), start="2020-01-02", end="2020-01-03"):
        path = self.directory / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "data_start": start,
                    "data_end": end,
                    "symbols": [
                        {
                            "symbol": symbol,
                            "history_start": start,
                            "eligibility": [],
                        }
                        for symbol in symbols
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    def values_payload(self, start="2020-01-02", end="2020-01-03"):
        return {
            "status": "ok",
            "values": [
                {
                    "datetime": end,
                    "open": "11",
                    "high": "12",
                    "low": "10",
                    "close": "11.5",
                    "volume": "300",
                },
                {
                    "datetime": start,
                    "open": "10",
                    "high": "11",
                    "low": "9",
                    "close": "10.5",
                    "volume": "200",
                },
            ],
        }

    def http_error(self, status, payload=None, retry_after=None):
        headers = email.message.Message()
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        body = (
            io.BytesIO(json.dumps(payload).encode("utf-8"))
            if payload is not None
            else None
        )
        return urllib.error.HTTPError(
            "https://api.twelvedata.com/time_series",
            status,
            "fake error",
            headers,
            body,
        )

    def http_error_with_read_error(self, status, error, retry_after=None):
        headers = email.message.Message()
        if retry_after is not None:
            headers["Retry-After"] = str(retry_after)
        return urllib.error.HTTPError(
            "https://api.twelvedata.com/time_series",
            status,
            "fake error",
            headers,
            ReadErrorResponse(error),
        )

    def run_sync(
        self,
        opener,
        clock,
        *,
        symbols=("AAA",),
        max_requests=50,
        state_contents=None,
    ):
        manifest = self.write_manifest(symbols)
        stocks = self.directory / "stocks"
        state = self.directory / ".market_anchor_sync_state.json"
        if state_contents is not None:
            state.write_text(json.dumps(state_contents), encoding="utf-8")
        result = sync.synchronize(
            manifest,
            stocks,
            state,
            client=sync.TwelveDataClient("fake-key", opener=opener),
            max_requests=max_requests,
            min_interval=9,
            sleep=clock.sleep,
            clock=clock.monotonic,
        )
        return result, stocks, state

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

    def test_atomic_write_uses_lf_only_with_standard_header_and_order(self):
        path = self.directory / "bars.csv"
        bars = [
            Bar("2020-01-03", 11, 12, 10, 11.5, 300),
            Bar("2020-01-02", 9, 10, 8, 9.5, 100),
        ]

        atomic_write_csv(path, bars)

        contents = path.read_bytes()
        self.assertNotIn(b"\r\n", contents)
        self.assertEqual(
            contents,
            (
                b"DateTime,Open,High,Low,Close,Volume\n"
                b"2020-01-02,9.0,10.0,8.0,9.5,100\n"
                b"2020-01-03,11.0,12.0,10.0,11.5,300\n"
            ),
        )

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

    def test_load_api_key_matches_server_env_search_order(self):
        parent_env = self.directory / ".env"
        project = self.directory / "project"
        project.mkdir()
        parent_env.write_text("TWELVE_API_KEY=parent-key\n", encoding="utf-8")

        self.assertEqual(sync.load_api_key(project), "parent-key")

        (project / ".env").write_text(
            "IGNORED=value\nTWELVE_API_KEY=project-key\n", encoding="utf-8"
        )
        self.assertEqual(sync.load_api_key(project), "project-key")

    def test_parse_twelve_values_normalizes_reverse_results(self):
        bars = sync.parse_twelve_values(self.values_payload())

        self.assertEqual([bar.date for bar in bars], ["2020-01-02", "2020-01-03"])
        self.assertEqual(bars[0].volume, 200)

    def test_parse_twelve_values_detects_provider_error_before_values(self):
        payload = self.values_payload()
        payload.update(
            {
                "status": "error",
                "code": 401,
                "message": "The apikey parameter is incorrect.",
            }
        )

        with self.assertRaises(sync.InvalidAPIKeyError):
            sync.parse_twelve_values(payload)

    def test_parse_twelve_values_detects_error_code_without_status_field(self):
        payload = self.values_payload()
        payload.update(
            {
                "code": 401,
                "message": "The apikey parameter is incorrect.",
            }
        )
        payload.pop("status")

        with self.assertRaises(sync.InvalidAPIKeyError):
            sync.parse_twelve_values(payload)

    def test_parse_twelve_values_rejects_incomplete_payload(self):
        payload = self.values_payload()
        del payload["values"][0]["volume"]

        with self.assertRaises(sync.PermanentSymbolError):
            sync.parse_twelve_values(payload)

    def test_client_uses_raw_daily_query_and_header_authentication(self):
        clock = FakeClock()
        opener = ScriptedOpener(clock, [self.values_payload()])
        supplied_context = object()
        client = sync.TwelveDataClient(
            "fake-key", opener=opener, ssl_context=supplied_context
        )

        client.fetch_daily("AAA", "2020-01-02", "2020-01-03")

        request = opener.calls[0][1]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.assertEqual(
            query,
            {
                "symbol": ["AAA"],
                "interval": ["1day"],
                "start_date": ["2020-01-02"],
                "end_date": ["2020-01-03"],
                "outputsize": ["5000"],
            },
        )
        self.assertNotIn("fake-key", request.full_url)
        self.assertEqual(
            request.get_header("Authorization"), "apikey fake-key"
        )
        self.assertEqual(opener.calls[0][2]["timeout"], 30)
        self.assertIs(opener.calls[0][2]["context"], supplied_context)

    def test_default_ssl_context_loads_certifi_when_available(self):
        context = FakeSSLContext()
        certifi = types.SimpleNamespace(
            where=mock.Mock(return_value="/fake/cacert.pem")
        )

        with mock.patch.object(
            sync.ssl, "create_default_context", return_value=context
        ), mock.patch.dict(sys.modules, {"certifi": certifi}):
            client = sync.TwelveDataClient("fake-key", opener=lambda *args: None)

        self.assertIs(client.ssl_context, context)
        self.assertEqual(context.loaded_locations, ["/fake/cacert.pem"])
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, sync.ssl.CERT_REQUIRED)

    def test_default_ssl_context_matches_server_fallback_without_certifi(self):
        context = FakeSSLContext()

        with mock.patch.object(
            sync.ssl, "create_default_context", return_value=context
        ), mock.patch.dict(sys.modules, {"certifi": None}):
            client = sync.TwelveDataClient("fake-key", opener=lambda *args: None)

        self.assertIs(client.ssl_context, context)
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, sync.ssl.CERT_NONE)

    def test_dry_run_never_calls_opener_or_writes(self):
        manifest = self.write_manifest(("AAA", "BBB"))
        stocks = self.directory / "stocks"
        state = self.directory / ".market_anchor_sync_state.json"
        clock = FakeClock()

        def forbidden_opener(*args, **kwargs):
            self.fail("dry-run opened the network")

        result = sync.synchronize(
            manifest,
            stocks,
            state,
            dry_run=True,
            client=sync.TwelveDataClient("fake-key", opener=forbidden_opener),
            sleep=clock.sleep,
            clock=clock.monotonic,
        )

        self.assertEqual(result["requests"], 0)
        self.assertEqual(result["remaining"], 2)
        self.assertEqual(clock.sleeps, [])
        self.assertFalse(stocks.exists())
        self.assertFalse(state.exists())

    def test_complete_symbol_consumes_no_request(self):
        manifest = self.write_manifest()
        stocks = self.directory / "stocks"
        stocks.mkdir()
        self.write_bars("complete-source.csv", ["2020-01-02", "2020-01-03"]).replace(
            stocks / "AAA.csv"
        )
        state = self.directory / ".market_anchor_sync_state.json"
        clock = FakeClock()
        opener = ScriptedOpener(clock, [])

        result = sync.synchronize(
            manifest,
            stocks,
            state,
            client=sync.TwelveDataClient("fake-key", opener=opener),
            sleep=clock.sleep,
            clock=clock.monotonic,
        )

        self.assertEqual(result["requests"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["complete"], 1)
        self.assertEqual(opener.calls, [])
        self.assertFalse(state.exists())

    def test_attempts_are_at_least_nine_seconds_apart(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock, [self.values_payload(), self.values_payload()]
        )

        result, _, _ = self.run_sync(opener, clock, symbols=("AAA", "BBB"))

        self.assertEqual(result["updated"], 2)
        self.assertEqual(result["requests"], 2)
        self.assertGreaterEqual(opener.calls[1][0] - opener.calls[0][0], 9)

    def test_http_429_honors_retry_after(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error(429, retry_after=25),
                self.values_payload(),
            ],
        )

        result, _, _ = self.run_sync(opener, clock)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(clock.sleeps, [25])

    def test_http_429_retry_after_starts_when_response_arrives(self):
        clock = FakeClock()

        def delayed_rate_limit():
            clock.now += 5
            return self.http_error(429, retry_after=25)

        opener = ScriptedOpener(
            clock,
            [
                delayed_rate_limit,
                self.values_payload(),
            ],
        )

        result, _, _ = self.run_sync(opener, clock)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(clock.sleeps, [25])

    def test_http_429_without_retry_after_defaults_to_sixty_seconds(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error(429),
                self.values_payload(),
            ],
        )

        result, _, _ = self.run_sync(opener, clock)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(clock.sleeps, [60])

    def test_terminal_http_429_deadline_applies_to_next_symbol(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error(429, retry_after=25),
                self.http_error(429, retry_after=25),
                self.http_error(429, retry_after=25),
                self.values_payload(),
            ],
        )

        result, _, _ = self.run_sync(opener, clock, symbols=("AAA", "BBB"))

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 4)
        self.assertGreaterEqual(opener.calls[3][0] - opener.calls[2][0], 25)

    def test_truncated_http_429_preserves_rate_limit_timing_and_state(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error_with_read_error(
                    429,
                    http.client.IncompleteRead(b"partial", 100),
                    retry_after=25,
                )
                for _ in range(3)
            ]
            + [self.values_payload()],
        )

        result, _, state = self.run_sync(
            opener, clock, symbols=("AAA", "BBB")
        )

        attempts = json.loads(state.read_text(encoding="utf-8"))["attempts"]
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 4)
        self.assertEqual(
            [attempt["result"] for attempt in attempts],
            ["rate_limited", "rate_limited", "rate_limited", "updated"],
        )
        self.assertTrue(
            all(
                later[0] - earlier[0] >= 25
                for earlier, later in zip(opener.calls, opener.calls[1:])
            )
        )

    def test_transient_network_and_5xx_retries_only_three_total_attempts(self):
        for outcomes in (
            [
                urllib.error.URLError("temporary"),
                urllib.error.URLError("temporary"),
                urllib.error.URLError("temporary"),
            ],
            [
                self.http_error(503),
                self.http_error(503),
                self.http_error(503),
            ],
        ):
            with self.subTest(kind=type(outcomes[0]).__name__):
                (self.directory / ".market_anchor_sync_state.json").unlink(
                    missing_ok=True
                )
                clock = FakeClock()
                opener = ScriptedOpener(clock, outcomes)

                result, _, state = self.run_sync(opener, clock)

                self.assertEqual(result["failed"], 1)
                self.assertEqual(result["requests"], 3)
                self.assertEqual(len(opener.calls), 3)
                self.assertEqual(
                    len(json.loads(state.read_text(encoding="utf-8"))["attempts"]),
                    3,
                )

    def test_incomplete_read_retries_and_records_attempt(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                ReadErrorResponse(http.client.IncompleteRead(b"partial", 100)),
                self.values_payload(),
            ],
        )

        try:
            result, _, state = self.run_sync(opener, clock)
        except Exception as exc:
            self.fail(f"IncompleteRead escaped instead of retrying: {exc!r}")

        attempts = json.loads(state.read_text(encoding="utf-8"))["attempts"]
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(
            [attempt["result"] for attempt in attempts],
            ["transient_error", "updated"],
        )

    def test_invalid_json_200_response_retries_and_records_attempt(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                RawResponse(b'{"status": "ok", "values": ['),
                self.values_payload(),
            ],
        )

        result, _, state = self.run_sync(opener, clock)

        attempts = json.loads(state.read_text(encoding="utf-8"))["attempts"]
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(
            [attempt["result"] for attempt in attempts],
            ["transient_error", "updated"],
        )

    def test_incomplete_http_error_body_is_a_transient_network_error(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error_with_read_error(
                    503, http.client.IncompleteRead(b"partial", 100)
                )
            ],
        )
        client = sync.TwelveDataClient("fake-key", opener=opener)

        try:
            client.fetch_daily("AAA", "2020-01-02", "2020-01-03")
        except Exception as exc:
            observed = exc
        else:
            self.fail("truncated HTTP error body did not raise")

        self.assertIsInstance(observed, sync.TransientNetworkError)

    def test_incomplete_http_error_body_retries_and_records_attempt(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error_with_read_error(
                    503, http.client.IncompleteRead(b"partial", 100)
                ),
                self.values_payload(),
            ],
        )

        try:
            result, _, state = self.run_sync(opener, clock)
        except Exception as exc:
            self.fail(f"truncated HTTP error body escaped: {exc!r}")

        attempts = json.loads(state.read_text(encoding="utf-8"))["attempts"]
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(
            [attempt["result"] for attempt in attempts],
            ["transient_error", "updated"],
        )
        self.assertIn("network", attempts[0]["error"].lower())

    def test_transient_retry_waits_increase(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error(503),
                self.http_error(503),
                self.values_payload(),
            ],
        )

        result, _, _ = self.run_sync(opener, clock)

        self.assertEqual(result["updated"], 1)
        self.assertEqual(clock.sleeps, [9, 18])

    def test_invalid_api_key_stops_entire_run(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                {
                    "status": "error",
                    "code": 401,
                    "message": "The apikey parameter is incorrect.",
                }
            ],
        )

        result, _, state = self.run_sync(opener, clock, symbols=("AAA", "BBB"))

        self.assertEqual(result["fatal"], "invalid_api_key")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(result["requests"], 1)
        self.assertEqual(len(opener.calls), 1)
        self.assertNotIn("fake-key", state.read_text(encoding="utf-8"))

    def test_fatal_tail_reaudits_complete_symbols_exactly_once(self):
        manifest = self.write_manifest(("AAA", "BBB"))
        stocks = self.directory / "stocks"
        stocks.mkdir()
        self.write_bars(
            "complete-tail.csv", ["2020-01-02", "2020-01-03"]
        ).replace(stocks / "BBB.csv")
        state = self.directory / ".market_anchor_sync_state.json"
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                {
                    "status": "error",
                    "code": 401,
                    "message": "The apikey parameter is incorrect.",
                }
            ],
        )

        result = sync.synchronize(
            manifest,
            stocks,
            state,
            client=sync.TwelveDataClient("fake-key", opener=opener),
            sleep=clock.sleep,
            clock=clock.monotonic,
        )

        details_by_symbol = {
            detail["symbol"]: detail for detail in result["details"]
        }
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["complete"], 1)
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(len(result["details"]), 2)
        self.assertEqual(len(details_by_symbol), 2)
        self.assertEqual(details_by_symbol["AAA"]["status"], "failed")
        self.assertEqual(details_by_symbol["BBB"]["status"], "skipped")
        self.assertEqual(details_by_symbol["BBB"]["coverage"], "complete")

    def test_truncated_http_auth_error_is_fatal_and_recorded(self):
        for status in (401, 403):
            with self.subTest(status=status):
                (self.directory / ".market_anchor_sync_state.json").unlink(
                    missing_ok=True
                )
                clock = FakeClock()
                opener = ScriptedOpener(
                    clock,
                    [
                        self.http_error_with_read_error(
                            status,
                            http.client.IncompleteRead(b"partial", 100),
                        )
                        for _ in range(3)
                    ]
                    + [self.values_payload()],
                )

                result, _, state = self.run_sync(
                    opener, clock, symbols=("AAA", "BBB")
                )

                attempts = json.loads(
                    state.read_text(encoding="utf-8")
                )["attempts"]
                self.assertEqual(result["fatal"], "invalid_api_key")
                self.assertEqual(result["failed"], 1)
                self.assertEqual(result["remaining"], 1)
                self.assertEqual(result["requests"], 1)
                self.assertEqual(
                    [attempt["result"] for attempt in attempts],
                    ["invalid_api_key"],
                )

    def test_client_redacts_api_key_from_provider_errors(self):
        secret = "secret-provider-key"
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                {
                    "status": "error",
                    "code": 400,
                    "message": f"Bad request containing {secret}",
                }
            ],
        )
        client = sync.TwelveDataClient(secret, opener=opener)

        with self.assertRaises(sync.PermanentSymbolError) as captured:
            client.fetch_daily("AAA", "2020-01-02", "2020-01-03")

        self.assertNotIn(secret, str(captured.exception))

    def test_malformed_value_cannot_leak_key_through_exception_chain(self):
        secret = "secret-numeric-key"
        payload = self.values_payload()
        payload["values"][0]["open"] = secret
        clock = FakeClock()
        client = sync.TwelveDataClient(
            secret, opener=ScriptedOpener(clock, [payload])
        )

        with self.assertRaises(sync.PermanentSymbolError) as captured:
            client.fetch_daily("AAA", "2020-01-02", "2020-01-03")

        error = captured.exception
        rendered = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        inspected = [
            str(error),
            repr(error),
            repr(error.__cause__),
            repr(error.__context__),
            rendered,
        ]
        for representation in inspected:
            self.assertNotIn(secret, representation)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def test_state_result_and_cli_output_do_not_contain_api_key(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                {
                    "status": "error",
                    "code": 400,
                    "message": "Bad request containing fake-key",
                }
            ],
        )

        result, _, state = self.run_sync(opener, clock)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sync_cli._print_result(result)

        serialized = (
            json.dumps(result)
            + state.read_text(encoding="utf-8")
            + output.getvalue()
        )
        self.assertNotIn("fake-key", serialized)

    def test_credit_exhaustion_stops_entire_run(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                {
                    "status": "error",
                    "code": 429,
                    "message": "You have run out of API credits for this minute.",
                }
            ],
        )

        result, _, _ = self.run_sync(opener, clock, symbols=("AAA", "BBB"))

        self.assertEqual(result["fatal"], "credit_exhausted")
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(result["requests"], 1)
        self.assertEqual(len(opener.calls), 1)

    def test_permanent_symbol_error_continues_to_next_symbol(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                {
                    "status": "error",
                    "code": 400,
                    "message": "Unknown symbol AAA",
                },
                self.values_payload(),
            ],
        )

        result, _, _ = self.run_sync(opener, clock, symbols=("AAA", "BBB"))

        self.assertIsNone(result["fatal"])
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(len(opener.calls), 2)

    def test_resume_reaudits_disk_instead_of_trusting_state(self):
        clock = FakeClock()
        opener = ScriptedOpener(clock, [self.values_payload()])
        stale_state = {
            "version": 1,
            "symbols": {
                "AAA": {
                    "result": "updated",
                    "range": {"start": "2020-01-02", "end": "2020-01-03"},
                }
            },
        }

        result, stocks, _ = self.run_sync(
            opener, clock, state_contents=stale_state
        )

        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["requests"], 1)
        self.assertTrue((stocks / "AAA.csv").is_file())

    def test_max_requests_counts_every_attempt_including_retries(self):
        clock = FakeClock()
        opener = ScriptedOpener(
            clock,
            [
                self.http_error(503),
                self.values_payload(),
                self.values_payload(),
            ],
        )

        result, stocks, _ = self.run_sync(
            opener, clock, symbols=("AAA", "BBB"), max_requests=2
        )

        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(len(opener.calls), 2)
        self.assertFalse((stocks / "BBB.csv").exists())

    def test_symbol_history_start_and_overrides_define_requested_range(self):
        manifest = self.write_manifest(start="2020-01-01", end="2020-01-03")
        payload = self.values_payload()
        clock = FakeClock()
        opener = ScriptedOpener(clock, [payload])
        state = self.directory / "state.json"

        sync.synchronize(
            manifest,
            self.directory / "stocks",
            state,
            start="2019-01-01",
            client=sync.TwelveDataClient("fake-key", opener=opener),
            sleep=clock.sleep,
            clock=clock.monotonic,
        )

        query = urllib.parse.parse_qs(
            urllib.parse.urlsplit(opener.calls[0][1].full_url).query
        )
        self.assertEqual(query["start_date"], ["2020-01-01"])
        self.assertEqual(query["end_date"], ["2020-01-03"])

    def test_end_before_history_start_is_skipped_as_not_applicable(self):
        manifest = self.directory / "manifest.json"
        manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "data_start": "2020-01-02",
                    "data_end": "2020-12-31",
                    "symbols": [
                        {
                            "symbol": "OLD",
                            "history_start": "2020-01-02",
                            "eligibility": [],
                        },
                        {
                            "symbol": "PLTR",
                            "history_start": "2020-09-30",
                            "eligibility": [],
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        try:
            result = sync.synchronize(
                manifest,
                self.directory / "stocks",
                self.directory / "state.json",
                dry_run=True,
                end="2020-06-30",
            )
        except ValueError as exc:
            self.fail(f"later history_start aborted the manifest: {exc}")

        details = {detail["symbol"]: detail for detail in result["details"]}
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["complete"], 0)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(result["requests"], 0)
        self.assertEqual(details["OLD"]["status"], "remaining")
        self.assertEqual(details["PLTR"]["status"], "skipped")
        self.assertEqual(details["PLTR"]["coverage"], "not_applicable")

    def test_synchronize_rejects_invalid_limits_and_ranges(self):
        manifest = self.write_manifest()
        state = self.directory / "state.json"
        invalid_options = (
            {"min_interval": 8.99},
            {"max_requests": 0},
            {"max_requests": True},
            {"start": "2020-01-04", "end": "2020-01-03"},
        )

        for options in invalid_options:
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    sync.synchronize(
                        manifest,
                        self.directory / "stocks",
                        state,
                        dry_run=True,
                        **options,
                    )

    def test_cli_rejects_min_interval_below_nine(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "sync_market_anchors.py"),
                "--dry-run",
                "--min-interval",
                "8",
            ],
            cwd=self.directory,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertIn("at least 9", completed.stderr)

    def test_cli_dry_run_succeeds_from_arbitrary_working_directory(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(PROJECT_ROOT / "tools" / "sync_market_anchors.py"),
                "--dry-run",
                "--symbol",
                "AAPL",
            ],
            cwd=self.directory,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("COMPLETE", completed.stdout)
        self.assertIn("complete=1", completed.stdout)


if __name__ == "__main__":
    unittest.main()
