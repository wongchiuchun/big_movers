"""Flask integration; no simulator dependencies imported by the study server."""
import atexit
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import threading
from urllib.parse import urlparse
from flask import Blueprint, jsonify, request, send_from_directory

LAB = Path(__file__).resolve().parent
DATA = LAB / "data"
blueprint = Blueprint("execution_lab", __name__, url_prefix="/execution-lab")


class WorkerManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.snapshot = None
        self.log = None
        self.failed = False
        atexit.register(self.close)

    def close(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
        if self.log:
            self.log.close()

    def start(self):
        if self.failed:
            raise RuntimeError("Simulation worker failed. Restart the big_movers server.")
        if self.process:
            if self.process.poll() is not None:
                self.failed = True
                raise RuntimeError("Simulation worker exited. Restart the big_movers server.")
            return
        python = Path(os.environ.get("EXECUTION_LAB_PYTHON", str(LAB/".venv/bin/python")))
        if not python.is_file():
            raise RuntimeError("Execution Lab needs its isolated environment. Run: bash big_movers/execution_lab/setup.sh")
        DATA.mkdir(parents=True,exist_ok=True)
        self.log = (DATA/"worker.log").open("a",encoding="utf-8")
        try:
            self.process = subprocess.Popen([str(python),"-u",str(LAB/"worker.py")],
                                            stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                            stderr=self.log,text=True,bufsize=1,cwd=str(LAB))
        except OSError as exc:
            self.log.close()
            self.log = None
            raise RuntimeError(f"Could not launch Execution Lab worker: {exc}") from None

    def call(self, body):
        with self.lock:
            self.start()
            try:
                self.process.stdin.write(json.dumps(body,allow_nan=False)+"\n")
                self.process.stdin.flush()
                with selectors.DefaultSelector() as selector:
                    selector.register(self.process.stdout,selectors.EVENT_READ)
                    if not selector.select(timeout=45):
                        raise RuntimeError("Simulation timed out; session stopped. Restart server.")
                    line = self.process.stdout.readline()
                if not line:
                    raise RuntimeError("Simulation worker stopped; see execution_lab/data/worker.log.")
                response = json.loads(line)
                if response.get("command_id") != body.get("command_id"):
                    raise RuntimeError("Worker response did not match this command.")
                if response.get("ok"):
                    self.snapshot = response["state"]
                if response.get("fatal"):
                    self.failed = True
                return response
            except (OSError,ValueError,RuntimeError) as exc:
                self.failed = True
                if self.process.poll() is None:
                    self.process.terminate()
                raise RuntimeError(str(exc)) from None


manager = WorkerManager()


@blueprint.get("/")
def index():
    return send_from_directory(LAB,"index.html")


@blueprint.get("/assets/<name>")
def asset(name):
    if name not in {"lab.js","lab.css"}:
        return jsonify(error="Unknown asset"),404
    return send_from_directory(LAB,name)


@blueprint.get("/api/state")
def state():
    with manager.lock:
        if manager.process and manager.process.poll() is not None:
            manager.failed = True
        return jsonify(state=manager.snapshot,worker_failed=manager.failed)


@blueprint.post("/api/command")
def command():
    if request.remote_addr not in {"127.0.0.1","::1"} or request.headers.get("X-Execution-Lab") != "1":
        return jsonify(error="Local Execution Lab requests only."),403
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc != request.host:
        return jsonify(error="Origin does not match this local app."),403
    if request.content_length and request.content_length > 16384:
        return jsonify(error="Command is too large."),413
    body = request.get_json(silent=True)
    if not isinstance(body,dict):
        return jsonify(error="Expected a JSON command."),400
    if body.get("action") not in {"create","state","advance","entry","add","exit","cancel","stop","delete_stop","finish"}:
        return jsonify(error="Unknown command."),400
    try:
        response = manager.call(body)
        return jsonify(response),200 if response.get("ok") else (503 if response.get("fatal") else 400)
    except RuntimeError as exc:
        return jsonify(error=str(exc),fatal=True),503


@blueprint.get("/api/reviews")
def reviews():
    result = []
    if DATA.exists():
        for path in DATA.glob("*.json"):
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                result.append({"id":item["id"],"saved_at":item["saved_at"],
                               "date":item["configuration"]["date"],"reason":item["reason"],
                               "realized":item["state"]["account"]["realized"],
                               "trades":len(item["trades"])})
            except (OSError,ValueError,KeyError,TypeError):
                continue
    return jsonify(reviews=sorted(result,key=lambda x:x["saved_at"],reverse=True))


@blueprint.get("/api/reviews/<review_id>")
def review(review_id):
    if not re.fullmatch(r"[0-9a-f]{32}",review_id):
        return jsonify(error="Invalid review ID"),400
    path = DATA/f"{review_id}.json"
    if not path.is_file():
        return jsonify(error="Review not found"),404
    try:
        return jsonify(json.loads(path.read_text(encoding="utf-8")))
    except (OSError,ValueError):
        return jsonify(error="Saved review could not be read"),500
