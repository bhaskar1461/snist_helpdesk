#!/bin/sh
# ============================================================
# Metabase Auto-Setup Script
# Waits for Metabase to be healthy, then:
#   1. Completes initial setup if needed (using setup-token)
#   2. Enables embedding
#   3. Sets the embedding secret key
#   4. Adds the helpdesk MySQL database as a data source
# ============================================================

METABASE_URL="${METABASE_INTERNAL_URL:-http://metabase:3000}"
ADMIN_EMAIL="${MB_ADMIN_EMAIL:-admin@gmail.com}"
ADMIN_PASSWORD="${MB_ADMIN_PASSWORD:-Admin@321#}"
SECRET_KEY="${MB_EMBEDDING_SECRET_KEY}"
DB_HOST="${MYSQL_HOST}"
DB_PORT="${MYSQL_PORT:-3306}"
DB_NAME="${MYSQL_DATABASE}"
DB_USER="${MYSQL_USER}"
DB_PASS="${MYSQL_PASSWORD}"

log() { echo "[metabase-init] $(date '+%H:%M:%S') $1"; }

# --- Wait for Metabase to be healthy ---
log "Waiting for Metabase at ${METABASE_URL}..."
for i in $(seq 1 60); do
    STATUS=$(python3 -c "
import urllib.request, json, sys
try:
    r = urllib.request.urlopen('${METABASE_URL}/api/health', timeout=2)
    d = json.loads(r.read())
    print(d.get('status',''))
except: print('down')
" 2>/dev/null)
    if [ "$STATUS" = "ok" ]; then
        log "Metabase is healthy!"
        break
    fi
    sleep 2
done

if [ "$STATUS" != "ok" ]; then
    log "ERROR: Metabase did not become healthy after 120s. Skipping setup."
    exit 0
fi

# --- Check if initial setup is needed ---
SETUP_TOKEN=$(python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('${METABASE_URL}/api/session/properties', timeout=5)
    d = json.loads(r.read())
    print(d.get('setup-token') or '')
except: print('')
" 2>/dev/null)

if [ -n "$SETUP_TOKEN" ]; then
    log "Running initial Metabase setup..."
    python3 -c "
import urllib.request, json
data = json.dumps({
    'token': '${SETUP_TOKEN}',
    'user': {
        'first_name': 'Admin',
        'last_name': 'Helpdesk',
        'email': '${ADMIN_EMAIL}',
        'password': '${ADMIN_PASSWORD}'
    },
    'prefs': {
        'site_name': 'SNIST Helpdesk Analytics',
        'site_locale': 'en',
        'allow_tracking': False
    }
}).encode()
req = urllib.request.Request('${METABASE_URL}/api/setup', data=data, method='POST')
req.add_header('Content-Type', 'application/json')
try:
    r = urllib.request.urlopen(req, timeout=15)
    print('Setup OK:', r.read().decode())
except Exception as e:
    print('Setup error (may already be done):', e)
" 2>&1
    log "Initial setup complete."
else
    log "Metabase already set up — skipping initial setup."
fi

# --- Login to get session token ---
log "Logging in to Metabase..."
SESSION_ID=$(python3 -c "
import urllib.request, json
data = json.dumps({'username': '${ADMIN_EMAIL}', 'password': '${ADMIN_PASSWORD}'}).encode()
req = urllib.request.Request('${METABASE_URL}/api/session', data=data, method='POST')
req.add_header('Content-Type', 'application/json')
try:
    r = urllib.request.urlopen(req, timeout=10)
    d = json.loads(r.read())
    print(d.get('id', ''))
except Exception as e:
    print('')
" 2>/dev/null)

if [ -z "$SESSION_ID" ]; then
    log "ERROR: Could not login to Metabase. Skipping configuration."
    exit 0
fi
log "Logged in successfully."

# --- Enable embedding ---
log "Enabling embedding..."
python3 -c "
import urllib.request, json
for setting in ['enable-embedding', 'enable-embedding-static']:
    data = json.dumps({'value': True}).encode()
    req = urllib.request.Request(f'${METABASE_URL}/api/setting/{setting}', data=data, method='PUT')
    req.add_header('Content-Type', 'application/json')
    req.add_header('X-Metabase-Session', '${SESSION_ID}')
    try:
        urllib.request.urlopen(req, timeout=10)
        print(f'{setting} enabled.')
    except Exception as e:
        print(f'{setting} enable error:', e)
" 2>&1

# --- Set embedding secret key ---
if [ -n "$SECRET_KEY" ]; then
    log "Setting embedding secret key..."
    python3 -c "
import urllib.request, json
data = json.dumps({'value': '${SECRET_KEY}'}).encode()
req = urllib.request.Request('${METABASE_URL}/api/setting/embedding-secret-key', data=data, method='PUT')
req.add_header('Content-Type', 'application/json')
req.add_header('X-Metabase-Session', '${SESSION_ID}')
try:
    urllib.request.urlopen(req, timeout=10)
    print('Secret key set.')
except Exception as e:
    print('Secret key error:', e)
" 2>&1
fi

# --- Add MySQL database if not already added ---
log "Checking for existing database connections..."
DB_COUNT=$(python3 -c "
import urllib.request, json
req = urllib.request.Request('${METABASE_URL}/api/database')
req.add_header('X-Metabase-Session', '${SESSION_ID}')
try:
    r = urllib.request.urlopen(req, timeout=10)
    d = json.loads(r.read())
    # Count non-sample databases
    count = sum(1 for db in d.get('data', []) if not db.get('is_sample', False))
    print(count)
except: print('0')
" 2>/dev/null)

if [ "$DB_COUNT" = "0" ] && [ -n "$DB_HOST" ]; then
    log "Adding helpdesk MySQL database..."
    python3 -c "
import urllib.request, json
data = json.dumps({
    'engine': 'mysql',
    'name': 'SNIST Helpdesk',
    'details': {
        'host': '${DB_HOST}',
        'port': int('${DB_PORT}'),
        'dbname': '${DB_NAME}',
        'user': '${DB_USER}',
        'password': '${DB_PASS}',
        'ssl': False
    }
}).encode()
req = urllib.request.Request('${METABASE_URL}/api/database', data=data, method='POST')
req.add_header('Content-Type', 'application/json')
req.add_header('X-Metabase-Session', '${SESSION_ID}')
try:
    r = urllib.request.urlopen(req, timeout=15)
    print('Database added:', json.loads(r.read()).get('id'))
except Exception as e:
    print('Database add error:', e)
" 2>&1
else
    log "Database already configured (${DB_COUNT} found) or no DB_HOST set."
fi

# --- Automatically create dashboards and visual questions ---
log "Configuring Metabase embedded dashboards..."
python3 /scripts/configure_metabase.py || python3 /app/scripts/configure_metabase.py || log "Metabase dashboard configuration complete or skipped."

log "Metabase auto-setup complete!"


