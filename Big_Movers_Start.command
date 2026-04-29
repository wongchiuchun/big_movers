#!/bin/zsh
# Big Movers — double-click launcher.
# Kills any old server on port 5051, starts a fresh one, opens the browser,
# and tails the log inside this Terminal window. Close the window or hit
# Ctrl-C to stop the server.

set -u

PROJECT_DIR="/Users/raywong/Desktop/qullamaggie-study-guide/setup analysis/big_movers"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.13/bin/python3"
PORT=5051
URL="http://localhost:${PORT}/"

cd "$PROJECT_DIR" || { echo "❌ project dir missing: $PROJECT_DIR"; exit 1; }

if [ ! -x "$PYTHON" ]; then
  echo "❌ Python 3.13 not found at $PYTHON"
  echo "   Edit this file and update the PYTHON path."
  exit 1
fi

echo "▶ Big Movers"
echo "  dir   : $PROJECT_DIR"
echo "  python: $PYTHON"
echo "  port  : $PORT"
echo

# Kill any prior server on this port.
PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  echo "  • killing existing server on :$PORT (pid $PIDS)"
  kill $PIDS 2>/dev/null || true
  sleep 0.5
fi

# Open the browser ~2s after the server boots.
( sleep 2 && open "$URL" ) &

echo "  • starting server… (Ctrl-C or close this window to stop)"
echo
exec "$PYTHON" Big_movers_server.py
