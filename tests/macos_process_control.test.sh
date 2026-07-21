#!/bin/zsh
set -u

ROOT_DIR=${0:A:h:h}
CONTROL="$ROOT_DIR/mac/big_movers_process.sh"
FIXTURE="$ROOT_DIR/tests/fixtures/stub_big_movers_server.py"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
TEST_DIR=$(mktemp -d /tmp/big-movers-process-test.XXXXXX)
PROJECT_DIR="$TEST_DIR/project"
PID_FILE="$TEST_DIR/server.pid"
LOG_FILE="$TEST_DIR/server.log"
typeset -a OWNED_PIDS
PASS_COUNT=0

fail() {
  print -u2 -- "FAIL: $1"
  exit 1
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  print -- "PASS: $1"
}

remember_pid() {
  [[ "$1" == <-> ]] && OWNED_PIDS+=("$1")
}

cleanup() {
  local pid
  for pid in $OWNED_PIDS; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -CONT "$pid" 2>/dev/null || true
      kill -TERM "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
      kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null || true
    fi
  done
  rm -rf "$TEST_DIR"
}
trap cleanup EXIT INT TERM

free_port() {
  "$PYTHON" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

wait_for_listener() {
  local pid="$1" port="$2"
  for _ in {1..50}; do
    [[ "$(lsof -a -p "$pid" -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)" == "$pid" ]] && return 0
    sleep 0.1
  done
  return 1
}

run_control() {
  /bin/zsh "$CONTROL" "$@"
}

mkdir -p "$PROJECT_DIR"
ln -s "$FIXTURE" "$PROJECT_DIR/Big_movers_server.py"

[[ -f "$CONTROL" ]] || fail "process controller exists"

# Normal start, exact-listener readiness, adoption, status, and stop.
port=$(free_port)
pid=$(run_control start "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$LOG_FILE") || fail "normal start succeeds"
remember_pid "$pid"
[[ -f "$PID_FILE" && "$(<"$PID_FILE")" == "$pid" ]] || fail "start writes its exact PID"
wait_for_listener "$pid" "$port" || fail "owned PID owns the listener"
pass "normal start owns the exact listener"

adopted=$(run_control start "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$LOG_FILE") || fail "second start adopts"
[[ "$adopted" == "$pid" ]] || fail "second start returns the same PID"
pass "second start adopts without duplication"

run_control status "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$pid" || fail "status accepts owned PID"
pass "status verifies the owned live PID"

run_control stop "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$pid" || fail "normal stop succeeds"
[[ ! -e "$PID_FILE" ]] || fail "normal stop removes PID file"
kill -0 "$pid" 2>/dev/null && fail "normal stop leaves process alive"
pass "normal stop terminates and cleans ownership"

# Stale PID recovery.
print -- "999999" > "$PID_FILE"
port=$(free_port)
pid=$(run_control start "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$LOG_FILE") || fail "stale PID recovery starts"
remember_pid "$pid"
[[ "$(<"$PID_FILE")" == "$pid" && "$pid" != "999999" ]] || fail "stale PID was not replaced"
run_control stop "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$pid" || fail "stale recovery stop succeeds"
pass "stale PID file is replaced safely"

# An existing listener with no owned PID file must be left untouched.
port=$(free_port)
(cd "$PROJECT_DIR" && PORTNUM="$port" "$PYTHON" Big_movers_server.py >"$LOG_FILE" 2>&1) &
unowned_listener=$!
remember_pid "$unowned_listener"
wait_for_listener "$unowned_listener" "$port" || fail "unowned fixture did not listen"
rm -f "$PID_FILE"
run_control start "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$LOG_FILE" >/dev/null 2>&1
rc=$?
[[ $rc -eq 11 ]] || fail "unowned port returns 11 (got $rc)"
kill -0 "$unowned_listener" 2>/dev/null || fail "unowned listener was killed"
pass "unowned port occupant is rejected and preserved"
kill -TERM "$unowned_listener" 2>/dev/null || true

# A stubborn owned process makes stop time out without losing ownership.
port=$(free_port)
pid=$(BIG_MOVERS_TEST_IGNORE_TERM=1 run_control start "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$LOG_FILE") || fail "stubborn start succeeds"
remember_pid "$pid"
run_control stop "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$pid" >/dev/null 2>&1
rc=$?
[[ $rc -eq 14 ]] || fail "stubborn stop returns 14 (got $rc)"
kill -0 "$pid" 2>/dev/null || fail "stubborn process did not survive timeout"
[[ -f "$PID_FILE" && "$(<"$PID_FILE")" == "$pid" ]] || fail "stubborn stop lost PID file"
pass "shutdown timeout retains the live process and PID file"
kill -KILL "$pid" 2>/dev/null || true
rm -f "$PID_FILE"

# Live but unowned PIDs are distinguished and never signaled.
sleep 30 &
unowned_pid=$!
remember_pid "$unowned_pid"
run_control status "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$unowned_pid" >/dev/null 2>&1
rc=$?
[[ $rc -eq 15 ]] || fail "live ownership mismatch status returns 15 (got $rc)"
run_control stop "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$unowned_pid" >/dev/null 2>&1
rc=$?
[[ $rc -eq 13 ]] || fail "live ownership mismatch stop returns 13 (got $rc)"
kill -0 "$unowned_pid" 2>/dev/null || fail "ownership mismatch killed live PID"
pass "live ownership mismatch is reported without signaling"
kill -TERM "$unowned_pid" 2>/dev/null || true

# Adopted process that never becomes ready and ignores TERM retains ownership.
port=$(free_port)
(cd "$PROJECT_DIR" && BIG_MOVERS_TEST_IGNORE_TERM=1 BIG_MOVERS_TEST_NO_LISTEN=1 PORTNUM="$port" "$PYTHON" Big_movers_server.py >"$LOG_FILE" 2>&1) &
pid=$!
remember_pid "$pid"
print -- "$pid" > "$PID_FILE"
run_control start "$PROJECT_DIR" "$PYTHON" "$port" "$PID_FILE" "$LOG_FILE" >/dev/null 2>&1
rc=$?
[[ $rc -eq 16 ]] || fail "adopted cleanup timeout returns 16 (got $rc)"
kill -0 "$pid" 2>/dev/null || fail "adopted stubborn PID did not survive"
[[ -f "$PID_FILE" && "$(<"$PID_FILE")" == "$pid" ]] || fail "adopted cleanup timeout lost PID file"
pass "unhealthy adopted server retains ownership when cleanup times out"

print -- "\nmacOS process controller: $PASS_COUNT passed, 0 failed"
