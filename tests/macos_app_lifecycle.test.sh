#!/bin/zsh
set -u

ROOT_DIR=${0:A:h:h}
APP_PATH="$ROOT_DIR/Big Movers.app"
CONTROL="$ROOT_DIR/mac/big_movers_process.sh"
PROJECT_DIR="$ROOT_DIR"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
PORT=5051
PID_FILE="/tmp/big_movers_server.pid"
LOG_FILE="/tmp/big_movers.log"
SERVER_PID=""
PASS_COUNT=0

fail() {
  print -u2 -- "FAIL: $1"
  exit 1
}

pass() {
  PASS_COUNT=$((PASS_COUNT + 1))
  print -- "PASS: $1"
}

app_running() {
  [[ "$(osascript -e 'application "Big Movers" is running' 2>/dev/null)" == "true" ]]
}

listener_pid() {
  lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | head -1
}

wait_until() {
  local description="$1"
  shift
  local step
  for step in {1..100}; do
    "$@" && return 0
    sleep 0.1
  done
  fail "timed out waiting for $description"
}

has_listener() {
  [[ -n "$(listener_pid)" ]]
}

server_is_dead() {
  [[ -n "$SERVER_PID" ]] && ! kill -0 "$SERVER_PID" 2>/dev/null
}

port_is_closed() {
  [[ -z "$(listener_pid)" ]]
}

pid_file_is_gone() {
  [[ ! -e "$PID_FILE" ]]
}

app_is_closed() {
  ! app_running
}

cleanup() {
  if [[ -n "$SERVER_PID" && "$SERVER_PID" == <-> ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill -CONT "$SERVER_PID" 2>/dev/null || true
    /bin/zsh "$CONTROL" stop "$PROJECT_DIR" "$PYTHON" "$PORT" "$PID_FILE" "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  if app_running; then
    osascript -e 'tell application "Big Movers" to quit' >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

[[ -d "$APP_PATH" ]] || fail "Big Movers.app exists"
[[ -z "$(listener_pid)" ]] || fail "port $PORT must be free before the lifecycle test"
if [[ -f "$PID_FILE" ]]; then
  stale_pid=$(<"$PID_FILE")
  if [[ "$stale_pid" == <-> ]] && kill -0 "$stale_pid" 2>/dev/null; then
    fail "live PID file already exists: $PID_FILE -> $stale_pid"
  fi
  rm -f "$PID_FILE"
fi

# Normal launch, reopen, and Quit.
open "$APP_PATH" || fail "open app"
wait_until "server listener" has_listener
SERVER_PID=$(listener_pid)
wait_until "Big Movers to remain running" app_running
pass "Big Movers remains running after launch"

[[ -f "$PID_FILE" ]] || fail "app creates PID file"
[[ "$(<"$PID_FILE")" == "$SERVER_PID" ]] || fail "PID file matches listening server"
pass "app records the exact listening PID"

open "$APP_PATH" || fail "reopen app"
for _ in {1..20}; do sleep 0.1; done
[[ "$(<"$PID_FILE")" == "$SERVER_PID" ]] || fail "reopen replaced the server PID"
pass "reopen keeps the same server"

osascript -e 'tell application "Big Movers" to quit' >/dev/null || fail "normal Quit event"
wait_until "server exit" server_is_dead
wait_until "port closure" port_is_closed
wait_until "PID-file cleanup" pid_file_is_gone
wait_until "app exit" app_is_closed
pass "normal Quit stops the server and exits the app"

# A stopped server cannot process SIGTERM. Quit must time out and be canceled.
SERVER_PID=""
open "$APP_PATH" || fail "second-cycle open app"
wait_until "second-cycle listener" has_listener
SERVER_PID=$(listener_pid)
wait_until "second-cycle app" app_running
kill -STOP "$SERVER_PID" || fail "stop owned server for timeout scenario"

osascript -e 'tell application "Big Movers" to quit' >/dev/null || true
app_running || fail "Quit timeout closed the controller app"
kill -0 "$SERVER_PID" 2>/dev/null || fail "Quit timeout lost the server PID"
[[ -f "$PID_FILE" && "$(<"$PID_FILE")" == "$SERVER_PID" ]] || fail "Quit timeout lost PID ownership"
pass "Quit timeout is canceled and retains ownership"

# SIGTERM is pending while the process is stopped; continuing lets it finish.
kill -CONT "$SERVER_PID" || fail "continue stopped server"
wait_until "pending SIGTERM server exit" server_is_dead
wait_until "idle-handler PID cleanup" pid_file_is_gone
wait_until "idle-handler app exit" app_is_closed
pass "controller exits after it confirms the server is gone"

SERVER_PID=""
print -- "\nmacOS app lifecycle: $PASS_COUNT passed, 0 failed"
