#!/bin/bash
set -euo pipefail
LAB_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
LAB_PYTHON="${EXECUTION_LAB_SETUP_PYTHON:-/Library/Frameworks/Python.framework/Versions/3.13/bin/python3}"
"$LAB_PYTHON" -m venv "$LAB_DIR/.venv"
"$LAB_DIR/.venv/bin/python" -m pip install -r "$LAB_DIR/requirements.txt"
printf '\nExecution Lab environment installed. Restart the big_movers server.\n'
