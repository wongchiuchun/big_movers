# Big Movers macOS App Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `Big Movers.app` as a stay-open macOS controller whose normal Quit command safely stops the exact Flask server process it owns.

**Architecture:** A small positional-argument shell controller owns process inspection, PID-file recovery, exact PID/listener verification, startup readiness, and graceful termination. A source-controlled stay-open AppleScript owns the user-facing run/reopen/idle/quit lifecycle and delegates process operations to that controller. A reproducible build script compiles the checked-in app bundle while preserving its custom icon, and shell plus macOS integration tests cover the safety rules and real launch/quit path.

**Tech Stack:** zsh, AppleScript/`osacompile`, macOS `lsof`/`ps`/`kill`, Flask/Python 3.13, ad-hoc `codesign`, shell integration tests.

---

## File Structure

| File | Responsibility | Change |
|---|---|---|
| `mac/big_movers_process.sh` | Process ownership, PID file, readiness, adoption, and graceful stop | Create |
| `mac/BigMovers.applescript` | Stay-open macOS run/reopen/idle/quit lifecycle | Create |
| `mac/build_big_movers_app.sh` | Reproducibly compile/sign the app and preserve its icon | Create |
| `tests/fixtures/stub_big_movers_server.py` | Controlled listener used by process tests, including ignored `SIGTERM` | Create |
| `tests/macos_process_control.test.sh` | Test process controller without GUI dependencies | Create |
| `tests/macos_app_lifecycle.test.sh` | Exercise the real compiled app launch/reopen/normal-Quit lifecycle | Create |
| `Big Movers.app/Contents/*` | Generated stay-open app bundle | Modify via build script |
| `HOW_TO_RUN.md` | Explain Dock lifetime and normal Quit behavior | Modify |

The AppleScript continues to own the production constants (project directory,
Python path, port, PID file, log, and URL). It passes them to the shell
controller, so the helper contains no duplicated machine-specific configuration.

## Process Controller Contract

Commands use positional arguments to keep AppleScript invocation simple:

```text
big_movers_process.sh start  PROJECT PYTHON PORT PID_FILE LOG_FILE
big_movers_process.sh status PROJECT PYTHON PORT PID_FILE PID
big_movers_process.sh stop   PROJECT PYTHON PORT PID_FILE PID
```

Output and exit codes:

| Command | Success | Expected failures |
|---|---|---|
| `start` | Print adopted/new PID; exit 0 | 10 config, 11 unowned port, 12 readiness failure with cleanup complete, 16 readiness cleanup timed out with PID retained |
| `status` | Exit 0 only while PID is ownership-verified and alive | 1 confirmed absent/dead, 15 alive but ownership verification failed |
| `stop` | `SIGTERM`, wait, remove PID file, exit 0; an already-dead PID is also success | 13 live PID ownership rejected, 14 shutdown timeout |

Ownership requires all of the following:

1. PID is numeric and alive.
2. `ps -p PID -o command=` contains the configured Python executable and
   `Big_movers_server.py`.
3. `lsof -a -p PID -d cwd -Fn` reports the exact configured project directory.

Readiness additionally requires `lsof -a -p PID -nP -iTCP:PORT
-sTCP:LISTEN -t` to return that same PID.

---

### Task 1: Build the testable process controller

**Files:**
- Create: `tests/fixtures/stub_big_movers_server.py`
- Create: `tests/macos_process_control.test.sh`
- Create: `mac/big_movers_process.sh`

- [ ] **Step 1: Add the controlled server fixture**

Create a tiny Python HTTP server that reads `PORTNUM`, binds
`127.0.0.1:PORTNUM`, and installs either the normal termination behavior or an
ignored `SIGTERM` when `BIG_MOVERS_TEST_IGNORE_TERM=1`.

```python
#!/usr/bin/env python3
import http.server
import os
import signal
import time

if os.environ.get("BIG_MOVERS_TEST_IGNORE_TERM") == "1":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

port = int(os.environ["PORTNUM"])
if os.environ.get("BIG_MOVERS_TEST_NO_LISTEN") == "1":
    while True:
        time.sleep(1)
server = http.server.ThreadingHTTPServer(("127.0.0.1", port), http.server.SimpleHTTPRequestHandler)
server.serve_forever()
```

