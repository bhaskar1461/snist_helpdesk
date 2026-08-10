"""
Metabase Embedding Diagnostic & Force-Repair Utility.
Checks global embedding status, lists all dashboards, force-enables embedding on all dashboards,
and outputs exact .env configuration settings.
"""
import json
import os
import sys
import pathlib
import urllib.request
import urllib.error

# Auto-load .env
env_file = pathlib.Path(__file__).resolve().parent.parent / ".env"
if env_file.exists():
    with open(env_file, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))

METABASE_URL = os.getenv("METABASE_INTERNAL_URL", "http://localhost:3000").rstrip("/")
ADMIN_EMAIL = os.getenv("MB_ADMIN_EMAIL", "admin@gmail.com")
ADMIN_PASSWORD = os.getenv("MB_ADMIN_PASSWORD", "Admin@321#")
SECRET_KEY = os.getenv("METABASE_SECRET_KEY", "b6c0144720edd6f7369910c70c66e0519ac0386c2b9d173434c57332a048e685")
SITE_URL = os.getenv("METABASE_SITE_URL", "https://metabase.1sports.app")

session_token = None

def api(method, path, data=None):
    url = f"{METABASE_URL}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    if session_token:
        req.add_header("X-Metabase-Session", session_token)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  [API Error {e.code}] {method} {path}: {body[:250]}")
        return None
    except Exception as e:
        print(f"  [API Exception] {method} {path}: {e}")
        return None

def main():
    global session_token
    print("=" * 60)
    print("Metabase Embedding Diagnostic & Force-Repair Utility")
    print("=" * 60)
    print(f"Metabase Target URL: {METABASE_URL}")

    # 1. Login
    res = api("POST", "/api/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if not res or "id" not in res:
        print("[FAIL] Could not login to Metabase.")
        sys.exit(1)
    session_token = res["id"]
    print(f"[OK] Logged in as {ADMIN_EMAIL}")

    # 2. Configure Global Settings
    print("\n[+] Configuring Global Metabase Embedding Settings...")
    s1 = api("PUT", "/api/setting/enable-embedding", {"value": True})
    print(f"    enable-embedding: {'OK' if s1 is not None else 'FAILED'}")

    s2 = api("PUT", "/api/setting/embedding-secret-key", {"value": SECRET_KEY})
    print(f"    embedding-secret-key: {'OK' if s2 is not None else 'FAILED'}")

    s3 = api("PUT", "/api/setting/site-url", {"value": SITE_URL})
    print(f"    site-url: {'OK' if s3 is not None else 'FAILED'}")

    # 3. List & Enable Embedding on ALL Dashboards
    print("\n[+] Inspecting & Enabling Embedding on All Dashboards...")
    dashboards = api("GET", "/api/dashboard")
    if not dashboards:
        print("[!] No dashboards returned from Metabase.")
        sys.exit(1)

    dash_list = dashboards if isinstance(dashboards, list) else dashboards.get("data", [])
    print(f"Found {len(dash_list)} total dashboards:\n")

    dash_map = {}

    for d in dash_list:
        did = d.get("id")
        name = d.get("name")
        curr_embed = d.get("enable_embedding")
        print(f"  - Dashboard ID {did}: '{name}' (Current enable_embedding: {curr_embed})")

        # Update embedding
        up_res = api("PUT", f"/api/dashboard/{did}", {
            "enable_embedding": True,
            "embedding_params": {}
        })
        if up_res and up_res.get("enable_embedding") is True:
            print(f"    [SUCCESS] Embedding enabled for Dashboard {did}")
        else:
            print(f"    [!] Failed to enable embedding for Dashboard {did}")

        name_lower = name.lower()
        if "overview" in name_lower and "overview" not in dash_map:
            dash_map["overview"] = did
        elif "trend" in name_lower and "trends" not in dash_map:
            dash_map["trends"] = did
        elif ("ca" in name_lower or "performance" in name_lower or "assignee" in name_lower) and "ca_performance" not in dash_map:
            dash_map["ca_performance"] = did

    # Pick latest dashboard IDs if map incomplete
    if "overview" not in dash_map and dash_list:
        dash_map["overview"] = dash_list[-1]["id"]
    if "trends" not in dash_map and dash_list:
        dash_map["trends"] = dash_list[-1]["id"]
    if "ca_performance" not in dash_map and dash_list:
        dash_map["ca_performance"] = dash_list[-1]["id"]

    print("\n" + "=" * 60)
    print("RECOMMENDED .ENV SETTINGS")
    print("=" * 60)
    print("Add/update these lines in your server's .env file (/var/www/snist_helpdesk/.env):\n")
    print(f"METABASE_DASHBOARD_OVERVIEW={dash_map.get('overview', 4)}")
    print(f"METABASE_DASHBOARD_TRENDS={dash_map.get('trends', 5)}")
    print(f"METABASE_DASHBOARD_CA_PERF={dash_map.get('ca_performance', 6)}")
    print("\nThen run: sudo systemctl restart helpdesk\n")

if __name__ == "__main__":
    main()
