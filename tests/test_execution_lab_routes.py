"""Essential Flask integration smoke checks, using the real isolated worker."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from Big_movers_server import app
from execution_lab import routes


class ExecutionLabRoutesTests(unittest.TestCase):
    def setUp(self):
        self.client=app.test_client()

    def test_page_assets_and_launch_link(self):
        for path in ("/execution-lab/","/execution-lab/assets/lab.js",
                     "/execution-lab/assets/lab.css","/vendor/lightweight-charts.standalone.production.js"):
            response=self.client.get(path)
            self.assertEqual(response.status_code,200,path)
            response.close()
        response=self.client.get("/")
        self.assertIn(b'href="/execution-lab/"',response.data)
        response.close()

    def test_mutation_header_loopback_and_origin_protection(self):
        body={"action":"create","command_id":"unauthorized"}
        self.assertEqual(self.client.post("/execution-lab/api/command",json=body).status_code,403)
        self.assertEqual(self.client.post("/execution-lab/api/command",json=body,
                                         headers={"X-Execution-Lab":"1"},
                                         environ_base={"REMOTE_ADDR":"192.0.2.10"}).status_code,403)
        self.assertEqual(self.client.post("/execution-lab/api/command",json=body,
                                         headers={"X-Execution-Lab":"1","Origin":"http://unrelated.example"}).status_code,403)

    def test_real_worker_create_advance_and_reconnect(self):
        manager=routes.WorkerManager()
        with tempfile.TemporaryDirectory() as directory, patch.object(routes,"DATA",Path(directory)), patch.object(routes,"manager",manager):
            try:
                headers={"X-Execution-Lab":"1"}
                response=self.client.post("/execution-lab/api/command",headers=headers,
                    json={"action":"create","command_id":"flask-create","seed":17,"date":"2026-10-02"})
                self.assertEqual(response.status_code,200,response.get_json())
                state=response.get_json()["state"]
                self.assertTrue(state["bars"])
                response=self.client.post("/execution-lab/api/command",headers=headers,
                    json={"action":"advance","command_id":"flask-advance","session_id":state["session_id"],"seconds":1})
                self.assertEqual(response.status_code,200,response.get_json())
                advanced=response.get_json()["state"]
                self.assertEqual(advanced["time"],state["time"]+1)
                snapshot=self.client.get("/execution-lab/api/state").get_json()
                self.assertEqual(snapshot["state"]["revision"],advanced["revision"])
                self.assertFalse(snapshot["worker_failed"])
            finally:
                manager.close()
                if manager.process:
                    manager.process.wait(timeout=5)
                    manager.process.stdin.close()
                    manager.process.stdout.close()


if __name__ == "__main__":
    unittest.main()
