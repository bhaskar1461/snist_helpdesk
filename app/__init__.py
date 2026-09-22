"""SNIST Helpdesk — Application Factory."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_wtf.csrf import CSRFProtect

from app.config import (
    BASE_DIR, DEFAULT_DEMO_CATEGORIES, DEFAULT_DEMO_USERS,
    get_flask_config,
)
from app.helpers import resolve_user_org

log = logging.getLogger(__name__)

# ── Shared service instances ────────────────────────────────────────
_demo_db = None
_live_db = None
_csrf = CSRFProtect()


def get_demo_db():
    return _demo_db


def get_live_db():
    return _live_db


def create_app(testing=False):
    """Create and configure the Flask application."""
    global _demo_db, _live_db

    # Load .env before anything else (preserve existing env vars)
    load_dotenv(BASE_DIR / ".env", override=False)

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.update(get_flask_config())
    app.secret_key = app.config["SECRET_KEY"]

    # Reverse proxy header support (Cloudflare, Nginx, ALB)
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # CSRF protection
    _csrf.init_app(app)

    import sys
    is_check_only = os.getenv("RUN_STARTUP_CHECKS_ONLY", "0").strip() in ("1", "true")
    force_checks = os.getenv("FORCE_STARTUP_CHECKS", "0").strip() in ("1", "true")
    is_testing_env = (
        (
            testing
            or app.config.get("TESTING")
            or "unittest" in sys.modules
            or "pytest" in sys.modules
            or os.getenv("TESTING", "false").lower() == "true"
            or os.getenv("SKIP_STARTUP_CHECKS", "0").strip() in ("1", "true")
        )
        and not force_checks
    )

    # ── Startup Configuration Validation ─────────────────────────────
    if not is_testing_env or is_check_only:
        from app.config_validator import validate_config, format_issues_panel
        cfg_issues = validate_config()
        cfg_errors = [i for i in cfg_issues if i["level"] == "ERROR"]
        cfg_warnings = [i for i in cfg_issues if i["level"] == "WARNING"]
        for w in cfg_warnings:
            log.warning("Configuration warning [%s]: %s (Fix: %s)", w["check"], w["message"], w.get("fix", ""))
        if cfg_errors and not is_check_only:
            panel = format_issues_panel(cfg_errors, "STARTUP CONFIGURATION VALIDATION FAILED")
            sys.stderr.write(panel + "\n")
            sys.stderr.flush()
            raise SystemExit(1)

    # ── Database Services ───────────────────────────────────────────
    from db_services import DemoDbService, LiveDbService, DbConfig

    host = os.getenv("MYSQL_HOST", "seg-dev.sreenidhi.edu.in")
    user = os.getenv("MYSQL_USER", "demo")
    password = os.getenv("MYSQL_PASSWORD", "Admin@321#")
    database = os.getenv("MYSQL_DATABASE", "helpdesk")
    port = int(os.getenv("MYSQL_PORT", "3306"))
    db_config = DbConfig(host=host, port=port, user=user, password=password, database=database) if all([host, user, password, database]) else None

    _live_db = LiveDbService(db_config)
    _demo_db = DemoDbService(db_config)

    # ── Check-Only Mode (Pre-deployment verification) ─────────────────
    if is_check_only:
        from app.config_validator import validate_config, format_issues_panel
        from app.startup_checks import check_database, format_readiness_panel
        print("=" * 80)
        print(" RUNNING PRE-DEPLOYMENT STARTUP CHECKS (CHECK-ONLY MODE)")
        print("=" * 80)
        cfg_issues = validate_config()
        if cfg_issues:
            print(format_issues_panel(cfg_issues, "CONFIGURATION VALIDATION REPORT"))
        db_report = check_database(db_service=_demo_db)
        print(format_readiness_panel(db_report, "DATABASE READINESS REPORT"))
        has_cfg_errors = any(i["level"] == "ERROR" for i in cfg_issues)
        if has_cfg_errors or db_report.get("has_failure"):
            print("\n[FAILED] PRE-DEPLOYMENT CHECKS ENCOUNTERED BLOCKING ERRORS.")
            raise SystemExit(1)
        else:
            print("\n[PASSED] ALL CONFIGURATION AND DATABASE READINESS CHECKS PASSED.")
            raise SystemExit(0)

    # ── Optional Demo Data Seeder (Development Only) ───────────────
    # Schema DDL is managed exclusively via scripts/migrate.py.
    # Automatic DDL execution at web-worker startup is strictly eliminated.
    if not is_testing_env and os.getenv("INIT_DEMO_DB", "false").lower() == "true" and _demo_db.enabled:
        try:
            _init_database_schema(_demo_db)
        except Exception as exc:
            log.error("Database seed failed: %s", exc)

    # ── Startup Database Readiness Validation (non-testing only) ─────
    if not is_testing_env and db_config and _demo_db.enabled:
        from app.startup_checks import check_database, format_readiness_panel
        db_report = check_database(db_service=_demo_db)
        for c in db_report.get("checks", []):
            if c.get("status") == "WARN":
                app.logger.warning("Database readiness warning [%s]: %s (Fix: %s)", c["check"], c["detail"], c.get("fix", ""))
        if db_report.get("has_failure"):
            panel = format_readiness_panel(db_report, "STARTUP DATABASE READINESS CHECK FAILED")
            sys.stderr.write(panel + "\n")
            sys.stderr.flush()
            raise SystemExit(1)

    # ── Register Blueprints ─────────────────────────────────────────
    from app.auth import auth_bp
    from app.tickets import tickets_bp
    from app.management import management_bp
    from app.dashboards import dashboards_bp
    from app.analytics import analytics_bp
    from app.api import api_bp
    from app.health import health_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(management_bp)
    app.register_blueprint(dashboards_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(health_bp)
    _csrf.exempt(health_bp)
    _csrf.exempt(api_bp)

    @app.route("/metrics", methods=["GET"])
    def root_metrics():
        from app.health import prometheus_metrics
        return prometheus_metrics()

    _csrf.exempt(root_metrics)

    # ── Context Processors ──────────────────────────────────────────
    @app.context_processor
    def inject_user_context():
        from app.helpers import current_user
        curr_user = current_user()
        return {"current_user": curr_user, "user": curr_user}

    # ── Security Headers ────────────────────────────────────────────
    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=(), payment=()"

        # Derive minimal Content-Security-Policy
        from app.config import METABASE_SITE_URL, METABASE_INTERNAL_URL
        mb_sources = {s.strip() for s in (METABASE_SITE_URL, METABASE_INTERNAL_URL, "https://metabase.1sports.app", "http://localhost:3000", "http://localhost:3002") if s and s.strip()}
        frame_sources = "'self' " + " ".join(sorted(mb_sources))

        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob:; "
            f"frame-src {frame_sources}; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self' https://accounts.google.com;"
        )
        response.headers["Content-Security-Policy"] = csp
        return response

    # ── Error Handlers ──────────────────────────────────────────────

    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("error.html", error_code=404,
                               error_title="Page Not Found",
                               error_message="The page you're looking for doesn't exist or has been moved."), 404

    @app.errorhandler(403)
    def forbidden(e):
        from flask import render_template
        return render_template("error.html", error_code=403,
                               error_title="Access Denied",
                               error_message="You don't have permission to access this resource."), 403

    @app.errorhandler(500)
    def server_error(e):
        from flask import render_template
        import traceback, sys
        err_msg = traceback.format_exc()
        sys.stderr.write(f"\n--- EXCEPTION TRACEBACK ---\n{err_msg}\n---------------------------\n")
        sys.stderr.flush()
        log.error("Internal server error: %s\n%s", e, err_msg)
        return render_template("error.html", error_code=500,
                               error_title="Server Error",
                               error_message="Something went wrong. Please try again later."), 500


    # ── Legacy Static File Serving Shim (30-day redirect with IDOR check) ──
    @app.route("/uploads/<path:filename>")
    def download_attachment(filename):
        """Legacy attachment route shim: validates authentication and participant authorization, then redirects (302) to canonical route."""
        from flask import abort, redirect, request, url_for
        from app.config import UPLOAD_DIR
        from app.helpers import current_user
        from app.security import can_user_access_ticket_attachment, validate_attachment_path

        user = current_user()
        if not user:
            return redirect(url_for("auth.login", next=request.url))

        demo_db = get_demo_db()
        ticket_id = demo_db.get_attachment_ticket_id(filename) if demo_db else None
        if not ticket_id:
            abort(404)

        ticket = demo_db.get_ticket(ticket_id)
        if not ticket:
            abort(404)

        if not can_user_access_ticket_attachment(user, ticket):
            abort(404)

        safe_file_path = validate_attachment_path(filename, UPLOAD_DIR)
        if not safe_file_path:
            abort(404)

        return redirect(url_for("tickets.download_attachment", ticket_id=ticket_id, filename=filename), code=302)

    log.info("Application factory complete. Blueprints: auth, tickets, management, dashboards, analytics, api.")
    return app


def _init_database_schema(demo_db):
    """
    Deprecated: Schema DDL creation and migration are managed exclusively via scripts/migrate.py.
    Runtime schema mutation is strictly eliminated.
    This function only performs starter reference data seeding if tables already exist and are empty (dev only).
    """
    log.warning("Runtime schema DDL is deprecated and disabled. Apply schema changes via 'python scripts/migrate.py up'.")
    if not demo_db or not demo_db.enabled:
        return

    from werkzeug.security import generate_password_hash

    try:
        with demo_db.connection() as connection, connection.cursor() as cursor:
            # Check if helpdesk_users exists before querying
            cursor.execute("SHOW TABLES LIKE 'helpdesk_users'")
            if not cursor.fetchone():
                log.warning("helpdesk_users table does not exist. Run 'python scripts/migrate.py up' to initialize schema.")
                return

            # ── Seed Default Users (if empty) ───────────────────────────
            cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_users")
            if cursor.fetchone()["cnt"] == 0:
                for u in DEFAULT_DEMO_USERS:
                    hashed = generate_password_hash(u["password"])
                    cursor.execute(
                        "INSERT INTO helpdesk_users (name, email, password, role, department) VALUES (%s, %s, %s, %s, %s)",
                        (u["name"], u["email"], hashed, u["role"], u["department"]),
                    )
                log.info("Seeded %d default demo users.", len(DEFAULT_DEMO_USERS))

            # ── Seed Default Categories (if empty) ──────────────────────
            cursor.execute("SHOW TABLES LIKE 'helpdesk_categories'")
            if cursor.fetchone():
                cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_categories")
                if cursor.fetchone()["cnt"] == 0:
                    for c in DEFAULT_DEMO_CATEGORIES:
                        cursor.execute(
                            "SELECT id FROM helpdesk_users WHERE email = %s LIMIT 1",
                            (c["authority_email"],),
                        )
                        ca_row = cursor.fetchone()
                        if ca_row:
                            cursor.execute(
                                "INSERT INTO helpdesk_categories (category_name, department, assigned_ca_id) VALUES (%s, %s, %s)",
                                (c["category_name"], c["department"], ca_row["id"]),
                            )
                    log.info("Seeded %d default demo categories.", len(DEFAULT_DEMO_CATEGORIES))
    except Exception as exc:
        log.warning("Data seeding skipped or encountered error: %s", exc)


def _verify_database_startup(demo_db):
    """
    Fail-fast startup validation to ensure database connectivity, SELECT access
    to institutional tables/views, and the existence of core helpdesk_* tables.
    """
    if not demo_db or not demo_db.config:
        return
    import sys
    from app.startup_checks import check_database, format_readiness_panel
    report = check_database(db_service=demo_db)
    if report.get("has_failure"):
        panel = format_readiness_panel(report, "STARTUP DATABASE READINESS CHECK FAILED")
        sys.stderr.write(panel + "\n")
        sys.stderr.flush()
        raise RuntimeError("Database startup readiness checks failed. See details above.")


# Module-level exports for package import compatibility
from app.helpers import LOGIN_ATTEMPTS  # noqa: E402



