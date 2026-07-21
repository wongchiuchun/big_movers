#!/usr/bin/env python3
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from Big_movers_server import app


class ShutdownEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.scheduled = []
        app.config["SHUTDOWN_SCHEDULER"] = lambda: self.scheduled.append(True)

    def tearDown(self):
        app.config.pop("SHUTDOWN_SCHEDULER", None)

    def test_local_ui_request_schedules_shutdown(self):
        response = self.client.post(
            "/api/shutdown",
            headers={"X-Big-Movers-UI": "1"},
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True})
        self.assertEqual(self.scheduled, [True])

    def test_missing_ui_header_is_rejected(self):
        response = self.client.post(
            "/api/shutdown",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.scheduled, [])

    def test_non_loopback_request_is_rejected(self):
        response = self.client.post(
            "/api/shutdown",
            headers={"X-Big-Movers-UI": "1"},
            environ_base={"REMOTE_ADDR": "192.0.2.10"},
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.scheduled, [])


if __name__ == "__main__":
    unittest.main()
