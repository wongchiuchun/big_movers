#!/bin/zsh
set -u

WAIT_STEPS=50
WAIT_INTERVAL=0.1

die() {
  local code="$1"
  shift
  print -u2 -- "$*"
  exit "$code"
}

is_pid() {
  [[ -n "${1:-}" && "$1" == <-> ]]
}

is_alive() {
  is_pid "${1:-}" && kill -0 "$1" 2>/dev/null
}

process_command() {
  ps -p "$1" -o command= 2>/dev/null
}

process_cwd() {
  lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p'
}

is_owned() {
  local pid="$1" project="$2" python="$3" command command_path cwd project_real python_app python_real
  is_alive "$pid" || return 1
  command=$(process_command "$pid") || return 1
  command_path="${command%% *}"
  python_real=$(realpath "$python" 2>/dev/null || print -r -- "$python")
  python_app=$("$python" -c 'import os, sys; p=os.path.join(sys.prefix,"Resources","Python.app","Contents","MacOS","Python"); print(p if os.path.exists(p) else os.path.realpath(sys.executable))' 2>/dev/null) || return 1
  [[ "$command_path" == "$python" || "$command_path" == "$python_real" || "$command_path" == "$python_app" ]] || return 1
  [[ "$command" == *"Big_movers_server.py"* ]] || return 1
  cwd=$(process_cwd "$pid") || return 1
  project_real=$(realpath "$project" 2>/dev/null || print -r -- "$project")
  cwd=$(realpath "$cwd" 2>/dev/null || print -r -- "$cwd")
  [[ "$cwd" == "$project_real" ]]
}

owns_listener() {
  local pid="$1" port="$2" listener
  listener=$(lsof -a -p "$pid" -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null)
  [[ "$listener" == "$pid" ]]
}

wait_ready() {
  local pid="$1" project="$2" python="$3" port="$4"
  local step
  for step in {1..$WAIT_STEPS}; do
    is_owned "$pid" "$project" "$python" && owns_listener "$pid" "$port" && return 0
    is_alive "$pid" || return 1
    sleep "$WAIT_INTERVAL"
  done
  return 1
}

wait_dead() {
  local pid="$1" step
  for step in {1..$WAIT_STEPS}; do
    is_alive "$pid" || return 0
    sleep "$WAIT_INTERVAL"
  done
  ! is_alive "$pid"
}

read_pid_file() {
  local pid_file="$1" value=""
  [[ -f "$pid_file" ]] || return 1
  IFS= read -r value < "$pid_file" || true
  print -r -- "$value"
}

remove_matching_pid_file() {
  local pid_file="$1" pid="$2" current=""
  [[ -f "$pid_file" ]] || return 0
  IFS= read -r current < "$pid_file" || true
  if [[ "$current" == "$pid" ]]; then
    rm -f -- "$pid_file"
  fi
}

validate_common() {
  local project="$1" python="$2" port="$3" pid_file="$4"
  [[ -d "$project" ]] || die 10 "Project directory not found: $project"
  [[ -x "$python" ]] || die 10 "Python executable not found: $python"
  [[ "$port" == <-> && "$port" -ge 1 && "$port" -le 65535 ]] || die 10 "Invalid port: $port"
  [[ -d "${pid_file:h}" && -w "${pid_file:h}" ]] || die 10 "PID directory is not writable: ${pid_file:h}"
}

