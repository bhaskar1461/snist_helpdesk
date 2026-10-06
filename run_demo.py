#!/usr/bin/env python3
"""
SNIST Help Desk — 1-Command Standalone Offline Demo Launcher
===========================================================
Runs the full SNIST Help Desk application 100% offline with zero external dependencies:
- No MySQL server needed
- No internet / VPN required
- No SMS / WhatsApp gateways needed (simulated in console)
- In-memory SQLite/JSON persistence (demo_state.json)
- Automatic browser opening
"""

import sys
import os
import time
import argparse
import threading
import webbrowser

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

def check_and_install_dependencies():
    """Verify required dependencies exist; offer automatic installation if missing."""
    required = ["flask", "flask_wtf", "werkzeug", "dotenv"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        print(f"\n[!] Missing Python packages detected: {', '.join(missing)}")
        print("[*] Installing required dependencies from requirements.txt...")
        import subprocess
        req_file = os.path.join(PROJECT_ROOT, "requirements.txt")
        if os.path.exists(req_file):
            ret = subprocess.call([sys.executable, "-m", "pip", "install", "-r", req_file])
            if ret != 0:
                print("\n[x] Failed to install dependencies. Please run:")
                print(f"    pip install -r requirements.txt")
                sys.exit(1)
        else:
            ret = subprocess.call([sys.executable, "-m", "pip", "install"] + missing)
            if ret != 0:
                print(f"\n[x] Could not install missing packages: {missing}")
                sys.exit(1)
        print("[+] Dependencies installed successfully!\n")

def print_banner(host, port, state_file, reset_requested):
    url = f"http://{host}:{port}"
    banner = f"""
================================================================================
           🏛️  SNIST CAMPUS HELPDESK — OFFLINE DEMO MODE  🏛️
================================================================================
  Server running at: {url}
  Status:            100% Standalone (Zero External Connections)
  Persistence:       {state_file}
  {"Reset Applied:     Clean slate re-initialized!" if reset_requested else "State:             Persistent across restarts (run with --reset to wipe)"}
--------------------------------------------------------------------------------
                   🔑  ONE-CLICK DEMO CREDENTIALS  🔑
--------------------------------------------------------------------------------
  Role                Email                             Password
  -----------------   -------------------------------   ---------
  👑 Super Admin      admin@gmail.com                   123
  🏛️ Campus Admin     campus.admin@gmail.com            123
  🎓 HOD (CSE)        shirisha.k@sreenidhi.edu.in       123
  🛠️ Assignee (ICT)   managerict@sreenidhi.edu.in       123
  👨‍🏫 Faculty (CSE)    aruna.v@sreenidhi.edu.in          123
--------------------------------------------------------------------------------
  💡 Tip: On the login page, you can click any role button to instantly
          autofill credentials without typing!
  📱 Note: SMS and WhatsApp notifications are simulated in this terminal.
================================================================================
  Press Ctrl+C to stop the server anytime.
================================================================================
"""
    print(banner)

def open_browser_later(url, delay=1.2):
    def _open():
        time.sleep(delay)
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass
    t = threading.Thread(target=_open, daemon=True)
    t.start()

def main():
    parser = argparse.ArgumentParser(description="Run SNIST Help Desk in 100% Standalone Demo Mode")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Do not automatically open browser on launch")
    parser.add_argument("--reset", action="store_true", help="Reset demo database state to initial sample data")
    args = parser.parse_args()

    # Step 1: Check dependencies
    check_and_install_dependencies()

    # Step 2: Set demo environment variables before any app imports
    os.environ["DEMO_MODE"] = "true"
    os.environ["OFFLINE_DEMO"] = "true"
    os.environ["FLASK_ENV"] = "development"
    os.environ["FLASK_DEBUG"] = "0"
    os.environ["INIT_DEMO_DB"] = "false"
    os.environ["SSO_ENABLED"] = "false"
    os.environ["METABASE_SITE_URL"] = ""
    os.environ["METABASE_SECRET_KEY"] = ""
    os.environ["SMS_API_KEY"] = ""
    os.environ["WHATSAPP_ENABLED"] = "false"
    os.environ["SMTP_HOST"] = ""

    # Step 3: Activate standalone mock database and state engine
    from app.demo_engine import activate_standalone_demo, DEMO_STATE_PATH
    activate_standalone_demo(reset=args.reset)

    # Step 4: Create Flask Application
    from app import create_app
    app = create_app(testing=False, demo_mode=True)

    # Step 5: Print demo credentials & guidance
    state_display = str(DEMO_STATE_PATH)
    print_banner(args.host, args.port, state_display, args.reset)

    # Step 6: Automatically launch web browser
    demo_url = f"http://{args.host}:{args.port}"
    if not args.no_browser:
        open_browser_later(demo_url)

    # Step 7: Run server
    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        print("\n[*] Demo server stopped. Goodbye!")
        sys.exit(0)

if __name__ == "__main__":
    main()
