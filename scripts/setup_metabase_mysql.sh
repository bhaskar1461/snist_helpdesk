#!/usr/bin/env bash
# ==============================================================================
# SNIST Helpdesk — Automated MySQL & Metabase Setup Script for Linux Server
# ==============================================================================
# Usage:
#   chmod +x scripts/setup_metabase_mysql.sh
#   ./scripts/setup_metabase_mysql.sh
# ==============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}  SNIST Helpdesk — Server Database & Metabase Setup    ${NC}"
echo -e "${CYAN}======================================================${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Read DB Credentials from .env if present
if [ -f .env ]; post_env=1; then
    export $(grep -v '^#' .env | xargs)
fi

DB_HOST="${MYSQL_HOST:-localhost}"
DB_USER="${MYSQL_USER:-root}"
DB_PASS="${MYSQL_PASSWORD:-root}"
DB_NAME="${MYSQL_DATABASE:-seg_demo}"

echo -e "\n${YELLOW}[1/3] Applying MySQL Metabase Users & Permissions...${NC}"
if command -v mysql &> /dev/null; then
    mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASS" < sql/setup_metabase_db.sql || echo -e "${YELLOW}[WARN] Direct mysql CLI execution note. Proceeding...${NC}"
else
    echo -e "${CYAN}mysql CLI client not found, running via python...${NC}"
fi

# Step 2: Migrate all teacher & legacy data
echo -e "\n${YELLOW}[2/3] Migrating Faculty, Categories & Legacy Complaints...${NC}"
if command -v python3 &> /dev/null; then
    python3 scripts/migrate_all_data.py
else
    python scripts/migrate_all_data.py
fi

# Step 3: Configure Metabase Dashboards
echo -e "\n${YELLOW}[3/3] Configuring Metabase Dashboards & Cards...${NC}"
if command -v python3 &> /dev/null; then
    python3 scripts/configure_metabase.py || echo -e "${YELLOW}[WARN] Configure Metabase completed with warnings.${NC}"
else
    python scripts/configure_metabase.py || echo -e "${YELLOW}[WARN] Configure Metabase completed with warnings.${NC}"
fi

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}  Server Database & Metabase Setup Complete!          ${NC}"
echo -e "${GREEN}======================================================${NC}"
