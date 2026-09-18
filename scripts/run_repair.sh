#!/usr/bin/env bash
# ==============================================================================
# SNIST Helpdesk - All-in-One Migration Repair Runner
# Resolves virtualenv, installs required dependencies, and runs migration repair.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

echo "================================================================================"
echo "SNIST Helpdesk Migration Repair Runner"
echo "Working Directory: ${PROJECT_ROOT}"
echo "================================================================================"

# 1. Locate or create Python virtual environment
PYTHON_BIN=""

if [ -f "venv/bin/python3" ]; then
    PYTHON_BIN="venv/bin/python3"
elif [ -f ".venv/bin/python3" ]; then
    PYTHON_BIN=".venv/bin/python3"
elif [ -f "/home/ubuntu/projects/snist_helpdesk/venv/bin/python3" ]; then
    PYTHON_BIN="/home/ubuntu/projects/snist_helpdesk/venv/bin/python3"
else
    echo "[INFO] No virtual environment detected. Initializing .venv..."
    python3 -m venv .venv
    PYTHON_BIN=".venv/bin/python3"
fi

echo "[OK] Using Python interpreter: ${PYTHON_BIN}"

# 2. Ensure essential migration dependencies are installed
echo "[INFO] Verifying dependencies (pymysql, python-dotenv)..."
"${PYTHON_BIN}" -m pip install -q pymysql python-dotenv

# 3. Execute migration repair
TARGET="${1:-0006}"
echo "[INFO] Executing migration repair for target: ${TARGET}"
"${PYTHON_BIN}" scripts/migrate.py repair --target="${TARGET}" "${@:2}"

echo "================================================================================"
echo "[SUCCESS] Migration repair complete!"
echo "================================================================================"
