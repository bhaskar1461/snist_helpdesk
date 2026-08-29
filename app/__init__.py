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
    MIGRATION_V2_PATH, MIGRATION_V3_PATH, MIGRATION_V5_PATH, MIGRATION_V6_PATH,
    SCHEMA_PATH, get_flask_config,
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
    app.secret_key = app.config["SECRET_KEY"]

    # CSRF protection
    _csrf.init_app(app)

    # ── Database Services ───────────────────────────────────────────
    from db_services import DemoDbService, LiveDbService, DbConfig

    host = os.getenv("MYSQL_HOST", "seg-dev.sreenidhi.edu.in")
    user = os.getenv("MYSQL_USER", "demo")
    password = os.getenv("MYSQL_PASSWORD", "Admin@321#")
    database = os.getenv("MYSQL_DATABASE", "seg_demo")
    import sys
    is_testing_env = testing or app.config.get("TESTING") or "unittest" in sys.modules or os.getenv("TESTING", "false").lower() == "true"
    port = int(os.getenv("MYSQL_PORT", "3306"))
    db_config = DbConfig(host=host, port=port, user=user, password=password, database=database) if all([host, user, password, database]) else None


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
        import traceback, sys
        err_msg = traceback.format_exc()
        sys.stderr.write(f"\n--- EXCEPTION TRACEBACK ---\n{err_msg}\n---------------------------\n")
        sys.stderr.flush()
        log.error("Internal server error: %s\n%s", e, err_msg)
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
                        if "REFERENCES command denied" in str(exc) or "1142" in str(exc):
                            import re
                            fallback = re.sub(r',?\s*CONSTRAINT\s+[\w`]+\s+FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+[\w`.]+\s*\([^)]+\)(?:\s+ON\s+(?:DELETE|UPDATE)\s+[A-Z\s]+)*', '', stmt, flags=re.IGNORECASE)
                            fallback = re.sub(r',?\s*FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+[\w`.]+\s*\([^)]+\)(?:\s+ON\s+(?:DELETE|UPDATE)\s+[A-Z\s]+)*', '', fallback, flags=re.IGNORECASE)
                            fallback = re.sub(r',\s*(\n?\s*\))', r'\1', fallback)
                            try:
                                cursor.execute(fallback)
                            except Exception as inner_exc:
                                log.warning("Warning executing fallback statement in base schema: %s", inner_exc)
                        else:
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

        # ── Migration V5: Dedup Keys ───────────────────────────────
        if MIGRATION_V5_PATH.is_file():
            v5_text = MIGRATION_V5_PATH.read_text(encoding="utf-8")
            for stmt in v5_text.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass  # Column/index may already exist

        # ── Migration V6: Rename Tables to Production helpdesk_* ─────
        if MIGRATION_V6_PATH.is_file():
            v6_text = MIGRATION_V6_PATH.read_text(encoding="utf-8")
            for stmt in v6_text.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    try:
                        cursor.execute(stmt)
                    except Exception:
                        pass  # Table rename procedure may already have run

        # ── Ensure phone column exists in helpdesk_users ───────────────
        try:
            cursor.execute("ALTER TABLE helpdesk_users ADD COLUMN phone VARCHAR(32) NULL")
        except Exception:
            pass

        # ── Normalize Legacy Department IDs to Standard Codes ───────
        try:
            branch_map = {
                "1": "EEE", "2": "ME", "3": "ECE", "4": "CSE", "5": "IT", "6": "Bio-Tech",
                "7": "S&H", "8": "MCA", "9": "ECM", "10": "S&H", "11": "MBA", "12": "S&H",
                "13": "CDC", "14": "EPE", "15": "EPE", "16": "DSCE", "17": "VLSI", "18": "Administration",
                "19": "Software Engineering", "20": "CAD/CAM", "21": "Bio-Tech", "22": "MCA",
                "23": "Thermal Engineering", "24": "Computer Science", "25": "Administration",
                "26": "Marketing", "27": "Administration", "28": "Administration", "29": "Administration",
                "30": "Library", "31": "EDC", "32": "TDTC", "33": "Accounts", "34": "CDC",
                "35": "Facilities", "36": "Administration", "37": "Nano Tech", "38": "CNIS",
                "39": "ICT", "40": "Accounts", "41": "Exam", "42": "CSE", "43": "Health Center",
                "44": "Electrical", "45": "HR", "46": "Estate", "47": "Stores", "48": "CDC",
                "49": "Training", "50": "Marketing", "51": "Stores", "52": "1Sports", "53": "SAP",
                "54": "Security", "55": "Administration", "56": "Administration", "57": "Electrical",
                "58": "CSE-AIML", "59": "IOT", "60": "Cyber Security", "61": "Administration",
                "62": "1Sports", "63": "Library", "64": "Training", "65": "Civil Engineering",
                "66": "Civil Engineering", "67": "AIML", "68": "Data Science", "69": "Security",
                "70": "Estate", "71": "Operations", "72": "1Sports", "73": "Admissions",
                "74": "Physical Education", "75": "Administration", "700": "Facilities", "701": "SAP"
            }
            for bid, dcode in branch_map.items():
                cursor.execute("UPDATE helpdesk_users SET department = %s WHERE department = %s", (dcode, bid))
        except Exception:
            pass

        # ── CA Assignments Table ────────────────────────────────────
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS helpdesk_ca_assignments (
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
        cursor.execute("SELECT COUNT(*) AS cnt FROM helpdesk_users")
        if cursor.fetchone()["cnt"] == 0:
            for u in DEFAULT_DEMO_USERS:
                hashed = generate_password_hash(u["password"])
                cursor.execute(
                    "INSERT INTO helpdesk_users (name, email, password, role, department) VALUES (%s, %s, %s, %s, %s)",
                    (u["name"], u["email"], hashed, u["role"], u["department"]),
                )
            log.info("Seeded %d default demo users.", len(DEFAULT_DEMO_USERS))

        # ── Seed Default Categories ─────────────────────────────────
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


# Module-level exports for package import compatibility
from app.helpers import LOGIN_ATTEMPTS  # noqa: E402