- [ ] **Step 2: Write the failing process-controller test**

Create `tests/macos_process_control.test.sh`. The test must:

1. Create a temporary project directory and symlink the fixture into it as
   `Big_movers_server.py`.
2. Choose a free test port using a bound Python socket.
3. Assert `start` creates a PID file and the exact PID owns the listener.
4. Assert a second `start` adopts the same PID.
5. Assert `status` succeeds for the owned PID.
6. Assert `stop` removes the PID file and listener.
7. Assert a stale PID file is replaced safely.
8. Start an unowned listener, assert `start` exits 11, and assert the listener
   remains alive.
9. Start the fixture with `BIG_MOVERS_TEST_IGNORE_TERM=1`, assert `stop` exits
   14, and assert the controller leaves both the process and PID file intact.
10. Point `status` and `stop` at a live but unowned PID; assert exit 15/13 and
    assert the process remains alive.
11. Adopt a controlled owned process that never listens and ignores `SIGTERM`;
    assert `start` exits 16 while retaining the live PID and matching PID file.
12. Clean up only PIDs created and recorded by the test. Cleanup always sends
    `SIGCONT` before `SIGTERM`, then uses `SIGKILL` only for a still-live stub
    process that this test itself created.

Use an assertion helper that prints `PASS:`/`FAIL:` and exits nonzero on the
first failure. Never use a broad `lsof | xargs kill` cleanup.

- [ ] **Step 3: Run the test and verify RED**

Run:

```bash
zsh tests/macos_process_control.test.sh
```

Expected: FAIL because `mac/big_movers_process.sh` does not exist.

- [ ] **Step 4: Implement the minimal controller**

Create `mac/big_movers_process.sh` with `set -u`, strict positional argument
validation, and these focused functions:

```zsh
is_pid() { [[ "$1" == <-> ]]; }
is_alive() { kill -0 "$1" 2>/dev/null; }

is_owned() {
  local pid="$1" project="$2" python="$3" command cwd
  is_pid "$pid" && is_alive "$pid" || return 1
  command=$(ps -p "$pid" -o command= 2>/dev/null) || return 1
  [[ "$command" == *"$python"* && "$command" == *"Big_movers_server.py"* ]] || return 1
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
  [[ "$cwd" == "$project" ]]
}

owns_listener() {
  local pid="$1" port="$2"
  [[ "$(lsof -a -p "$pid" -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)" == "$pid" ]]
}
```

`start` must implement this order:

1. Validate project, Python, port, and writable PID/log parents.
2. Read the PID file. If the PID is owned, poll it for the full bounded
   readiness window; if it becomes the exact listener, print/adopt it.
3. If the owned/adoptable PID does not become ready before the timeout, send
   `SIGTERM` and wait. Remove its PID file and exit 12 only after confirming it
   exited. If it ignores termination, retain its PID file and exit 16.
4. Remove a stale PID file without signaling its PID. If its PID is alive but
   ownership verification fails, leave the PID untouched and continue to the
   independent port-occupancy check.
5. Reject any existing port listener with exit 11.
6. Start from the project directory using:

```zsh
PORTNUM="$port" nohup "$python" Big_movers_server.py \
  </dev/null >"$log_file" 2>&1 &
pid=$!
```

7. Atomically write the PID using a PID-specific temporary file and `mv`.
8. Poll up to five seconds until `is_owned "$pid"` and
   `owns_listener "$pid" "$port"` both succeed.
9. On failure, terminate only if ownership still validates and wait for the
   process. If it exits, remove the matching PID file and exit 12. If it remains
   alive, retain the PID file and exit 16 so the app can keep ownership.

`status` returns 1 only after `kill -0` confirms the PID is absent/dead; it
returns 15 when the PID is alive but ownership cannot be verified. `stop`
returns success for an already-dead PID after removing only a matching PID
file. For a live verified PID it sends only `SIGTERM` and polls for up to five
seconds. On timeout it exits 14 without deleting the PID file. On live ownership
rejection it exits 13 without signaling anything.

Every nonzero path writes a stable, human-readable stderr message including the
relevant PID/port/path so the AppleScript never presents a blank error.

- [ ] **Step 5: Run the process tests and verify GREEN**

Run:

```bash
zsh tests/macos_process_control.test.sh
```

