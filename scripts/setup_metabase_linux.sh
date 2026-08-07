#!/usr/bin/env bash
# ==============================================================================
# SNIST Helpdesk — Automated Metabase Setup Script for Linux (Non-Docker)
# ==============================================================================
# Usage:
#   chmod +x scripts/setup_metabase_linux.sh
#   sudo ./scripts/setup_metabase_linux.sh
# ==============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}======================================================${NC}"
echo -e "${CYAN}  SNIST Helpdesk — Metabase Setup & Auto-Configure     ${NC}"
echo -e "${CYAN}======================================================${NC}"

# 1. Ensure running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}[ERROR] Please run this script with sudo or as root:${NC}"
    echo "  sudo ./scripts/setup_metabase_linux.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
METABASE_DIR="/opt/metabase"
METABASE_JAR="$METABASE_DIR/metabase.jar"
METABASE_PORT=3000
SECRET_KEY="b6c0144720edd6f7369910c70c66e0519ac0386c2b9d173434c57332a048e685"

# 2. Install OpenJDK 17 if not installed
echo -e "\n${YELLOW}[1/5] Checking Java installation...${NC}"
if ! command -v java &> /dev/null || ! java -version 2>&1 | grep -q "17\|11\|21"; then
    echo -e "${CYAN}Installing OpenJDK 17...${NC}"
    apt-get update -qq
    apt-get install -y -qq openjdk-17-jre wget curl
else
    echo -e "${GREEN}[OK] Java is already installed.${NC}"
fi

# 3. Download Metabase jar
echo -e "\n${YELLOW}[2/5] Setting up Metabase directory...${NC}"
mkdir -p "$METABASE_DIR"

if [ ! -f "$METABASE_JAR" ]; then
    echo -e "${CYAN}Downloading Metabase v0.49.0...${NC}"
    wget -q --show-progress -O "$METABASE_JAR" https://downloads.metabase.com/v0.49.0/metabase.jar
else
    echo -e "${GREEN}[OK] Metabase jar already present at $METABASE_JAR.${NC}"
fi

# 4. Create systemd service for Metabase
echo -e "\n${YELLOW}[3/5] Configuring systemd service (metabase.service)...${NC}"
cat <<EOF > /etc/systemd/system/metabase.service
[Unit]
Description=Metabase Analytics Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$METABASE_DIR
Environment="MB_JETTY_PORT=$METABASE_PORT"
Environment="MB_EMBEDDING_SECRET_KEY=$SECRET_KEY"
ExecStart=/usr/bin/java -jar $METABASE_JAR
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable metabase
systemctl restart metabase
echo -e "${GREEN}[OK] metabase.service started on port $METABASE_PORT.${NC}"

# 5. Wait for Metabase health check
echo -e "\n${YELLOW}[4/5] Waiting for Metabase to initialize (this takes ~30 seconds)...${NC}"
MAX_RETRY=30
RETRY_COUNT=0
HEALTH_OK=0

while [ $RETRY_COUNT -lt $MAX_RETRY ]; do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:$METABASE_PORT/api/health || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        HEALTH_OK=1
        break
    fi
    sleep 3
    RETRY_COUNT=$((RETRY_COUNT + 1))
    echo -n "."
done

echo ""
if [ $HEALTH_OK -eq 1 ]; then
    echo -e "${GREEN}[OK] Metabase is online and healthy!${NC}"
else
    echo -e "${RED}[WARN] Metabase health check timed out. Proceeding anyway...${NC}"
fi

# 6. Auto-configure Metabase Dashboards & Cards
echo -e "\n${YELLOW}[5/5] Running Metabase Dashboard Auto-Configuration...${NC}"
cd "$PROJECT_DIR"

if command -v python3 &> /dev/null; then
    python3 scripts/configure_metabase.py || echo -e "${YELLOW}[WARN] Configure script failed. You can re-run: python3 scripts/configure_metabase.py${NC}"
else
    echo -e "${RED}[WARN] python3 not found. Please run 'python3 scripts/configure_metabase.py' manually.${NC}"
fi

echo -e "\n${GREEN}======================================================${NC}"
echo -e "${GREEN}  Metabase Setup Complete!                             ${NC}"
echo -e "${GREEN}======================================================${NC}"
echo -e "Metabase URL:      http://localhost:$METABASE_PORT"
echo -e "Service Status:    sudo systemctl status metabase"
echo -e "Service Logs:      sudo journalctl -u metabase -f"
echo -e "${CYAN}Make sure your .env file has:${NC}"
echo "  METABASE_SITE_URL=http://<your-domain-or-ip>:$METABASE_PORT"
echo "  METABASE_INTERNAL_URL=http://localhost:$METABASE_PORT"
echo "  METABASE_SECRET_KEY=$SECRET_KEY"
echo ""
