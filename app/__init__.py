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
    MIGRATION_V2_PATH, MIGRATION_V3_PATH, SCHEMA_PATH, get_flask_config,
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

    # Load .env before anything else
    load_dotenv(BASE_DIR / ".env")

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.update(get_flask_config())

    # CSRF protection
    _csrf.init_app(app)

    # ── Database Services ───────────────────────────────────────────
    from db_services import DemoDbService, LiveDbService, DbConfig

    host = os.getenv("MYSQL_HOST", "")
    user = os.getenv("MYSQL_USER", "")
    password = os.getenv("MYSQL_PASSWORD", "")
    database = os.getenv("MYSQL_DATABASE", "")
    import sys
    is_testing_env = testing or app.config.get("TESTING") or "unittest" in sys.modules or os.getenv("TESTING", "false").lower() == "true"
    port = int(os.getenv("MYSQL_PORT", "3306"))
    db_config = None
    if not is_testing_env and all([host, user, password, database]):
        db_config = DbConfig(host=host, port=port, user=user, password=password, database=database)

    _live_db = LiveDbService(db_config)
    _demo_db = DemoDbService(db_config)

    # ── Initialize Database Schema ──────────────────────────────────
    if not is_testing_env and os.getenv("INIT_DEMO_DB", "true").lower() == "true" and _demo_db.enabled:
        try:
            _init_database_schema(_demo_db)
        except Exception as exc:
            log.error("Database initialization failed: %s", exc)

    # ── Register Blueprints ─────────────────────────────────────────
    from app.auth import auth_bp
    from app.tickets import tickets_bp
    from app.management import management_bp
    from app.dashboards import dashboards_bp
    from app.analytics import analytics_bp
    from app.api import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(management_bp)
    app.register_blueprint(dashboards_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(api_bp)

    # ── Context Processors ──────────────────────────────────────────
    @app.context_processor
    def inject_user_context():
        from app.helpers import current_user
        curr_user = current_user()
        return {"current_user": curr_user, "user": curr_user}

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
        log.error("Internal server error: %s", e)
        return render_template("error.html", error_code=500,
                               error_title="Server Error",
                               error_message="Something went wrong. Please try again later."), 500

    # ── Static File Serving (attachments) ───────────────────────────
    @app.route("/uploads/<path:filename>")
    def download_attachment(filename):
        from flask import send_from_directory
        from werkzeug.utils import secure_filename
        from app.config import UPLOAD_DIR
        safe_name = secure_filename(filename)
        return send_from_directory(str(UPLOAD_DIR), safe_name)

    log.info("Application factory complete. Blueprints: auth, tickets, management, dashboards, analytics, api.")
    return app


def _init_database_schema(demo_db):
    """Initialize base schema, run migrations, and seed default data."""
    import hashlib

    from werkzeug.security import generate_password_hash

    with demo_db.connection() as connection, connection.cursor() as cursor:
        # ── Base Schema ─────────────────────────────────────────────
        if SCHEMA_PATH.is_file():
            sql_text = SCHEMA_PATH.read_text(encoding="utf-8")
            for stmt in sql_text.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        cursor.execute(stmt)
                    except Exception as exc:
                        log.warning("Warning executing statement in base schema: %s", exc)

        # ── Migration V2 ───────────────────────────────────────────
        if MIGRATION_V2_PATH.is_file():
            v2_text = MIGRATION_V2_PATH.read_text(encoding="utf-8")
            for stmt in v2_text.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass  # Table may already exist

        # ── Migration V3 ───────────────────────────────────────────
        if MIGRATION_V3_PATH.is_file():
            v3_text = MIGRATION_V3_PATH.read_text(encoding="utf-8")
            for stmt in v3_text.split(";"):
                stmt = stmt.strip()
                if stmt:
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass  # Table may already exist

        # ── CA Assignments Table ────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS demo_ca_assignments (
                id INT UNSIGNED NOT NULL AUTO_INCREMENT,
                category_id INT UNSIGNED NOT NULL,
                ca_id INT UNSIGNED NOT NULL,
                block VARCHAR(120) NOT NULL DEFAULT '',
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY uq_ca_category_block (category_id, ca_id, block),
                KEY idx_ca_assignments_ca (ca_id),
                KEY idx_ca_assignments_category (category_id)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        # ── Seed Default Users ──────────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM demo_users")
        if cursor.fetchone()["cnt"] == 0:
            for u in DEFAULT_DEMO_USERS:
                hashed = generate_password_hash(u["password"])
                cursor.execute(
                    "INSERT INTO demo_users (name, email, password, role, department) VALUES (%s, %s, %s, %s, %s)",
                    (u["name"], u["email"], hashed, u["role"], u["department"]),
                )
            log.info("Seeded %d default demo users.", len(DEFAULT_DEMO_USERS))

        # ── Seed Default Categories ─────────────────────────────────
        cursor.execute("SELECT COUNT(*) AS cnt FROM demo_categories")
        if cursor.fetchone()["cnt"] == 0:
            for c in DEFAULT_DEMO_CATEGORIES:
                cursor.execute(
                    "SELECT id FROM demo_users WHERE email = %s LIMIT 1",
                    (c["authority_email"],),
                )
                ca_row = cursor.fetchone()
                if ca_row:
                    cursor.execute(
                        "INSERT INTO demo_categories (category_name, department, assigned_ca_id) VALUES (%s, %s, %s)",
                        (c["category_name"], c["department"], ca_row["id"]),
                    )
            log.info("Seeded %d default demo categories.", len(DEFAULT_DEMO_CATEGORIES))


# Module-level exports for package import compatibility
from app.helpers import LOGIN_ATTEMPTS  # noqa: E402



