#!/usr/bin/env bash
# SNIST Help Desk — Standalone Offline Demo Launcher (Linux / macOS)
set -e
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if command -v python3 &>/dev/null; then
    PYTHON_CMD=python3
elif command -v python &>/dev/null; then
    PYTHON_CMD=python
else
    echo "[ERROR] Python 3 is not installed or not in PATH."
    exit 1
fi

"$PYTHON_CMD" run_demo.py "$@"
