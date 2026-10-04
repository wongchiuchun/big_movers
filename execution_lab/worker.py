"""One worker, one session. Stdout is exclusively the JSON-line protocol."""
import contextlib
import json
from pathlib import Path
import sys
import traceback

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB / "vendor"))
sys.path.insert(0, str(LAB.parent))


def main():
    session = None
    seen = {}
    for line in sys.stdin:
        request_id = None
        try:
            body = json.loads(line)
            request_id = body.get("command_id")
            action = body.get("action")
            if not isinstance(request_id,str) or not 1 <= len(request_id) <= 100:
                raise ValueError("A command ID is required.")
            fingerprint = json.dumps(body, sort_keys=True)
            if request_id in seen:
                if seen[request_id] != fingerprint:
                    raise ValueError("Command ID was reused with different content.")
                result = session.state() if session else None
            else:
                # Any upstream printing is diagnostic output, never protocol.
                with contextlib.redirect_stdout(sys.stderr):
                    if action == "create":
                        if session and not session.ended:
                            raise ValueError("Finish the active session before starting another.")
                        from execution_lab.session import Session
                        new_session = Session(body)
                        session = new_session
                    else:
                        if not session or body.get("session_id") != session.id:
                            raise ValueError("Session is missing or stale. Refresh the session.")
                        if session.failed:
                            raise ValueError("Worker session failed. Restart the local server to start again.")
                        if action != "state":
                            session.commands.append({"time": session.now//1_000_000_000,
                                                     "request": body})
                        if action == "advance":
                            session.advance(body.get("seconds",1))
                        elif action == "finish":
                            session.finish()
                        elif action != "state":
                            session.command(action,body)
                    result = session.state()
                seen[request_id] = fingerprint
            response = {"ok": True, "command_id": request_id, "state": result}
        except (ValueError, TypeError, KeyError) as exc:
            response = {"ok": False, "command_id": request_id, "error": str(exc)}
        except ImportError as exc:
            response = {"ok": False, "command_id": request_id,
                        "error": f"Worker dependency missing: {exc}. Run bash big_movers/execution_lab/setup.sh."}
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            if session:
                session.failed = True
            response = {"ok": False, "command_id": request_id, "fatal": True,
                        "error": f"Simulation stopped: {type(exc).__name__}: {exc}. Restart server; see execution_lab/data/worker.log."}
        print(json.dumps(response, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
