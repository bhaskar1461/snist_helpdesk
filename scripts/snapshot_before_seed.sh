#!/usr/bin/env bash
# scripts/snapshot_before_seed.sh
# Creates a pre-seed safety backup of production configuration tables.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="${PROJECT_ROOT}/backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_FILE="${BACKUP_DIR}/pre_seed_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# If python is available, execute the python snapshot generator which runs across Linux and Windows
if command -v python3 &>/dev/null; then
    python3 "${SCRIPT_DIR}/snapshot_before_seed.py"
elif command -v python &>/dev/null; then
    python "${SCRIPT_DIR}/snapshot_before_seed.py"
else
    # Fallback to mysqldump
    DB_HOST="${MYSQL_HOST:-seg.sreenidhi.edu.in}"
    DB_USER="${MYSQL_USER:-demo}"
    DB_PASS="${MYSQL_PASSWORD:-Admin@321#}"
    DB_NAME="${MYSQL_DATABASE:-helpdesk}"
    DB_PORT="${MYSQL_PORT:-3306}"

    TABLES="helpdesk_categories helpdesk_ca_assignments helpdesk_staff_roles helpdesk_problem_types"

    echo "=== Taking pre-seed mysqldump snapshot ==="
    echo "Target: ${DB_HOST}:${DB_PORT}/${DB_NAME}"
    echo "Tables: ${TABLES}"

    mysqldump --single-transaction --quick \
        -h "${DB_HOST}" -P "${DB_PORT}" -u "${DB_USER}" -p"${DB_PASS}" \
        "${DB_NAME}" ${TABLES} | gzip > "${OUTPUT_FILE}"

    echo "Backup created successfully: ${OUTPUT_FILE}"
fi