Expected: all process-control assertions pass and no test listener remains.

- [ ] **Step 6: Commit the process layer**

```bash
git add mac/big_movers_process.sh tests/fixtures/stub_big_movers_server.py tests/macos_process_control.test.sh
git commit -m "feat(mac): add safe Big Movers server lifecycle controller"
```

---

### Task 2: Specify the real app lifecycle with a failing integration test

**Files:**
- Create: `tests/macos_app_lifecycle.test.sh`

- [ ] **Step 1: Write the real-bundle lifecycle test**

The test begins only when port 5051 is free. It installs a cleanup trap that
records the post-launch PID, sends `SIGCONT` first in case a failed assertion
left it stopped, and then sends `SIGTERM` only to that recorded PID.

Test this observable sequence:

1. `open "Big Movers.app"`.
2. Wait for port 5051 to listen.
3. Assert `application "Big Movers" is running` returns `true`.
4. Assert `/tmp/big_movers_server.pid` exists and contains the listening PID.
5. Open the same app again and assert the PID file is unchanged.
6. Send `tell application "Big Movers" to quit`.
7. Assert the app exits, the exact server PID exits, port 5051 closes, and the
   PID file disappears.
8. Launch a second cycle, send `SIGSTOP` to its exact server PID so it cannot
   process `SIGTERM`, and send the app a normal Quit event.
9. After the five-second stop timeout, assert the app is still running, the
   stopped PID is still alive, and its PID file is retained.
10. Send `SIGCONT` to the recorded PID so its pending `SIGTERM` completes; then
    assert the idle handler observes the confirmed exit and the app closes.

Use bounded polling helpers (ten seconds maximum); do not use fixed sleeps as
the assertion mechanism.

- [ ] **Step 2: Run the integration test and verify RED**

Run with macOS GUI access:

```bash
zsh tests/macos_app_lifecycle.test.sh
```

Expected against the current bundle: FAIL at `Big Movers remains running after
launch`; the existing fire-and-forget applet has already exited while Flask is
still listening. Confirm the cleanup trap stops the test-started server.

- [ ] **Step 3: Commit the regression test**

```bash
git add tests/macos_app_lifecycle.test.sh
git commit -m "test(mac): reproduce orphaned Big Movers server lifecycle"
```

---

### Task 3: Implement and build the stay-open macOS controller

**Files:**
- Create: `mac/BigMovers.applescript`
- Create: `mac/build_big_movers_app.sh`
- Modify: `Big Movers.app/Contents/Info.plist`
- Modify: `Big Movers.app/Contents/Resources/Scripts/main.scpt`
- Modify: generated bundle signature/resources as emitted by `osacompile`

- [ ] **Step 1: Add the AppleScript source**

Define production constants and runtime state:

```applescript
property projectDir : "/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
property pythonPath : "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
property portNumber : "5051"
property appURL : "http://localhost:5051/"
property pidFile : "/tmp/big_movers_server.pid"
property logFile : "/tmp/big_movers.log"
property controllerPath : projectDir & "/mac/big_movers_process.sh"
property serverPID : missing value
```

Add one `controllerCommand(verb, maybePID)` handler that invokes the helper with
`/bin/zsh`, the resolved `controllerPath`, and every argument shell-quoted via
AppleScript's `quoted form of`. The helper does not rely on its executable bit.

Implement handlers:

- `run`: call `start`, store trimmed PID, and open `appURL`. On exit 10/11/12,
  display one concise dialog using the helper's stderr, leave `serverPID`
  missing, and quit normally. On exit 16, read and validate the retained PID
  file into `serverPID`, notify that startup cleanup timed out, and keep the app
  running so Quit can be retried safely. If that retained PID dies before
  validation, remove only the still-matching PID file and quit normally.
- `reopen`: if `serverPID` is present, open `appURL`; never call `start`.
- `idle`: every two seconds call `status`. Only status 1 (confirmed absent/dead)
  may remove a matching PID file, clear `serverPID`, and quit normally. Status
  15 keeps the app and PID state alive; issue at most one notification per
  incident so a transient verification failure cannot orphan the server.
- `quit`: if `serverPID` is `missing value`, immediately `continue quit` without
  calling the helper. Otherwise call `stop`. Success means the server is
  confirmed gone, so clear state and `continue quit`. For live ownership
  rejection (13) or timeout (14), show one notification with PID/log details
  and return without `continue quit`, canceling Quit and retaining state for a
  safe retry.

