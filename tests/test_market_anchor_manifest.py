#!/usr/bin/env python3
import datetime as dt
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "market_anchor_universe.json"

sys.path.insert(0, str(PROJECT_ROOT))

import Big_movers_server

app = Big_movers_server.app


EXPECTED_SYMBOLS = {
    "growth": {
        "AAPL",
        "ADBE",
        "AMAT",
        "AMD",
        "AMZN",
        "AVGO",
        "BKNG",
        "COST",
        "CSCO",
        "GOOG",
        "GOOGL",
        "INTC",
        "INTU",
        "ISRG",
        "META",
        "MSFT",
        "MU",
        "NFLX",
        "NVDA",
        "PANW",
        "PEP",
        "PLTR",
        "QCOM",
        "TSLA",
        "TXN",
    },
    "broad": {
        "ABBV",
        "BA",
        "BAC",
        "CAT",
        "CRM",
        "CVX",
        "DIS",
        "GE",
        "GS",
        "HD",
        "IBM",
        "JNJ",
        "JPM",
        "KO",
        "LLY",
        "MA",
        "MCD",
        "MRK",
        "NKE",
        "ORCL",
        "PG",
        "UNH",
        "V",
        "WMT",
        "XOM",
    },
}


def parse_date(value):
    return dt.date.fromisoformat(value)


class MarketAnchorManifestTests(unittest.TestCase):
    def load_manifest(self):
        self.assertTrue(MANIFEST_PATH.is_file(), "market anchor manifest is missing")
        with MANIFEST_PATH.open(encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    def test_manifest_has_exact_reviewed_universe(self):
        manifest = self.load_manifest()
        rows = manifest["symbols"]

        self.assertEqual(manifest["version"], 1)
        self.assertEqual(len(rows), 50)
        symbols = [row["symbol"] for row in rows]
        self.assertEqual(len(symbols), len(set(symbols)))
        self.assertEqual(
            [row["group"] for row in rows],
            ["growth"] * len(EXPECTED_SYMBOLS["growth"])
            + ["broad"] * len(EXPECTED_SYMBOLS["broad"]),
        )
        for group, expected in EXPECTED_SYMBOLS.items():
            actual = [row["symbol"] for row in rows if row["group"] == group]
            self.assertEqual(set(actual), expected)
            self.assertEqual(actual, sorted(actual))

    def test_manifest_has_expected_data_bounds(self):
        manifest = self.load_manifest()

        self.assertEqual(manifest["data_start"], "2015-01-01")
        self.assertEqual(manifest["data_end"], "2025-12-31")

    def test_symbol_metadata_is_complete_and_within_global_history(self):
        manifest = self.load_manifest()
        data_start = parse_date(manifest["data_start"])
        data_end = parse_date(manifest["data_end"])

        for row in manifest["symbols"]:
            with self.subTest(symbol=row["symbol"]):
                self.assertIn(row["group"], {"growth", "broad"})
                self.assertTrue(row["sector"].strip())
                self.assertTrue(row["history_start"])
                history_start = parse_date(row["history_start"])
                self.assertGreaterEqual(history_start, data_start)
                self.assertLessEqual(history_start, data_end)

    def test_eligibility_intervals_are_complete_ordered_and_disjoint(self):
        manifest = self.load_manifest()
        data_end = parse_date(manifest["data_end"])

        for row in manifest["symbols"]:
            with self.subTest(symbol=row["symbol"]):
                intervals = row["eligibility"]
                history_start = parse_date(row["history_start"])
                self.assertTrue(intervals)
                previous_to = None
                open_ended_count = 0

                for index, interval in enumerate(intervals):
                    self.assertTrue(interval["from"])
                    self.assertTrue(interval["basis"].strip())
                    interval_from = parse_date(interval["from"])
                    self.assertGreaterEqual(interval_from, history_start)
                    self.assertLessEqual(interval_from, data_end)
                    interval_to_value = interval.get("to")
                    if interval_to_value is None:
                        open_ended_count += 1
                        self.assertEqual(index, len(intervals) - 1)
                        interval_to = None
                    else:
                        interval_to = parse_date(interval_to_value)
                        self.assertLessEqual(interval_from, interval_to)
                        self.assertLessEqual(interval_to, data_end)

                    if previous_to is not None:
                        self.assertGreater(interval_from, previous_to)
                    previous_to = interval_to

                self.assertLessEqual(open_ended_count, 1)

    def test_market_anchors_endpoint_serves_manifest(self):
        manifest = self.load_manifest()
        response = app.test_client().get("/api/market-anchors")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), manifest)

    def test_market_anchors_endpoint_reports_missing_manifest(self):
        missing_path = str(PROJECT_ROOT / "missing-market-anchor-manifest.json")
        with mock.patch.object(
            Big_movers_server, "MARKET_ANCHORS_FILE", missing_path, create=True
        ):
            response = app.test_client().get("/api/market-anchors")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json(), {"error": "market anchor manifest not found"}
        )

    def test_market_anchors_endpoint_reports_invalid_manifest(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as invalid_file:
            invalid_file.write("{not valid json")
            invalid_file.flush()
            with mock.patch.object(
                Big_movers_server,
                "MARKET_ANCHORS_FILE",
                invalid_file.name,
                create=True,
            ):
                response = app.test_client().get("/api/market-anchors")

        self.assertEqual(response.status_code, 500)
        self.assertTrue(
            response.get_json()["error"].startswith(
                "market anchor manifest invalid:"
            )
        )

    def test_market_anchors_endpoint_reports_manifest_read_error(self):
        with mock.patch.object(
            Big_movers_server,
            "open",
            side_effect=OSError("manifest storage unavailable"),
            create=True,
        ):
            response = app.test_client().get("/api/market-anchors")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.get_json(),
            {
                "error": (
                    "market anchor manifest invalid: manifest storage unavailable"
                )
            },
        )


if __name__ == "__main__":
    unittest.main()
