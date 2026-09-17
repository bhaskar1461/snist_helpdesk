#!/usr/bin/env bash
# ==============================================================================
# SNIST Helpdesk Pre-Deployment Readiness Check
# ==============================================================================
# This script MUST be executed before starting or reloading granian in the
# systemd service (snist_helpdesk.service) or deploy pipeline (ExecStartPre=).
#
# It executes full configuration and database readiness checks in check-only mode.
# If any required configuration is missing or the database is unreachable/degraded,
# it exits with a non-zero exit code to prevent swapping or booting a broken app.
# ==============================================================================

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

echo "================================================================================"
echo "SNIST HELPDESK PRE-DEPLOYMENT GATE"
echo "Target Directory: ${PROJECT_ROOT}"
echo "================================================================================"

# Enable check-only mode for startup checks
export RUN_STARTUP_CHECKS_ONLY=1

# Execute the application entrypoint in check-only mode
if python -c "from app import create_app; create_app()"; then
    echo ""
    echo "================================================================================"
    echo "DEPLOY PRECHECK PASSED: System configuration and database readiness verified."
    echo "================================================================================"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo "================================================================================"
    echo "DEPLOY BLOCKED: see errors above. Application startup would fail."
    echo "================================================================================"
    exit ${EXIT_CODE}
fi