Avoid `do shell script "lsof ... | xargs kill"` and avoid `SIGKILL` entirely.

- [ ] **Step 2: Add the reproducible build script**

`mac/build_big_movers_app.sh` must:

1. Resolve repository paths relative to itself.
2. Compile to a `mktemp -d` staging directory with
   `osacompile -s -o "$stage/Big Movers.app" mac/BigMovers.applescript`.
3. Copy the existing `applet.icns` into the staged bundle before replacement.
4. Assert staged `OSAAppletStayOpen` is true and `CFBundleName` is `Big Movers`.
5. Use `ditto` to replace bundle contents without deleting any path outside the
   exact `Big Movers.app` bundle.
6. Refresh the ad-hoc signature using
   `codesign --force --deep --sign - "Big Movers.app"`.
7. Verify `codesign --verify --deep --strict` and decompile `main.scpt` to ensure
   `on quit` is present.
8. Remove only the staging directory via a quoted trap.

- [ ] **Step 3: Build the app**

Run:

```bash
zsh mac/build_big_movers_app.sh
```

Expected: build verification succeeds; `plutil -p` reports
`OSAAppletStayOpen => true`; the existing icon remains present.

- [ ] **Step 4: Run the app lifecycle test and verify GREEN**

Run:

```bash
zsh tests/macos_app_lifecycle.test.sh
```

Expected: launch, stay-running, reopen-with-same-PID, normal Quit, server exit,
PID-file cleanup, and the `SIGSTOP`-induced canceled-Quit scenario all pass.

- [ ] **Step 5: Re-run process tests**

Run:

```bash
zsh tests/macos_process_control.test.sh
```

Expected: all safety assertions still pass.

- [ ] **Step 6: Commit source and generated app**

```bash
git add mac/BigMovers.applescript mac/build_big_movers_app.sh "Big Movers.app"
git commit -m "fix(mac): stop Big Movers server on normal app quit"
```

---

### Task 4: Document and perform full regression verification

**Files:**
- Modify: `HOW_TO_RUN.md`

- [ ] **Step 1: Update user instructions**

Document that `Big Movers.app` remains in the Dock while Flask runs, clicking it
again reopens the browser, and Cmd-Q/Dock Quit is the supported shutdown path.
Retain the `.command` launcher instructions as the visible-Terminal alternative.

- [ ] **Step 2: Run all relevant verification**

Run:

```bash
zsh tests/macos_process_control.test.sh
zsh tests/macos_app_lifecycle.test.sh
for test_file in tests/*.test.cjs; do node "$test_file" || exit 1; done
plutil -extract OSAAppletStayOpen raw "Big Movers.app/Contents/Info.plist"
codesign --verify --deep --strict "Big Movers.app"
git diff --check
git status --short
```

Expected:

- Process and real-app lifecycle tests pass.
- Existing 30 quiz and 29 simulator assertions pass.
- `OSAAppletStayOpen` prints `true`.
- Code signature verification and `git diff --check` succeed.
- Only intended source, tests, documentation, and generated bundle changes are
  present.

- [ ] **Step 3: Manually confirm the user-visible path once**

Open the app from Finder/Dock, confirm the browser opens, then use Cmd-Q or Dock
Quit. Confirm Big Movers leaves the Dock, port 5051 is closed, and no new file
appears in `~/Library/Logs/DiagnosticReports` for Big Movers/Python.

- [ ] **Step 4: Commit documentation**

```bash
git add HOW_TO_RUN.md
git commit -m "docs(mac): explain normal Big Movers app shutdown"
```

---

## Completion Conditions

Implementation is complete only when:

- The original integration test has been observed failing against the old
  bundle and passing against the rebuilt bundle.
- The exact PID owns the readiness socket; separate PID/port checks are not
  accepted.
- Normal Quit uses only ownership-verified `SIGTERM` and stops the server.
- A shutdown timeout cancels Quit and preserves PID ownership for retry.
- Unowned listeners and stale/reused PIDs are never signaled.
- The app remains in the Dock while running and reopening does not duplicate
  the server.
- The app source and build are reproducible, signed, documented, and covered by
  the existing regression suite.
