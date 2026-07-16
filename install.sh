#!/usr/bin/env bash
set -e

echo "========================================="
echo " SNIST Helpdesk - Automated Installer"
echo "========================================="

# 1. Dependency Validation
echo "[+] Validating software dependencies..."

if ! [ -x "$(command -v git)" ]; then
  echo "[!] Git is not installed. Installing git..."
  sudo apt-get update && sudo apt-get install git -y
fi

if ! [ -x "$(command -v docker)" ]; then
  echo "[!] Docker is not installed. Installing docker..."
  curl -fsSL https://get.docker.com -o get-docker.sh
  sudo sh get-docker.sh
  rm get-docker.sh
fi

# Check for docker compose plugin (modern version)
if ! docker compose version >/dev/null 2>&1; then
  echo "[!] Docker Compose plugin is missing. Installing compose plugin..."
  sudo apt-get update && sudo apt-get install docker-compose-plugin -y
fi

# 2. Environment Configuration Setup
if [ ! -f .env ]; then
  echo "[+] Copying .env.example configuration..."
  cp .env.example .env
  
  # Generate secure random secret key
  SEC_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "fallback_secret_key_99342211")
  sed -i "s/SECRET_KEY=/SECRET_KEY=$SEC_KEY/g" .env
  echo "[+] Configured custom SECRET_KEY in .env"
fi

# 3. Booting Container Service
echo "[+] Building and starting Docker containers..."
docker compose up -d --build

# 4. Bootstrap Database Schema & Default Seeds
echo "[+] Initializing database schema..."
# Wait for MySQL to become ready
echo "Waiting for database port connectivity..."
sleep 5

docker compose exec -T web python scripts/init_demo_db.py

# 5. Check Health Endpoint
echo "[+] Verifying application health..."
HEALTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/ || echo "000")

if [ "$HEALTH_CHECK" -eq 200 ] || [ "$HEALTH_CHECK" -eq 302 ]; then
  echo "========================================="
  echo " SUCCESS: SNIST Helpdesk is live!"
  echo " Access URL: http://localhost:5000"
  echo "========================================="
else
  echo "[!] Warning: Application returned status $HEALTH_CHECK. Check 'docker compose logs web' for details."
fi