start_server() {
  local project="$1" python="$2" port="$3" pid_file="$4" log_file="$5"
  local old_pid="" listeners="" pid="" tmp_pid=""

  validate_common "$project" "$python" "$port" "$pid_file"
  [[ -d "${log_file:h}" && -w "${log_file:h}" ]] || die 10 "Log directory is not writable: ${log_file:h}"
  [[ -f "$project/Big_movers_server.py" ]] || die 10 "Server script not found: $project/Big_movers_server.py"

  old_pid=$(read_pid_file "$pid_file" 2>/dev/null || true)
  if is_pid "$old_pid"; then
    if is_alive "$old_pid"; then
      if is_owned "$old_pid" "$project" "$python"; then
        if wait_ready "$old_pid" "$project" "$python" "$port"; then
          print -r -- "$old_pid"
          return 0
        fi
        kill -TERM "$old_pid" 2>/dev/null || true
        if wait_dead "$old_pid"; then
          remove_matching_pid_file "$pid_file" "$old_pid"
          die 12 "Owned server PID $old_pid did not become ready on port $port and was stopped; see $log_file"
        fi
        die 16 "Owned server PID $old_pid did not become ready and ignored SIGTERM; ownership retained in $pid_file"
      fi
      remove_matching_pid_file "$pid_file" "$old_pid"
    else
      remove_matching_pid_file "$pid_file" "$old_pid"
    fi
  elif [[ -f "$pid_file" ]]; then
    rm -f -- "$pid_file"
  fi

  listeners=$(lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null || true)
  [[ -z "$listeners" ]] || die 11 "Port $port is already used by unowned PID(s): ${listeners//$'\n'/, }"

  cd "$project" || die 10 "Cannot enter project directory: $project"
  PORTNUM="$port" nohup "$python" Big_movers_server.py </dev/null >"$log_file" 2>&1 &
  pid=$!

  tmp_pid="${pid_file}.tmp.${pid}"
  print -r -- "$pid" > "$tmp_pid" || die 10 "Cannot write PID file: $pid_file"
  mv -f -- "$tmp_pid" "$pid_file" || die 10 "Cannot install PID file: $pid_file"

  if wait_ready "$pid" "$project" "$python" "$port"; then
    print -r -- "$pid"
    return 0
  fi

  if is_alive "$pid"; then
    if is_owned "$pid" "$project" "$python"; then
      kill -TERM "$pid" 2>/dev/null || true
      if wait_dead "$pid"; then
        remove_matching_pid_file "$pid_file" "$pid"
        die 12 "Server PID $pid failed readiness on port $port and was stopped; see $log_file"
      fi
    fi
    die 16 "Server PID $pid failed readiness and remains alive; ownership retained in $pid_file"
  fi

  remove_matching_pid_file "$pid_file" "$pid"
  die 12 "Server PID $pid exited before listening on port $port; see $log_file"
}

status_server() {
  local project="$1" python="$2" port="$3" pid_file="$4" pid="$5"
  validate_common "$project" "$python" "$port" "$pid_file"
  if ! is_alive "$pid"; then
    remove_matching_pid_file "$pid_file" "$pid"
    die 1 "Server PID $pid is not running"
  fi
  is_owned "$pid" "$project" "$python" || die 15 "Live PID $pid failed Big Movers ownership verification"
  return 0
}

stop_server() {
  local project="$1" python="$2" port="$3" pid_file="$4" pid="$5"
  validate_common "$project" "$python" "$port" "$pid_file"
  if ! is_alive "$pid"; then
    remove_matching_pid_file "$pid_file" "$pid"
    return 0
  fi
  is_owned "$pid" "$project" "$python" || die 13 "Refusing to stop live unowned PID $pid"
  kill -TERM "$pid" 2>/dev/null || true
  if wait_dead "$pid"; then
    remove_matching_pid_file "$pid_file" "$pid"
    return 0
  fi
  die 14 "Server PID $pid ignored SIGTERM; it is still running and retained in $pid_file"
}

command_name="${1:-}"
case "$command_name" in
  start)
    [[ $# -eq 6 ]] || die 10 "Usage: $0 start PROJECT PYTHON PORT PID_FILE LOG_FILE"
    start_server "$2" "$3" "$4" "$5" "$6"
    ;;
  status)
    [[ $# -eq 6 ]] || die 10 "Usage: $0 status PROJECT PYTHON PORT PID_FILE PID"
    status_server "$2" "$3" "$4" "$5" "$6"
    ;;
  stop)
    [[ $# -eq 6 ]] || die 10 "Usage: $0 stop PROJECT PYTHON PORT PID_FILE PID"
    stop_server "$2" "$3" "$4" "$5" "$6"
    ;;
  *)
    die 10 "Usage: $0 {start|status|stop} ..."
    ;;
esac
