"""
Metabase Dashboard Auto-Configurator for SNIST Helpdesk.
Creates 3 embedded dashboards: Overview, Trends, CA Performance.
Uses the Metabase REST API to create questions, dashboards, and enable embedding.
"""
import json
import os
import sys
import time
import pathlib
import urllib.request
import urllib.error

# Auto-load .env if present
env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

def find_metabase_url():
    candidates = [
        os.getenv("METABASE_INTERNAL_URL"),
        os.getenv("METABASE_SITE_URL"),
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    for url in candidates:
        if not url:
            continue
        try:
            target = url.rstrip("/")
            req = urllib.request.Request(f"{target}/api/health", method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    return target
        except Exception:
            pass
    return "http://localhost:3000"

METABASE_URL = find_metabase_url()
ADMIN_EMAIL = os.getenv("MB_ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.getenv("MB_ADMIN_PASSWORD", "Admin@321#")
DB_NAME = os.getenv("MYSQL_DATABASE", "seg_demo")

session_token = None


def api(method, path, data=None, silent=False):
    """Make a Metabase API call."""
    url = f"{METABASE_URL}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if session_token:
        req.add_header("X-Metabase-Session", session_token)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        if not silent:
            print(f"  API Error {e.code} on {method} {path}: {body[:200]}")
        return None
    except Exception as e:
        if not silent:
            print(f"  API Exception on {method} {path}: {e}")
        return None


def login():
    global session_token, ADMIN_EMAIL, ADMIN_PASSWORD

    # Check if fresh Metabase setup wizard needs to be completed
    try:
        props = api("GET", "/api/session/properties", silent=True)
        if props and props.get("setup-token") and not props.get("has-user-setup"):
            setup_token = props["setup-token"]
            print("[..] Fresh Metabase detected. Auto-completing initial setup wizard...")
            setup_payload = {
                "token": setup_token,
                "user": {
                    "email": ADMIN_EMAIL,
                    "first_name": "Admin",
                    "last_name": "User",
                    "password": ADMIN_PASSWORD,
                    "site_name": "SNIST Helpdesk Analytics"
                },
                "prefs": {
                    "site_name": "SNIST Helpdesk Analytics",
                    "allow_tracking": False
                }
            }
            setup_res = api("POST", "/api/setup", setup_payload, silent=False)
            if setup_res and "id" in setup_res:
                session_token = setup_res["id"]
                print(f"[OK] Metabase initial setup completed with email: {ADMIN_EMAIL}")
                return True
            else:
                print(f"[!] Setup call did not return session ID: {setup_res}")
    except Exception as exc:
        print(f"[!] Metabase setup exception: {exc}")

    # Try configured credentials first, followed by fallbacks
    credentials_to_try = [
        (ADMIN_EMAIL, ADMIN_PASSWORD),
        ("admin@gmail.com", "Admin@321#"),
        ("admin@gmail.com", "Admin@123"),
        ("admin@gmail.com", "password"),
        ("admin@gmail.com", "admin"),
        ("admin@sreenidhi.edu.in", "Admin@321#"),
        ("admin@sreenidhi.edu.in", "Password@123"),
    ]

    seen = set()
    for email, password in credentials_to_try:
        if not email or not password or (email, password) in seen:
            continue
        seen.add((email, password))

        result = api("POST", "/api/session", {"username": email, "password": password}, silent=True)
        if result and "id" in result:
            session_token = result["id"]
            ADMIN_EMAIL = email
            ADMIN_PASSWORD = password
            print(f"[OK] Logged in to Metabase as {email}")
            return True

    print(f"\n[FAIL] Could not login to Metabase. Invalid email or password.")
    print("Please set your server's Metabase login credentials in your .env file:")
    print("  MB_ADMIN_EMAIL=your-metabase-email")
    print("  MB_ADMIN_PASSWORD=your-metabase-password\n")
    return False


def add_database():
    """Add the MySQL database to Metabase using env-var connection details."""
    host = os.getenv("MYSQL_HOST", "localhost")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    dbname = os.getenv("MYSQL_DATABASE", DB_NAME)
    user = os.getenv("MYSQL_USER", "root")
    password = os.getenv("MYSQL_PASSWORD", "")
    ssl = os.getenv("MYSQL_SSL", "false").lower() in ("true", "1", "yes")

    print(f"[..] Adding MySQL database '{dbname}' @ {host}:{port} to Metabase...")
    payload = {
        "engine": "mysql",
        "name": dbname,
        "details": {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "ssl": ssl,
            "tunnel-enabled": False,
        },
        "is_full_sync": True,
        "auto_run_queries": True,
    }
    result = api("POST", "/api/database", payload)
    if result and "id" in result:
        print(f"[OK] Database added: {result['name']} (ID: {result['id']})")
        return result["id"]
    print("[FAIL] Could not add MySQL database to Metabase.")
    if result:
        print(f"  Response: {json.dumps(result)[:300]}")
    return None


def find_database():
    """Find our helpdesk database in Metabase, or add it if missing."""
    result = api("GET", "/api/database")
    if result:
        for db in result.get("data", []):
            if not db.get("is_sample") and db.get("engine") == "mysql":
                print(f"[OK] Found database: {db['name']} (ID: {db['id']})")
                return db["id"]
    # No MySQL database registered yet — auto-add it
    print("[..] No MySQL database found in Metabase. Attempting to add one...")
    return add_database()


def sync_database(db_id):
    """Trigger a database sync and wait for it."""
    print("[..] Syncing database schema...")
    api("POST", f"/api/database/{db_id}/sync_schema")
    # Wait for sync to complete
    for _ in range(15):
        time.sleep(2)
        result = api("GET", f"/api/database/{db_id}/metadata")
        if result and result.get("tables"):
            tables = [t["name"] for t in result["tables"]]
            if "helpdesk_tickets" in tables:
                print(f"[OK] Database synced. Found {len(tables)} tables.")
                return True
    print("[WARN] Sync may still be running.")
    return True


def create_native_question(db_id, name, description, sql, display="table", visualization_settings=None):
    """Create a saved native SQL question."""
    data = {
        "name": name,
        "description": description,
        "dataset_query": {
            "type": "native",
            "native": {"query": sql},
            "database": db_id
        },
        "display": display,
        "visualization_settings": visualization_settings or {},
        "collection_id": None
    }
    result = api("POST", "/api/card", data)
    if result and "id" in result:
        print(f"  [+] Created question: {name} (ID: {result['id']})")
        return result["id"]
    print(f"  [!] Failed to create question: {name}")
    return None



def create_dashboard(name, description):
    """Create a dashboard."""
    result = api("POST", "/api/dashboard", {
        "name": name,
        "description": description,
        "collection_id": None
    })
    if result and "id" in result:
        print(f"  [+] Created dashboard: {name} (ID: {result['id']})")
        return result["id"]
    print(f"  [!] Failed to create dashboard: {name}")
    return None


# Collect cards to add in bulk via PUT
_dashboard_cards = {}  # dashboard_id -> list of card specs

def add_card_to_dashboard(dashboard_id, card_id, row, col, size_x=6, size_y=4):
    """Queue a card to be added to a dashboard (applied via finalize_dashboard)."""
    if dashboard_id not in _dashboard_cards:
        _dashboard_cards[dashboard_id] = []
    _dashboard_cards[dashboard_id].append({
        "id": -(len(_dashboard_cards[dashboard_id]) + 1),  # temporary negative ID
        "card_id": card_id,
        "row": row,
        "col": col,
        "size_x": size_x,
        "size_y": size_y,
    })
    return True


def finalize_dashboard(dashboard_id):
    """Push all queued cards to a dashboard via PUT."""
    cards = _dashboard_cards.get(dashboard_id, [])
    if not cards:
        return
    result = api("PUT", f"/api/dashboard/{dashboard_id}", {
        "dashcards": cards
    })
    if result:
        print(f"  [+] Added {len(cards)} cards to dashboard {dashboard_id}")
    else:
        print(f"  [!] Failed to add cards to dashboard {dashboard_id}")


def enable_global_embedding():
    """Ensure embedding feature and site URL are enabled globally in Metabase settings."""
    api("PUT", "/api/setting/enable-embedding", {"value": True}, silent=True)
    secret_key = os.getenv("METABASE_SECRET_KEY")
    if secret_key:
        api("PUT", "/api/setting/embedding-secret-key", {"value": secret_key}, silent=True)
    site_url = os.getenv("METABASE_SITE_URL")
    if site_url:
        api("PUT", "/api/setting/site-url", {"value": site_url}, silent=True)


def enable_dashboard_embedding(dashboard_id):
    """Enable embedding for a dashboard."""
    # First finalize any queued cards
    finalize_dashboard(dashboard_id)
    # Then enable embedding
    result = api("PUT", f"/api/dashboard/{dashboard_id}", {
        "enable_embedding": True,
        "embedding_params": {}
    })
    if result:
        print(f"  [+] Embedding enabled for dashboard ID {dashboard_id}")
        return True
    # Try alternative field name for newer Metabase
    result = api("PUT", f"/api/dashboard/{dashboard_id}", {
        "enable-embedding": True,
        "embedding-params": {}
    })
    if result:
        print(f"  [+] Embedding enabled for dashboard ID {dashboard_id}")
        return True
    print(f"  [!] Could not enable embedding for dashboard {dashboard_id}")
    return False


def main():
    print("=" * 60)
    print("SNIST Helpdesk — Metabase Dashboard Configurator")
    print("=" * 60)

    if not login():
        sys.exit(1)

    enable_global_embedding()

    db_id = find_database()
    if not db_id:
        sys.exit(1)

    sync_database(db_id)

    # ================================================================
    # DASHBOARD 1: Overview
    # ================================================================
    print("\n--- Creating Overview Dashboard ---")

    q1 = create_native_question(db_id, "Ticket Status Summary",
        "Count of tickets grouped by current status.",
        """
        SELECT status AS 'Status',
               COUNT(*) AS 'Count'
        FROM helpdesk_tickets
        GROUP BY status
        ORDER BY FIELD(status, 'PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED')
        """, "bar", {"graph.dimensions": ["Status"], "graph.metrics": ["Count"]})

    q2 = create_native_question(db_id, "Tickets by Department",
        "Total tickets per department.",
        """
        SELECT c.department AS 'Department',
               COUNT(t.id) AS 'Tickets'
        FROM helpdesk_tickets t
        JOIN helpdesk_categories c ON t.category_id = c.id
        GROUP BY c.department
        ORDER BY COUNT(t.id) DESC
        """, "bar", {"graph.dimensions": ["Department"], "graph.metrics": ["Tickets"]})

    q3 = create_native_question(db_id, "Tickets by Category",
        "Ticket distribution across categories.",
        """
        SELECT c.category_name AS 'Category',
               c.department AS 'Department',
               COUNT(t.id) AS 'Tickets'
        FROM helpdesk_tickets t
        JOIN helpdesk_categories c ON t.category_id = c.id
        GROUP BY c.category_name, c.department
        ORDER BY COUNT(t.id) DESC
        """, "pie", {"pie.dimension": "Category", "pie.metric": "Tickets"})

    q4 = create_native_question(db_id, "Recent Tickets",
        "Latest 20 tickets with status and assignment.",
        """
        SELECT t.id AS 'ID',
               t.title AS 'Title',
               t.status AS 'Status',
               c.category_name AS 'Category',
               c.department AS 'Department',
               u.name AS 'Created By',
               ca.name AS 'Assigned To',
               t.created_at AS 'Created'
        FROM helpdesk_tickets t
        JOIN helpdesk_categories c ON t.category_id = c.id
        JOIN helpdesk_users u ON t.created_by = u.id
        JOIN helpdesk_users ca ON t.assigned_to = ca.id
        ORDER BY t.created_at DESC
        LIMIT 20
        """, "table")

    q5 = create_native_question(db_id, "Total Ticket Count",
        "Single number: total tickets.",
        "SELECT COUNT(*) AS 'Total Tickets' FROM helpdesk_tickets",
        "scalar")

    q6 = create_native_question(db_id, "Pending Ticket Count",
        "Single number: pending tickets.",
        "SELECT COUNT(*) AS 'Pending' FROM helpdesk_tickets WHERE status = 'PENDING'",
        "scalar")

    q7 = create_native_question(db_id, "Resolved Ticket Count",
        "Single number: resolved tickets.",
        "SELECT COUNT(*) AS 'Resolved' FROM helpdesk_tickets WHERE status = 'RESOLVED'",
        "scalar")

    dash_overview = create_dashboard("Helpdesk Overview",
        "Overall ticket status, department distribution, and recent activity.")

    if dash_overview:
        # Row 0: KPI numbers (3 cards across 18 cols = 6 cols each)
        if q5: add_card_to_dashboard(dash_overview, q5, 0, 0, 6, 3)
        if q6: add_card_to_dashboard(dash_overview, q6, 0, 6, 6, 3)
        if q7: add_card_to_dashboard(dash_overview, q7, 0, 12, 6, 3)
        # Row 3: Main Charts (10 cols + 8 cols = 18 cols)
        if q1: add_card_to_dashboard(dash_overview, q1, 3, 0, 10, 6)
        if q2: add_card_to_dashboard(dash_overview, q2, 3, 10, 8, 6)
        # Row 9: Category Pie (8 cols) + Recent Tickets Table (10 cols)
        if q3: add_card_to_dashboard(dash_overview, q3, 9, 0, 8, 7)
        if q4: add_card_to_dashboard(dash_overview, q4, 9, 8, 10, 7)
        enable_dashboard_embedding(dash_overview)

    # ================================================================
    # DASHBOARD 2: Trends
    # ================================================================
    print("\n--- Creating Trends Dashboard ---")

    q8 = create_native_question(db_id, "Daily Ticket Creation",
        "Number of tickets created per day.",
        """
        SELECT DATE(created_at) AS 'Date',
               COUNT(*) AS 'Tickets Created'
        FROM helpdesk_tickets
        GROUP BY DATE(created_at)
        ORDER BY DATE(created_at)
        """, "line", {"graph.dimensions": ["Date"], "graph.metrics": ["Tickets Created"]})

    q9 = create_native_question(db_id, "Daily Resolutions",
        "Number of tickets resolved per day.",
        """
        SELECT DATE(updated_at) AS 'Date',
               COUNT(*) AS 'Tickets Resolved'
        FROM helpdesk_tickets
        WHERE status = 'RESOLVED'
        GROUP BY DATE(updated_at)
        ORDER BY DATE(updated_at)
        """, "line", {"graph.dimensions": ["Date"], "graph.metrics": ["Tickets Resolved"]})

    q10 = create_native_question(db_id, "Weekly Ticket Volume",
        "Tickets created and resolved per week.",
        """
        SELECT DATE_FORMAT(t.created_at, '%Y-W%v') AS 'Week',
               COUNT(*) AS 'Created',
               SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS 'Resolved'
        FROM helpdesk_tickets t
        GROUP BY DATE_FORMAT(t.created_at, '%Y-W%v')
        ORDER BY DATE_FORMAT(t.created_at, '%Y-W%v') ASC
        LIMIT 12
        """, "bar", {"graph.dimensions": ["Week"], "graph.metrics": ["Created", "Resolved"]})

    q11 = create_native_question(db_id, "Status Transition Flow",
        "All status transitions with timestamps.",
        """
        SELECT a.id,
               u.name AS 'Action By',
               COALESCE(a.from_status, 'â€”') AS 'From',
               a.to_status AS 'To',
               a.remarks AS 'Remarks',
               a.created_at AS 'Timestamp'
        FROM helpdesk_ticket_activity a
        JOIN helpdesk_users u ON a.action_by = u.id
        ORDER BY a.created_at DESC
        LIMIT 50
        """, "table")

    q12 = create_native_question(db_id, "Tickets by Hour of Day",
        "When are tickets created? Distribution by hour.",
        """
        SELECT CONCAT(LPAD(HOUR(created_at), 2, '0'), ':00') AS `Hour`,
               COUNT(*) AS `Tickets`
        FROM helpdesk_tickets
        GROUP BY HOUR(created_at), CONCAT(LPAD(HOUR(created_at), 2, '0'), ':00')
        ORDER BY HOUR(created_at) ASC
        """, "bar", {"graph.dimensions": ["Hour"], "graph.metrics": ["Tickets"]})

    dash_trends = create_dashboard("Helpdesk Trends",
        "Ticket creation and resolution trends over time.")

    if dash_trends:
        # Row 0: Daily Creation (9 cols) & Daily Resolutions (9 cols)
        if q8:  add_card_to_dashboard(dash_trends, q8,  0, 0, 9, 6)
        if q9:  add_card_to_dashboard(dash_trends, q9,  0, 9, 9, 6)
        # Row 6: Weekly Volume (18 cols)
        if q10: add_card_to_dashboard(dash_trends, q10, 6, 0, 18, 6)
        # Row 12: Hour of Day (8 cols) & Transition Flow Table (10 cols)
        if q12: add_card_to_dashboard(dash_trends, q12, 12, 0, 8, 7)
        if q11: add_card_to_dashboard(dash_trends, q11, 12, 8, 10, 7)
        enable_dashboard_embedding(dash_trends)

    # ================================================================
    # DASHBOARD 3: CA Performance
    # ================================================================
    print("\n--- Creating CA Performance Dashboard ---")

    q13 = create_native_question(db_id, "CA Workload Summary",
        "Tickets assigned to each CA with status breakdown.",
        """
        SELECT ca.name AS 'CA Name',
               ca.email AS 'Email',
               ca.department AS 'Department',
               COUNT(t.id) AS 'Total Assigned',
               SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS 'Resolved',
               SUM(CASE WHEN t.status IN ('PENDING','IN_PROGRESS','REOPENED') THEN 1 ELSE 0 END) AS 'Active',
               SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS 'On Hold'
        FROM helpdesk_tickets t
        JOIN helpdesk_users ca ON t.assigned_to = ca.id
        GROUP BY ca.id, ca.name, ca.email, ca.department
        ORDER BY COUNT(t.id) DESC
        """, "table")

    q14 = create_native_question(db_id, "Avg Resolution Time by CA",
        "Average hours between ticket creation and resolution per CA.",
        """
        SELECT ca.name AS `CA Name`,
               ROUND(AVG(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)), 1) AS `Avg Hours`
        FROM helpdesk_tickets t
        JOIN helpdesk_users ca ON t.assigned_to = ca.id
        WHERE t.status = 'RESOLVED'
        GROUP BY ca.id, ca.name
        ORDER BY AVG(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at))
        """, "bar", {"graph.dimensions": ["CA Name"], "graph.metrics": ["Avg Hours"]})

    q15 = create_native_question(db_id, "Resolution Time by Category",
        "Average resolution time for each ticket category.",
        """
        SELECT c.category_name AS `Category`,
               c.department AS `Department`,
               COUNT(t.id) AS `Resolved`,
               ROUND(AVG(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)), 1) AS `Avg Hours`,
               ROUND(MIN(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)), 1) AS `Min Hours`,
               ROUND(MAX(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at)), 1) AS `Max Hours`
        FROM helpdesk_tickets t
        JOIN helpdesk_categories c ON t.category_id = c.id
        WHERE t.status = 'RESOLVED'
        GROUP BY c.id, c.category_name, c.department
        ORDER BY AVG(TIMESTAMPDIFF(HOUR, t.created_at, t.updated_at))
        """, "table")

    q16 = create_native_question(db_id, "CA Resolution Rate",
        "Percentage of assigned tickets resolved by each CA.",
        """
        SELECT ca.name AS 'CA Name',
               COUNT(t.id) AS 'Total',
               SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS 'Resolved',
               ROUND(100.0 * SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) / COUNT(t.id), 1) AS 'Resolution Rate %'
        FROM helpdesk_tickets t
        JOIN helpdesk_users ca ON t.assigned_to = ca.id
        GROUP BY ca.id, ca.name
        HAVING COUNT(t.id) > 0
        ORDER BY ROUND(100.0 * SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) / COUNT(t.id), 1) DESC
        """, "bar", {"graph.dimensions": ["CA Name"], "graph.metrics": ["Resolution Rate %"]})


    q17 = create_native_question(db_id, "Overdue/Active Tickets by CA",
        "Currently active (non-resolved) tickets per CA, oldest first.",
        """
        SELECT ca.name AS 'CA Name',
               t.id AS 'Ticket ID',
               t.title AS 'Title',
               t.status AS 'Status',
               c.category_name AS 'Category',
               t.created_at AS 'Created',
               TIMESTAMPDIFF(HOUR, t.created_at, NOW()) AS 'Age (hrs)'
        FROM helpdesk_tickets t
        JOIN helpdesk_users ca ON t.assigned_to = ca.id
        JOIN helpdesk_categories c ON t.category_id = c.id
        WHERE t.status NOT IN ('RESOLVED')
        ORDER BY t.created_at ASC
        LIMIT 50
        """, "table")

    dash_ca = create_dashboard("CA Performance",
        "Concerned Authority workload, resolution rates, and active tickets.")

    if dash_ca:
        # Row 0: Workload Summary (18 cols)
        if q13: add_card_to_dashboard(dash_ca, q13, 0, 0, 18, 6)
        # Row 6: Avg Res Time (9 cols) & Res Rate (9 cols)
        if q14: add_card_to_dashboard(dash_ca, q14, 6, 0, 9, 6)
        if q16: add_card_to_dashboard(dash_ca, q16, 6, 9, 9, 6)
        # Row 12: Resolution by Category Table (18 cols)
        if q15: add_card_to_dashboard(dash_ca, q15, 12, 0, 18, 6)
        # Row 18: Overdue/Active Tickets Table (18 cols)
        if q17: add_card_to_dashboard(dash_ca, q17, 18, 0, 18, 7)
        enable_dashboard_embedding(dash_ca)

    # ================================================================
    # Print summary
    # ================================================================
    print("\n" + "=" * 60)
    print("CONFIGURATION COMPLETE")
    print("=" * 60)
    dashboards = {
        "overview": dash_overview,
        "trends": dash_trends,
        "ca_performance": dash_ca
    }
    for key, did in dashboards.items():
        print(f"  {key}: Dashboard ID {did}")

    print(f"\n  Update your .env file:")
    print(f"    METABASE_DASHBOARD_OVERVIEW={dash_overview or 1}")
    print(f"    METABASE_DASHBOARD_TRENDS={dash_trends or 1}")
    print(f"    METABASE_DASHBOARD_CA_PERF={dash_ca or 1}")
    print()


if __name__ == "__main__":
    main()

