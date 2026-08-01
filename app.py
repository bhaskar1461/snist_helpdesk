from __future__ import annotations

import csv
import io
import logging
import os
import re
from functools import wraps
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask, Response, abort, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from flask_wtf.csrf import CSRFProtect
from markupsafe import escape
from werkzeug.utils import secure_filename

from db_services import APP_ROLE_TO_DB, ROLE_MAP, DemoDbService, LiveDbService, env_db_config

from collections import defaultdict
import time

load_dotenv()

log = logging.getLogger(__name__)

app = Flask(__name__)
_secret = os.getenv("SECRET_KEY", "")
if not _secret or _secret in ("change-me-in-production", "snist-helpdesk-demo-secret"):
    import secrets as _s
    _secret = _s.token_hex(32)
    log.warning("SECRET_KEY not set — using a random key. Sessions will NOT persist across restarts.")
app.secret_key = _secret
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)
csrf = CSRFProtect(app)

# Brute-force protection / Rate limiting (H-3)
LOGIN_ATTEMPTS = defaultdict(list)
LOCKOUT_TIME = 60  # 1 minute lockout
MAX_ATTEMPTS = 5   # 5 attempts in 1 minute

def is_login_rate_limited(ip):
    now = time.time()
    # Clean up old attempts
    LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < LOCKOUT_TIME]
    return len(LOGIN_ATTEMPTS[ip]) >= MAX_ATTEMPTS

def record_login_attempt(ip):
    LOGIN_ATTEMPTS[ip].append(time.time())

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "sql" / "demo_schema.sql"
MIGRATION_V2_PATH = BASE_DIR / "sql" / "migration_v2.sql"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "doc", "docx", "xls", "xlsx"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

DB_CONFIG = env_db_config()
live_db = LiveDbService(DB_CONFIG)
demo_db = DemoDbService(DB_CONFIG)

DEFAULT_DEMO_USERS = [
    # SNIST org (2000)
    {"name": "Super Admin", "email": "admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "org_id": "2000"},
    {"name": "Campus Admin", "email": "campus.admin@gmail.com", "password": "123", "role": "ADMIN", "department": "Administration", "org_id": "2000"},
    {"name": "Dr. Kavya", "email": "hod@gmail.com", "password": "123", "role": "HOD", "department": "CSE", "org_id": "2000"},
    {"name": "Dr. Harini", "email": "hod.ece@gmail.com", "password": "123", "role": "HOD", "department": "ECE", "org_id": "2000"},
    {"name": "Chandini", "email": "ca@gmail.com", "password": "123", "role": "CA", "department": "CSE", "org_id": "2000"},
    {"name": "Sravan", "email": "sravan.ca@gmail.com", "password": "123", "role": "CA", "department": "Facilities", "org_id": "2000"},
    {"name": "Bhaskar", "email": "bhaskar.ca@gmail.com", "password": "123", "role": "CA", "department": "Maintenance", "org_id": "2000"},
    {"name": "Demo User", "email": "faculty@gmail.com", "password": "123", "role": "FACULTY", "department": "CSE", "org_id": "2000"},
    # SNU org (3000)
    {"name": "SNU Admin", "email": "snu.admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "org_id": "3000"},
]

DEFAULT_DEMO_CATEGORIES = [
    {"category_name": "Internet", "department": "CSE", "authority_email": "ca@gmail.com"},
    {"category_name": "Projector", "department": "CSE", "authority_email": "ca@gmail.com"},
    {"category_name": "Plumbing", "department": "Facilities", "authority_email": "bhaskar.ca@gmail.com"},
    {"category_name": "Electrical", "department": "Maintenance", "authority_email": "bhaskar.ca@gmail.com"},
]


def bootstrap_demo_database():
    if os.getenv("INIT_DEMO_DB", "true").lower() == "false":
        log.info("INIT_DEMO_DB is false – skipping demo schema init.")
        return
    if not demo_db.enabled:
        log.warning("Demo DB not configured – skipping bootstrap.")
        return
    try:
        try:
            demo_db.ensure_schema(SCHEMA_PATH)
        except Exception as schema_exc:
            log.warning("Schema initialization warning: %s", schema_exc)
        try:
            demo_db.seed_defaults(DEFAULT_DEMO_USERS, DEFAULT_DEMO_CATEGORIES)
        except Exception as seed_exc:
            log.warning("Default seeding warning: %s", seed_exc)
        # Migration: add location_id if it doesn't exist yet
        try:
            with demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM demo_tickets LIKE 'location_id'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE demo_tickets ADD COLUMN location_id INT UNSIGNED NULL COMMENT 'FK to location table' AFTER org_id")
                    log.info("Migration: added location_id column to demo_tickets.")
        except Exception as mig_exc:
            log.warning("Migration check for location_id: %s", mig_exc)
        # Migration: add is_active to demo_categories if it doesn't exist yet
        try:
            with demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM demo_categories LIKE 'is_active'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE demo_categories ADD COLUMN is_active TINYINT(1) NOT NULL DEFAULT 1 AFTER assigned_ca_id")
                    log.info("Migration: added is_active column to demo_categories.")
        except Exception as mig_exc:
            log.warning("Migration check for is_active in demo_categories: %s", mig_exc)
        # Migration: add ON_HOLD and REOPENED to status ENUM
        try:
            with demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM demo_tickets LIKE 'status'")
                col = cur.fetchone()
                if col and 'ON_HOLD' not in str(col.get('Type', '')):
                    cur.execute("ALTER TABLE demo_tickets MODIFY COLUMN status ENUM('PENDING','IN_PROGRESS','ON_HOLD','RESOLVED','REOPENED') NOT NULL DEFAULT 'PENDING'")
                    cur.execute("ALTER TABLE demo_ticket_activity MODIFY COLUMN from_status ENUM('PENDING','IN_PROGRESS','ON_HOLD','RESOLVED','REOPENED') NULL")
                    cur.execute("ALTER TABLE demo_ticket_activity MODIFY COLUMN to_status ENUM('PENDING','IN_PROGRESS','ON_HOLD','RESOLVED','REOPENED') NOT NULL")
                    log.info("Migration: added ON_HOLD and REOPENED to status ENUMs.")
        except Exception as mig_exc:
            log.warning("Migration check for status ENUM: %s", mig_exc)
        # Migration: create demo_ca_assignments table
        try:
            with demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS demo_ca_assignments (
                      id INT UNSIGNED NOT NULL AUTO_INCREMENT,
                      category_id INT UNSIGNED NOT NULL,
                      ca_id INT UNSIGNED NOT NULL,
                      block VARCHAR(100) NOT NULL,
                      created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                      PRIMARY KEY (id),
                      UNIQUE KEY uq_demo_ca_assignments_cat_block_ca (category_id, block, ca_id)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
                """)
                log.info("Migration: created demo_ca_assignments table if not exists.")
        except Exception as mig_exc:
            log.warning("Migration check for demo_ca_assignments: %s", mig_exc)
        # Migration v2: run migration_v2.sql for problem_types, audit_events, etc.
        try:
            if MIGRATION_V2_PATH.exists():
                v2_sql = MIGRATION_V2_PATH.read_text(encoding="utf-8")
                v2_statements = [s.strip() for s in v2_sql.split(";") if s.strip() and not s.strip().startswith("--")]
                with demo_db.connection() as conn, conn.cursor() as cur:
                    for stmt in v2_statements:
                        try:
                            cur.execute(stmt)
                        except Exception:
                            pass  # ignore individual statement failures (e.g. table already exists)
                log.info("Migration v2 executed successfully.")
        except Exception as mig_exc:
            log.warning("Migration v2: %s", mig_exc)
        # Migration v2: add problem_type_id column to demo_tickets
        try:
            with demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM demo_tickets LIKE 'problem_type_id'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE demo_tickets ADD COLUMN problem_type_id INT UNSIGNED NULL AFTER category_id")
                    log.info("Migration v2: added problem_type_id column to demo_tickets.")
        except Exception as mig_exc:
            log.warning("Migration v2 problem_type_id: %s", mig_exc)
        # Migration v2: add is_archived column to branch_detail
        try:
            with demo_db.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM branch_detail LIKE 'is_archived'")
                if not cur.fetchone():
                    cur.execute("ALTER TABLE branch_detail ADD COLUMN is_archived TINYINT(1) NOT NULL DEFAULT 0")
                    log.info("Migration v2: added is_archived column to branch_detail.")
        except Exception as mig_exc:
            log.warning("Migration v2 is_archived: %s", mig_exc)
        log.info("Demo database bootstrapped successfully.")
    except Exception as exc:
        log.error("Demo DB bootstrap failed: %s", exc)


bootstrap_demo_database()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def verify_file_signature(file_stream) -> bool:
    try:
        header = file_stream.read(4)
        file_stream.seek(0)
        
        # PNG
        if header.startswith(b'\x89PNG'):
            return True
        # JPEG
        if header.startswith(b'\xff\xd8'):
            return True
        # PDF
        if header.startswith(b'%PDF'):
            return True
        # GIF
        if header.startswith(b'GIF8'):
            return True
        # ZIP / DOCX / XLSX
        if header.startswith(b'PK\x03\x04'):
            return True
        # OLE CF (legacy doc, xls)
        if header.startswith(b'\xd0\xcf\x11\xe0'):
            return True
        
        return False
    except Exception:
        return False


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def resolve_user_org(email, department):
    email_lower = (email or "").lower().strip()
    
    # 1) Try live_db lookup by email first
    if live_db.enabled and email_lower:
        resolved = live_db.resolve_org_id(email=email_lower)
        if resolved:
            return resolved

    domain = ""
    if "@" in email_lower:
        domain = email_lower.split("@", 1)[1]

    if domain in ("suh.edu.in", "snu.edu.in") or "snu" in domain:
        return "3000"
    if domain == "sreenidhi.edu.in" or "sreenidhi" in domain:
        return "2000"
    if email_lower in ("admin@gmail.com", "campus.admin@gmail.com"):
        return "2000"
    if email_lower == "snu.admin@gmail.com":
        return "3000"
    
    # 2) Fallback to department mapping if email lookup yielded nothing
    if department and live_db.enabled:
        resolved = live_db.resolve_org_id(department=department)
        if resolved:
            return resolved
            
    return "2000"


def current_user():
    if not session.get("user_id"):
        return None
    email = session["user_email"]
    dept = session.get("acting_department") or session["department"]
    role = session.get("acting_role") or session["role"]
    return {
        "id": session["user_id"],
        "name": session["user_name"],
        "email": email,
        "role": role,
        "department": dept,
        "org_id": resolve_user_org(email, dept),
    }


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in to continue.", "error")
                return redirect("/login")
            if user["role"] not in roles:
                flash("You do not have access to that page.", "error")
                return redirect(url_for(route_for_role(user["role"])))
            return view_func(*args, **kwargs)

        return wrapper

    return decorator


def route_for_role(role):
    return {
        "SUPER_ADMIN": "super_admin_dashboard",
        "ADMIN": "admin_dashboard",
        "HOD": "hod_dashboard",
        "CA": "authority_tickets",
        "FACULTY": "user_dashboard",
    }.get(role, "login")


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "snist_helpdesk"}), 200



def sidebar_links(role):
    mapping = {
        "SUPER_ADMIN": [
            ("create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("super_admin_dashboard", "Dashboard", "layout-dashboard"),
            ("super_admin_all_tickets", "All Tickets", "ticket"),
            ("user_management", "User Management", "users"),
            ("management_category", "Category Management", "folder-open"),
            ("location_management", "Location Management", "map-pin"),
            ("ca_assignments", "CA Assignments", "users"),
        ],
        "ADMIN": [
            ("create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("admin_dashboard", "Dashboard", "layout-dashboard"),
            ("admin_all_tickets", "All Tickets", "ticket"),
            ("user_management", "User Management", "users"),
            ("management_category", "Category Management", "folder-open"),
        ],
        "HOD": [
            ("create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("hod_dashboard", "Dashboard", "layout-dashboard"),
            ("hod_all_tickets", "Department Tickets", "ticket"),
            ("user_management", "User Management", "users"),
            ("management_category", "Category Management", "folder-open"),
            ("ca_assignments", "CA Assignments", "users"),
        ],
        "CA": [
            ("create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("authority_tickets", "CA Dashboard", "layout-dashboard"),
            ("ca_report", "Reports", "bar-chart-3"),
        ],
        "FACULTY": [
            ("create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("user_dashboard", "Dashboard", "layout-dashboard"),
            ("my_tickets", "My Tickets", "ticket"),
        ],
    }
    links = mapping.get(role, [])
    if role != "SUPER_ADMIN":
        links = links + [("change_password", "Change Password", "lock")]
    return links + [("logout", "Logout", "log-out")]


def page_context(role_title):
    user = current_user()
    org_id = user["org_id"] if user else "2000"
    org_label = ORG_LABELS.get(org_id, "SNIST")
    logo_filename = "images/snu_logo.webp" if org_id == "3000" else "images/snist_logo.jpg"
    return {
        "role_title": role_title,
        "user_name": user["name"] if user else "",
        "role_email": user["email"] if user else "",
        "current_role": user["role"] if user else "",
        "sidebar_links": sidebar_links(user["role"]) if user else [],
        "db_ready": demo_db.enabled,
        "org_label": org_label,
        "logo_filename": logo_filename,
    }


def live_departments(org_id=None):
    rows = live_db.fetch_departments() if live_db.enabled else []
    departments = []
    seen = set()
    for row in rows:
        row_org_id = row.get("org_id") or "2000"
        if org_id and row_org_id != org_id:
            continue
        code = row.get("department_code") or row.get("department_name")
        if not code or code in seen:
            continue
        seen.add(code)
        departments.append(
            {
                "id": row.get("BRANCH_ID"),
                "code": code,
                "name": row.get("department_name") or code,
                "org_id": row_org_id,
                "is_archived": row.get("is_archived", 0),
            }
        )
    if not departments:
        default_list = [
            {"code": "CSE", "name": "Computer Science and Engineering", "org_id": "2000"},
            {"code": "ECE", "name": "Electronics and Communication Engineering", "org_id": "2000"},
            {"code": "Facilities", "name": "Facilities", "org_id": "2000"},
            {"code": "Maintenance", "name": "Maintenance", "org_id": "2000"},
        ]
        departments = [d for d in default_list if not org_id or d["org_id"] == org_id]
    return departments


def filters_from_request():
    return {
        "q": request.args.get("q", "").strip(),
        "status": request.args.get("status", "").strip().upper(),
        "department": request.args.get("department", "").strip(),
        "org_id": request.args.get("org_id", "").strip(),
        "from_date": request.args.get("from_date", "").strip(),
        "to_date": request.args.get("to_date", "").strip(),
    }


def serialize_tickets(tickets):
    rows = []
    for ticket in tickets:
        rows.append(
            {
                "Ticket ID": ticket["id"],
                "Title": ticket["title"],
                "Description": ticket["description"],
                "Category": ticket["category_name"],
                "Department": ticket["department"],
                "Created By": ticket["created_by_name"],
                "Assigned To": ticket["assigned_to_name"],
                "Status": ticket["status"],
                "Org ID": ticket["org_id"],
                "Created At": ticket["created_at"],
                "Updated At": ticket["updated_at"],
            }
        )
    return rows


def sanitize_for_csv(value):
    if value is None:
        return ""
    val_str = str(value)
    if val_str and val_str[0] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + val_str
    return val_str


def export_response(tickets, export_format, filename):
    rows = serialize_tickets(tickets)
    sanitized_rows = []
    for r in rows:
        sanitized_rows.append({k: sanitize_for_csv(v) for k, v in r.items()})
    
    fieldnames = list(rows[0].keys()) if rows else [
        "Ticket ID", "Title", "Description", "Category", "Department",
        "Created By", "Assigned To", "Status", "Org ID", "Created At", "Updated At",
    ]
    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sanitized_rows)
        return Response(buffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}.csv"})

    table_rows = "".join("<tr>" + "".join(f"<td>{escape(row.get(key, ''))}</td>" for key in fieldnames) + "</tr>" for row in sanitized_rows)
    table_html = "<table><thead><tr>" + "".join(f"<th>{key}</th>" for key in fieldnames) + f"</tr></thead><tbody>{table_rows}</tbody></table>"
    return Response(table_html, mimetype="application/vnd.ms-excel", headers={"Content-Disposition": f"attachment; filename={filename}.xls"})


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not demo_db.enabled:
            flash("MySQL demo database is not configured. Start the app with MYSQL_* environment variables.", "error")
            return render_template("login.html")

        ip = request.remote_addr
        if is_login_rate_limited(ip):
            flash("Too many failed login attempts. Please try again in 1 minute.", "error")
            return render_template("login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        # 1) Try demo_users first (existing accounts)
        user = demo_db.authenticate_user(email, password)

        # 2) If not found and email is a valid Sreenidhi domain, try teacher_info
        teacher_lookup_occurred = False
        if not user and email.endswith(("@sreenidhi.edu.in", "@suh.edu.in", "@sreegroup.edu.in")):
            # If the email already exists in demo_users, it means they have already been provisioned
            # and simply entered an incorrect password. Avoid duplicate entry error.
            if demo_db.get_user_by_email(email):
                record_login_attempt(ip)
                if live_db.enabled:
                    try:
                        with live_db.connection() as conn, conn.cursor() as cur:
                            cur.execute("SELECT 1")
                            cur.fetchone()
                    except Exception:
                        pass
                flash("Invalid email or password.", "error")
                return render_template("login.html")

            teacher_lookup_occurred = True
            teacher = live_db.lookup_teacher_by_email(email)
            if teacher and teacher.get("sap_id"):
                # Verify password against SAP ID
                sap_id = str(teacher["sap_id"]).strip()
                if password == sap_id:
                    # Auto-provision into demo_users as FACULTY
                    teacher_name = (teacher.get("name") or "User").strip()
                    teacher_dept = (teacher.get("department") or "").strip() or "General"
                    try:
                        user_id = demo_db.create_user({
                            "name": teacher_name,
                            "email": email,
                            "password": sap_id,  # stored as hash by create_user
                            "role": "FACULTY",
                            "department": teacher_dept,
                        })
                        user = {
                            "id": user_id,
                            "name": teacher_name,
                            "email": email,
                            "role": "FACULTY",
                            "department": teacher_dept,
                        }
                        log.info("Auto-provisioned teacher %s (%s) as FACULTY.", teacher_name, email)
                    except Exception as exc:
                        log.error("Failed to auto-provision teacher %s: %s", email, exc)
                        flash("Account setup failed. Please contact the administrator.", "error")
                        return render_template("login.html")

        # Normalize timing for non-Sreenidhi emails or already found users
        if not teacher_lookup_occurred:
            if live_db.enabled:
                try:
                    with live_db.connection() as conn, conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        cur.fetchone()
                except Exception:
                    pass

        if not user:
            record_login_attempt(ip)
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        if ip in LOGIN_ATTEMPTS:
            del LOGIN_ATTEMPTS[ip]

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["role"] = user["role"]
        session["department"] = user["department"]
        session["org_id"] = user.get("org_id") or resolve_user_org(email, user["department"])
        return redirect(url_for(route_for_role(user["role"])))

    if current_user():
        return redirect(url_for(route_for_role(session["role"])))
    return render_template("login.html")


@app.route("/user/dashboard")
@role_required("FACULTY")
def user_dashboard():
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    tickets = demo_db.list_tickets(user, scope="own")
    return render_template("user_dashboard.html", summary=summary, tickets=tickets[:5], **page_context("User"))


@app.route("/user/my-tickets")
@role_required("FACULTY")
def my_tickets():
    user = current_user()
    tickets = demo_db.list_tickets(user, scope="own", filters=filters_from_request())
    return render_template("my_tickets.html", tickets=tickets, filters=filters_from_request(), **page_context("My Tickets"))


@app.route("/tickets/create", methods=["GET", "POST"])
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def create_ticket_for_role():
    user = current_user()
    user_dept = (user.get("department") or "").strip()

    all_depts = live_departments(user["org_id"])
    matched_dept = next((d for d in all_depts if d["code"].lower() == user_dept.lower() or d["name"].lower() == user_dept.lower()), None)
    user_dept_code = matched_dept["code"] if matched_dept else user_dept
    user_dept_name = matched_dept["name"] if matched_dept else user_dept

    if request.method == "POST":
        category_id = safe_int(request.form.get("category_id", "0"))
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location_id = safe_int(request.form.get("location_id", "0")) or None
        if not category_id:
            flash("Category is required.", "error")
            return redirect(url_for("create_ticket_for_role"))
        if not description:
            flash("Description is required.", "error")
            return redirect(url_for("create_ticket_for_role"))
        if title and len(title) > 180:
            flash("Title cannot exceed 180 characters.", "error")
            return redirect(url_for("create_ticket_for_role"))
        if len(description) > 5000:
            flash("Description cannot exceed 5000 characters.", "error")
            return redirect(url_for("create_ticket_for_role"))

        # Server-side validation: derive department from user session and validate category
        category = demo_db.get_category(category_id)
        if not category:
            flash("Selected category does not exist.", "error")
            return redirect(url_for("create_ticket_for_role"))

        cat_dept = (category.get("department") or "").strip().lower()
        allowed_depts = {user_dept.lower(), user_dept_code.lower(), user_dept_name.lower()}
        if user["role"] not in ("SUPER_ADMIN", "ADMIN") and cat_dept not in allowed_depts:
            flash("You can only create tickets for your assigned department.", "error")
            return redirect(url_for("create_ticket_for_role"))

        org_id = user["org_id"]
        demo_db.create_ticket(title=title, description=description, category_id=category_id, created_by=user["id"], org_id=org_id, location_id=location_id)
        flash("Ticket created and auto-assigned to the mapped Concerned Authority.", "success")
        return redirect(url_for(route_for_role(user["role"])))

    categories = demo_db.list_categories(department=user_dept_code, org_id=user["org_id"], active_only=True)
    if not categories and user_dept_name != user_dept_code:
        categories = demo_db.list_categories(department=user_dept_name, org_id=user["org_id"], active_only=True)
    if not categories and user["role"] in ("SUPER_ADMIN", "ADMIN"):
        categories = demo_db.list_categories(org_id=user["org_id"], active_only=True)

    locations = live_db.fetch_locations()
    return render_template(
        "create_ticket.html",
        categories=categories,
        locations=locations,
        user_dept_code=user_dept_code,
        user_dept_name=user_dept_name,
        current_user_dept=user_dept,
        departments=all_depts,
        **page_context("Create Ticket")
    )


@app.route("/api/locations")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def api_locations():
    """JSON endpoint returning locations grouped by block → floor → rooms."""
    locations = live_db.fetch_locations()
    grouped = {}
    for loc in locations:
        block = loc.get("block", "Unknown")
        floor = loc.get("floor", "Unknown")
        if block not in grouped:
            grouped[block] = {}
        if floor not in grouped[block]:
            grouped[block][floor] = []
        grouped[block][floor].append({
            "id": loc["id"],
            "room_no": loc.get("room_no", ""),
            "name": loc.get("name", ""),
        })
    return jsonify(grouped)


# Org label helper
ORG_LABELS = {"2000": "SNIST", "3000": "SNU"}


@app.route("/super-admin/dashboard")
@role_required("SUPER_ADMIN")
def super_admin_dashboard():
    user = current_user()
    org_id = user["org_id"]
    org_label = ORG_LABELS.get(org_id, org_id)
    summary = demo_db.dashboard_summary(user)
    return render_template(
        "management_dashboard.html",
        summary=summary,
        highlights=demo_db.hod_overview(org_id=org_id),
        dept_stats=demo_db.ticket_stats_by_department(org_id=org_id),
        cat_stats=demo_db.ticket_stats_by_category(org_id=org_id),
        departments=live_departments(org_id),
        page_title=f"{org_label} Super Admin Dashboard",
        kicker="RBAC Control",
        page_heading=f"{org_label} Super Admin overview",
        page_description=f"Full control over users, roles, departments, and ticket visibility for {org_label}.",
        highlight_title="HOD overview",
        highlight_note="HOD rows below are powered by demo users and department-level ticket/category counts.",
        primary_cta=("user_management", "Manage Users"),
        secondary_cta=("super_admin_all_tickets", "View All Tickets"),
        **page_context("Super Admin"),
    )


@app.route("/admin/dashboard")
@role_required("ADMIN")
def admin_dashboard():
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    users = demo_db.list_users()
    highlights = [
        {
            "name": item["name"],
            "department": item["department"],
            "email": item["email"],
            "category_count": 0,
            "ticket_count": 0,
        }
        for item in users[:6]
    ]
    return render_template(
        "management_dashboard.html",
        summary=summary,
        highlights=highlights,
        departments=live_departments(user["org_id"]),
        page_title="Admin Dashboard",
        kicker="Administration",
        page_heading="Admin panel",
        page_description="Create, edit, and delete demo users. Assign departments and HOD roles safely on demo tables.",
        highlight_title="Recent users",
        highlight_note="Admins manage users and roles, but ticket assignment remains automatic via category-to-CA mapping.",
        primary_cta=("user_management", "Open User Management"),
        secondary_cta=("admin_all_tickets", "View Tickets"),
        **page_context("Admin"),
    )


@app.route("/hod/dashboard")
@role_required("HOD")
def hod_dashboard():
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    highlights = demo_db.list_categories(department=user["department"])
    return render_template(
        "management_dashboard.html",
        summary=summary,
        highlights=highlights,
        page_title="HOD Dashboard",
        kicker="Department Control",
        page_heading=f"{user['department']} HOD dashboard",
        page_description="Manage CA mappings for your department and monitor department-specific tickets.",
        highlight_title="Category to CA mapping",
        highlight_note="HOD manages CAs by mapping categories to Concerned Authorities in demo_categories.",
        primary_cta=("management_category", "Manage CA Mapping"),
        secondary_cta=("hod_all_tickets", "View Department Tickets"),
        **page_context("HOD"),
    )


def render_all_tickets(role_title, endpoint_name):
    user = current_user()
    filters = filters_from_request()
    tickets = demo_db.list_tickets(user, scope="all", filters=filters)
    departments = live_departments()
    return render_template(
        "management_all_tickets.html",
        tickets=tickets,
        filters=filters,
        departments=departments,
        export_scope=endpoint_name,
        **page_context(role_title),
    )


@app.route("/super-admin/all-tickets")
@role_required("SUPER_ADMIN")
def super_admin_all_tickets():
    return render_all_tickets("Super Admin", "super_admin_all_tickets")


@app.route("/admin/all-tickets")
@role_required("ADMIN")
def admin_all_tickets():
    return render_all_tickets("Admin", "admin_all_tickets")


@app.route("/hod/all-tickets")
@role_required("HOD")
def hod_all_tickets():
    return render_all_tickets("HOD", "hod_all_tickets")


@app.route("/authority/tickets")
@role_required("CA")
def authority_tickets():
    user = current_user()
    filters = filters_from_request()
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    own_tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    return render_template(
        "authority_tickets.html",
        assigned_tickets=assigned_tickets,
        own_tickets=own_tickets,
        filters=filters,
        **page_context("Concerned Authority"),
    )


@app.route("/ca/report")
@role_required("CA")
def ca_report():
    user = current_user()
    filters = filters_from_request()
    filters["status"] = "RESOLVED"
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    
    for t in assigned_tickets:
        if t.get("created_at") and t.get("updated_at"):
            try:
                created = datetime.fromisoformat(t["created_at"])
                updated = datetime.fromisoformat(t["updated_at"])
                diff = updated - created
                days = diff.days
                hours, remainder = divmod(diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                
                parts = []
                if days > 0: parts.append(f"{days}d")
                if hours > 0: parts.append(f"{hours}h")
                if minutes > 0: parts.append(f"{minutes}m")
                t["time_taken"] = " ".join(parts) if parts else "< 1m"
            except Exception:
                t["time_taken"] = "N/A"
        else:
            t["time_taken"] = "N/A"

    return render_template(
        "ca_report.html",
        resolved_tickets=assigned_tickets,
        filters=filters,
        **page_context("CA Report"),
    )


@app.route("/tickets/<int:ticket_id>")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def ticket_detail(ticket_id):
    user = current_user()
    ticket = demo_db.get_ticket(ticket_id)
    if not ticket:
        flash("Ticket not found.", "error")
        return redirect(url_for("user_dashboard" if user["role"] == "FACULTY" else "authority_tickets"))
    # Access check: creator, assigned CA, same department HOD, or admin/super_admin
    allowed = False
    if user["role"] in ("SUPER_ADMIN", "ADMIN"):
        allowed = True
    elif user["role"] == "HOD" and ticket["department"] == user["department"]:
        allowed = True
    elif ticket["created_by_email"].lower() == user["email"].lower():
        allowed = True
    elif ticket["assigned_to_email"].lower() == user["email"].lower():
        allowed = True
    if not allowed or ticket["org_id"] != user["org_id"]:
        flash("You do not have access to this ticket.", "error")
        return redirect(url_for("user_dashboard" if user["role"] == "FACULTY" else "authority_tickets"))
    activity = demo_db.list_ticket_activity(ticket_id)
    # Determine next allowed transitions for status action
    next_statuses = list(demo_db.ALLOWED_TRANSITIONS.get(ticket["status"], set()))
    # CA or SUPER_ADMIN can update ticket status
    can_update = user["role"] == "SUPER_ADMIN" or (user["role"] == "CA" and ticket["assigned_to_email"].lower() == user["email"].lower())
    # Ticket creator can REOPEN a resolved ticket
    can_reopen = (
        ticket["status"] == "RESOLVED"
        and ticket["created_by_email"].lower() == user["email"].lower()
    )
    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        activity=activity,
        next_statuses=next_statuses,
        can_update=can_update,
        can_reopen=can_reopen,
        **page_context("Ticket #" + str(ticket_id)),
    )


@app.route("/authority/update-status/<int:ticket_id>", methods=["POST"])
@role_required("CA", "SUPER_ADMIN")
def authority_update_status(ticket_id):
    user = current_user()
    status = request.form.get("status", "").strip().upper()
    remarks = request.form.get("remarks", "").strip()
    time_taken = request.form.get("time_taken", "").strip()
    attachment = request.files.get("attachment")

    if status not in {"PENDING", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "REOPENED"}:
        flash("Invalid status selected.", "error")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))
    if status == "RESOLVED" and not remarks:
        flash("Resolution remarks are required.", "error")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))

    attachment_path = ""
    if attachment and attachment.filename:
        if not allowed_file(attachment.filename) or not verify_file_signature(attachment):
            flash(f"File type not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket_id))
        attachment.seek(0, 2)
        size = attachment.tell()
        attachment.seek(0)
        if size > MAX_UPLOAD_SIZE:
            flash(f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.", "error")
            return redirect(url_for("ticket_detail", ticket_id=ticket_id))
        safe_name = secure_filename(attachment.filename)
        attachment_name = f"{ticket_id}-{int(datetime.now().timestamp())}-{safe_name}"
        attachment.save(str(UPLOAD_DIR / attachment_name))
        attachment_path = attachment_name

    try:
        demo_db.update_ticket_status(ticket_id, actor=user, status=status, remarks=remarks, time_taken=time_taken, attachment_path=attachment_path)
        flash("Ticket updated successfully.", "success")
    except PermissionError as exc:
        flash("You do not have access to that page.", "error")
        return redirect(url_for(route_for_role(user["role"])))
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/tickets/<int:ticket_id>/reopen", methods=["POST"])
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def reopen_ticket(ticket_id):
    """Allow the ticket creator to reopen a resolved ticket."""
    user = current_user()
    remarks = request.form.get("remarks", "").strip()
    if not remarks:
        flash("Please provide a reason for reopening.", "error")
        return redirect(url_for("ticket_detail", ticket_id=ticket_id))
    try:
        demo_db.update_ticket_status(ticket_id, actor=user, status="REOPENED", remarks=remarks)
        flash("Ticket has been reopened.", "success")
    except PermissionError as exc:
        flash(str(exc), "error")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("ticket_detail", ticket_id=ticket_id))


@app.route("/user-management", methods=["GET", "POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def user_management():
    user = current_user()
    if request.method == "POST":
        role = request.form.get("role", "").strip().upper()
        if user["role"] == "HOD":
            if role not in ("CA", "FACULTY"):
                flash("Access denied: HOD can only create CA or FACULTY users.", "error")
                return redirect(url_for("user_management"))
            if role == "CA":
                selected_depts = [d.strip() for d in request.form.getlist("department") if d.strip()]
                if user["department"] not in selected_depts:
                    selected_depts.append(user["department"])
                department = ",".join(selected_depts)
            else:
                department = user["department"]
        else:
            if user["role"] != "SUPER_ADMIN" and role == "SUPER_ADMIN":
                flash("Access denied: Only SUPER_ADMIN can create SUPER_ADMIN users.", "error")
                return redirect(url_for("user_management"))
            if role == "CA":
                department = ",".join([d.strip() for d in request.form.getlist("department") if d.strip()])
            else:
                department = request.form.get("department", "").strip()

        payload = {
            "name": request.form.get("name", "").strip(),
            "email": request.form.get("email", "").strip().lower(),
            "password": request.form.get("password", "").strip() or "123",
            "role": role,
            "department": department,
        }
        if not all([payload["name"], payload["email"], payload["role"], payload["department"]]):
            flash("All user fields are required.", "error")
            return redirect(url_for("user_management"))
        if len(payload["name"]) > 120:
            flash("Name cannot exceed 120 characters.", "error")
            return redirect(url_for("user_management"))
        if len(payload["email"]) > 190:
            flash("Email cannot exceed 190 characters.", "error")
            return redirect(url_for("user_management"))
        if not is_valid_email(payload["email"]):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("user_management"))
        
        # Enforce that the user resolves to the admin's organization
        target_org = resolve_user_org(payload["email"], payload["department"])
        if target_org != user["org_id"]:
            flash(f"Access denied: User details do not resolve to your organization ({user['org_id']}).", "error")
            return redirect(url_for("user_management"))

        existing = demo_db.list_users(search=payload["email"])
        if any(u["email"].lower() == payload["email"] for u in existing):
            flash(f"A user with email '{payload['email']}' already exists.", "error")
            return redirect(url_for("user_management"))
        demo_db.create_user(payload)
        demo_db.log_audit_event(
            "USER_CREATED", user["id"], user["org_id"],
            target_type="user", target_id=None,
            details={"email": payload["email"], "role": payload["role"], "department": payload["department"]},
        )
        flash("Demo user created successfully.", "success")
        return redirect(url_for("user_management"))

    search = request.args.get("q", "").strip()
    roles_filter = [r.upper() for r in request.args.getlist("role") if r.strip()]
    department = request.args.get("department", "").strip() or None
    
    if user["role"] == "HOD":
        department = user["department"]
        roles_list = ["CA", "FACULTY"]
    else:
        roles_list = list(ROLE_MAP.keys()) if user["role"] == "SUPER_ADMIN" else [r for r in ROLE_MAP.keys() if r != "SUPER_ADMIN"]

    role_arg = roles_filter if len(roles_filter) > 1 else (roles_filter[0] if roles_filter else None)
    users = demo_db.list_users(role=role_arg, department=department, search=search, org_id=user["org_id"])
    if user["role"] == "HOD":
        users = [u for u in users if u["role"] in ("CA", "FACULTY")]
    departments = live_departments(user["org_id"])
    return render_template(
        "user_management.html",
        users=users,
        departments=departments,
        filters={"q": search, "role": roles_filter[0] if len(roles_filter) == 1 else "", "roles": roles_filter, "department": department or ""},
        roles=roles_list,
        **page_context("User Management"),
    )


@app.route("/user-management/<int:user_id>/update", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def update_user(user_id):
    user = current_user()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        flash("User not found.", "error")
        return redirect(url_for("user_management"))
        
    # Check if the user belongs to the admin's organization
    target_org = resolve_user_org(target_user["email"], target_user["department"])
    if target_org != user["org_id"]:
        flash("Access denied: User belongs to a different organization.", "error")
        return redirect(url_for("user_management"))

    if user["role"] == "HOD":
        target_depts = [d.strip() for d in target_user["department"].split(",")]
        if user["department"] not in target_depts:
            flash("Access denied: You can only modify users in your own department.", "error")
            return redirect(url_for("user_management"))
        if target_user["role"] not in ("CA", "FACULTY"):
            flash("Access denied: You can only modify CA or FACULTY users.", "error")
            return redirect(url_for("user_management"))
        
        role = request.form.get("role", "").strip().upper()
        if role not in ("CA", "FACULTY"):
            flash("Access denied: You can only assign CA or FACULTY role.", "error")
            return redirect(url_for("user_management"))
            
        if role == "CA":
            selected_depts = [d.strip() for d in request.form.getlist("department") if d.strip()]
            if user["department"] not in selected_depts:
                selected_depts.append(user["department"])
            department = ",".join(selected_depts)
        else:
            department = user["department"]
    else:
        role = request.form.get("role", "").strip().upper()
        if user["role"] != "SUPER_ADMIN":
            if target_user["role"] == "SUPER_ADMIN":
                flash("Access denied: Cannot modify SUPER_ADMIN users.", "error")
                return redirect(url_for("user_management"))
            if role == "SUPER_ADMIN":
                flash("Access denied: Cannot assign SUPER_ADMIN role.", "error")
                return redirect(url_for("user_management"))

        if role == "CA":
            department = ",".join([d.strip() for d in request.form.getlist("department") if d.strip()])
        else:
            department = request.form.get("department", "").strip()

    password = request.form.get("password", "").strip()
    payload = {
        "name": request.form.get("name", "").strip() or target_user["name"],
        "email": request.form.get("email", "").strip().lower() or target_user["email"],
        "role": role or target_user["role"],
        "department": department or target_user["department"],
    }
    if password:
        payload["password"] = password
    if not all([payload["name"], payload["email"], payload["role"], payload["department"]]):
        flash("All user fields are required.", "error")
        return redirect(url_for("user_management"))
    if len(payload["name"]) > 120:
        flash("Name cannot exceed 120 characters.", "error")
        return redirect(url_for("user_management"))
    if len(payload["email"]) > 190:
        flash("Email cannot exceed 190 characters.", "error")
        return redirect(url_for("user_management"))
    if not is_valid_email(payload["email"]):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("user_management"))

    # Enforce that the updated details still resolve to the admin's organization
    new_org = resolve_user_org(payload["email"], payload["department"])
    if new_org != user["org_id"]:
        flash(f"Access denied: Updated details do not resolve to your organization ({user['org_id']}).", "error")
        return redirect(url_for("user_management"))

    demo_db.update_user(user_id, payload)
    flash("Demo user updated.", "success")
    return redirect(url_for("user_management"))


@app.route("/user-management/<int:user_id>/delete", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def delete_user(user_id):
    user = current_user()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        flash("User not found.", "error")
        return redirect(url_for("user_management"))
        
    target_org = resolve_user_org(target_user["email"], target_user["department"])
    if target_org != user["org_id"]:
        flash("Access denied: User belongs to a different organization.", "error")
        return redirect(url_for("user_management"))

    if user["role"] == "HOD":
        target_depts = [d.strip() for d in target_user["department"].split(",")]
        if user["department"] not in target_depts:
            flash("Access denied: You can only delete users in your own department.", "error")
            return redirect(url_for("user_management"))
        if target_user["role"] not in ("CA", "FACULTY"):
            flash("Access denied: You can only delete CA or FACULTY users.", "error")
            return redirect(url_for("user_management"))
    else:
        if user["role"] != "SUPER_ADMIN" and target_user["role"] == "SUPER_ADMIN":
            flash("Access denied: Cannot delete SUPER_ADMIN users.", "error")
            return redirect(url_for("user_management"))

    try:
        demo_db.delete_user(user_id)
        flash("Demo user deleted.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("user_management"))


def check_and_promote_ca(ca_id, target_dept, actor_id, org_id):
    ca_user = demo_db.get_user(ca_id)
    if ca_user:
        target_depts = [d.strip() for d in ca_user["department"].split(",") if d.strip()]
        dept_updated = False
        if target_dept not in target_depts:
            target_depts.append(target_dept)
            dept_updated = True
        
        if ca_user["role"] == "FACULTY" or dept_updated:
            new_role = "CA"
            new_dept_str = ",".join(target_depts)
            demo_db.update_user(ca_id, {
                "name": ca_user["name"],
                "email": ca_user["email"],
                "role": new_role,
                "department": new_dept_str
            })
            if ca_user["role"] == "FACULTY":
                demo_db.log_audit_event(
                    "CA_PROMOTED", actor_id, org_id,
                    target_type="user", target_id=ca_id,
                    details={"promoted_name": ca_user["name"], "department": target_dept},
                )
                flash(f"Promoted {ca_user['name']} to Concerned Authority for {target_dept}.", "success")
            else:
                flash(f"Updated Concerned Authority department mapping for {ca_user['name']}.", "success")


def resolve_and_promote_ca(assigned_ca_id_str, target_dept, actor_id, org_id):
    if assigned_ca_id_str.startswith("ref:"):
        ref_email = assigned_ca_id_str.split(":", 1)[1]
        teacher = live_db.lookup_teacher_by_email(ref_email)
        if not teacher:
            raise ValueError("Selected authority not found in reference directory.")
        
        sap_id = str(teacher.get("sap_id", "123")).strip()
        existing = demo_db.get_user_by_email(teacher["email"])
        if existing:
            check_and_promote_ca(existing["id"], target_dept, actor_id, org_id)
            return existing["id"]
            
        new_user_id = demo_db.create_user({
            "name": teacher["name"],
            "email": teacher["email"],
            "password": sap_id,
            "role": "CA",
            "department": target_dept
        })
        demo_db.log_audit_event(
            "CA_PROMOTED", actor_id, org_id,
            target_type="user", target_id=new_user_id,
            details={"promoted_name": teacher["name"], "department": target_dept},
        )
        flash(f"Promoted reference user {teacher['name']} to Concerned Authority for {target_dept}.", "success")
        return new_user_id
    else:
        ca_id = safe_int(assigned_ca_id_str)
        check_and_promote_ca(ca_id, target_dept, actor_id, org_id)
        return ca_id


@app.route("/management/category-management", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN")
def management_category():
    user = current_user()
    if request.method == "POST":
        payload = {
            "category_name": request.form.get("category_name", "").strip(),
            "department": user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip(),
        }
        if not payload["category_name"] or not payload["department"]:
            flash("Category name and department are required.", "error")
            return redirect(url_for("management_category"))
        # Duplicate check / reactivate check
        if demo_db.category_exists(payload["category_name"], payload["department"]):
            cats = demo_db.list_categories(department=payload["department"])
            matching = [c for c in cats if c["category_name"].lower() == payload["category_name"].lower()]
            if matching and matching[0]["is_active"] == 0:
                demo_db.toggle_category_status(matching[0]["id"], 1)
                flash(f"Re-activated category '{matching[0]['category_name']}' for {payload['department']}.", "success")
            else:
                flash(f"A category '{payload['category_name']}' already exists in {payload['department']}.", "error")
            return redirect(url_for("management_category"))
        
        payload["assigned_ca_id"] = user["id"]  # set HOD/Admin as default placeholder CA to satisfy DB FK constraint
        demo_db.create_category(payload)
        flash("Category created successfully.", "success")
        return redirect(url_for("management_category"))

    # GET: support search/filter
    department = user["department"] if user["role"] == "HOD" else request.args.get("department", "").strip() or None
    search = request.args.get("q", "").strip()
    show_inactive = request.args.get("show_inactive") == "true"
    categories = demo_db.list_categories(department=department, search=search, org_id=user["org_id"], active_only=not show_inactive)

    return render_template(
        "category_management.html",
        categories=categories,
        departments=live_departments(user["org_id"]),
        selected_department=department or "",
        show_inactive=show_inactive,
        filters={"q": search, "department": department or ""},
        **page_context("Category Management"),
    )


@app.route("/management/category-management/<int:category_id>/update", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN")
def update_category(category_id):
    user = current_user()
    existing_cat = demo_db.get_category(category_id)
    if not existing_cat:
        flash("Category not found.", "error")
        return redirect(url_for("management_category"))

    # HOD can only update categories in their department
    if user["role"] == "HOD":
        if existing_cat["department"] != user["department"]:
            flash("You can only modify categories in your own department.", "error")
            return redirect(url_for("management_category"))

    payload = {
        "category_name": request.form.get("category_name", "").strip(),
        "department": user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip(),
        "assigned_ca_id": existing_cat["assigned_ca_id"],
    }
    if not payload["category_name"] or not payload["department"]:
        flash("Category name and department are required.", "error")
        return redirect(url_for("management_category"))

    # Duplicate check (exclude self)
    if demo_db.category_exists(payload["category_name"], payload["department"], exclude_id=category_id):
        flash(f"A category '{payload['category_name']}' already exists in {payload['department']}.", "error")
        return redirect(url_for("management_category"))
        
    demo_db.update_category(category_id, payload)
    flash("Category updated successfully.", "success")
    return redirect(url_for("management_category"))


@app.route("/management/category-management/<int:category_id>/delete", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN")
def delete_category(category_id):
    user = current_user()
    # HOD can only delete categories in their department
    if user["role"] == "HOD":
        existing_cat = demo_db.get_category(category_id)
        if not existing_cat or existing_cat["department"] != user["department"]:
            flash("You can only delete categories in your own department.", "error")
            return redirect(url_for("management_category"))
    try:
        demo_db.delete_category(category_id)
        flash("Category deleted successfully.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("management_category"))


@app.route("/management/category-management/<int:category_id>/toggle", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN")
def toggle_category(category_id):
    user = current_user()
    existing_cat = demo_db.get_category(category_id)
    if not existing_cat:
        flash("Category not found.", "error")
        return redirect(url_for("management_category"))

    # HOD can only modify categories in their department
    if user["role"] == "HOD" and existing_cat["department"] != user["department"]:
        flash("You can only modify categories in your own department.", "error")
        return redirect(url_for("management_category"))

    # Toggle the active state
    new_state = 0 if existing_cat.get("is_active", 1) == 1 else 1
    try:
        demo_db.toggle_category_status(category_id, new_state)
        status_str = "activated" if new_state else "deactivated"
        flash(f"Category '{existing_cat['category_name']}' has been {status_str}.", "success")
    except Exception as exc:
        flash(f"Failed to toggle category status: {exc}", "error")
    return redirect(url_for("management_category"))


@app.route("/tickets/export/<scope>.<export_format>")
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "FACULTY")
def export_tickets(scope, export_format):
    user = current_user()
    filters = filters_from_request()
    if export_format not in {"csv", "xls"}:
        flash("Unsupported export format.", "error")
        return redirect(url_for(route_for_role(user["role"])))

    # Enforce per-role export scope
    role = user["role"]
    if role == "FACULTY":
        # Faculty can only export their own tickets
        tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    elif role == "CA":
        if scope == "authority_own":
            tickets = demo_db.list_tickets(user, scope="own", filters=filters)
        else:
            tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    elif role == "HOD":
        # HOD can only export department-scoped tickets
        tickets = demo_db.list_tickets(user, scope="all", filters=filters)
    else:
        # SUPER_ADMIN / ADMIN – full access
        tickets = demo_db.list_tickets(user, scope="all", filters=filters)
    return export_response(tickets, export_format, f"{scope}-{datetime.now().strftime('%Y%m%d')}")


def user_json(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "email": row["email"],
        "role": row["role"],
        "department": row["department"],
        "created_at": str(row["created_at"]),
    }


@app.route("/api/live/departments")
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_live_departments():
    user = current_user()
    return jsonify(live_departments(user["org_id"]))
 
 
@app.route("/api/live/users")
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_live_users():
    user = current_user()
    search = request.args.get("q", "").strip()
    department = user["department"] if user["role"] == "HOD" else request.args.get("department", "").strip() or None
    rows = live_db.fetch_reference_users(search=search, department=department, limit=100, org_id=user["org_id"]) if live_db.enabled else []
    return jsonify(rows)
 
 
@app.route("/api/demo/users", methods=["GET", "POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_demo_users():
    user = current_user()
    if request.method == "GET":
        department = user["department"] if user["role"] == "HOD" else request.args.get("department", "").strip() or None
        users = demo_db.list_users(
            role=request.args.get("role", "").strip().upper() or None,
            department=department,
            search=request.args.get("q", "").strip(),
            org_id=user["org_id"],
        )
        if user["role"] == "HOD":
            users = [u for u in users if u["role"] in ("CA", "FACULTY")]
        return jsonify([user_json(row) for row in users])
 
    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Request body is required."}), 400
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    role = (payload.get("role") or "").strip().upper()
    department = (payload.get("department") or "").strip()
    if not all([name, email, role, department]):
        return jsonify({"error": "name, email, role, and department are required."}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Invalid email format."}), 400

    if user["role"] == "HOD":
        if role not in ("CA", "FACULTY"):
            return jsonify({"error": "Access denied: HOD can only create CA or FACULTY users."}), 403
        if role == "CA":
            depts = [d.strip() for d in department.split(",")]
            if user["department"] not in depts:
                return jsonify({"error": f"Access denied: CA must belong to your department ({user['department']})."}), 403
        else:
            if department != user["department"]:
                return jsonify({"error": f"Access denied: User must belong to your department ({user['department']})."}), 403
    else:
        if user["role"] != "SUPER_ADMIN" and role == "SUPER_ADMIN":
            return jsonify({"error": "Access denied: Only SUPER_ADMIN can create SUPER_ADMIN users."}), 403

    # Enforce organization scoping on creation
    target_org = resolve_user_org(email, department)
    if target_org != user["org_id"]:
        return jsonify({"error": f"Access denied: User details do not resolve to your organization ({user['org_id']})."}), 403

    existing = demo_db.list_users(search=email)
    if any(u["email"].lower() == email for u in existing):
        return jsonify({"error": f"A user with email '{email}' already exists."}), 409
    user_id = demo_db.create_user(
        {
            "name": name,
            "email": email,
            "password": (payload.get("password") or "123").strip(),
            "role": role,
            "department": department,
        }
    )
    return jsonify({"id": user_id}), 201
 
 
@app.route("/api/demo/users/<int:user_id>", methods=["PUT", "DELETE"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_demo_user_detail(user_id):
    user = current_user()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404
    target_org = resolve_user_org(target_user["email"], target_user["department"])
    if target_org != user["org_id"]:
        return jsonify({"error": "Access denied: User belongs to a different organization."}), 403

    if user["role"] == "HOD":
        target_depts = [d.strip() for d in target_user["department"].split(",")]
        if user["department"] not in target_depts:
            return jsonify({"error": "Access denied: You can only modify users in your own department."}), 403
        if target_user["role"] not in ("CA", "FACULTY"):
            return jsonify({"error": "Access denied: You can only modify CA or FACULTY users."}), 403
    else:
        if user["role"] != "SUPER_ADMIN" and target_user["role"] == "SUPER_ADMIN":
            return jsonify({"error": "Access denied: Cannot modify/delete SUPER_ADMIN users."}), 403

    if request.method == "DELETE":
        try:
            demo_db.delete_user(user_id)
            return "", 204
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
 
    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Request body is required."}), 400
    name = (payload.get("name") or "").strip()
    email = (payload.get("email") or "").strip().lower()
    role = (payload.get("role") or "").strip().upper()
    department = (payload.get("department") or "").strip()
    if not all([name, email, role, department]):
        return jsonify({"error": "name, email, role, and department are required."}), 400
    if not is_valid_email(email):
        return jsonify({"error": "Invalid email format."}), 400

    if user["role"] == "HOD":
        if role not in ("CA", "FACULTY"):
            return jsonify({"error": "You can only assign CA or FACULTY role."}), 403
        if role == "CA":
            depts = [d.strip() for d in department.split(",")]
            if user["department"] not in depts:
                return jsonify({"error": f"Access denied: CA must belong to your department ({user['department']})."}), 403
        else:
            if department != user["department"]:
                return jsonify({"error": f"Access denied: User must belong to your department ({user['department']})."}), 403
    else:
        if user["role"] != "SUPER_ADMIN" and role == "SUPER_ADMIN":
            return jsonify({"error": "Access denied: Cannot assign SUPER_ADMIN role."}), 403
 
    # Enforce that updated details still resolve to the admin's organization
    new_org = resolve_user_org(email, department)
    if new_org != user["org_id"]:
        return jsonify({"error": f"Access denied: Updated details do not resolve to your organization ({user['org_id']})."}), 403

    update_payload = {
        "name": name,
        "email": email,
        "role": role,
        "department": department,
    }
    pw = (payload.get("password") or "").strip()
    if pw:
        update_payload["password"] = pw
    demo_db.update_user(user_id, update_payload)
    return "", 204


@app.route("/api/demo/categories", methods=["GET", "POST"])
@role_required("SUPER_ADMIN", "HOD")
def api_demo_categories():
    user = current_user()
    if request.method == "GET":
        department = user["department"] if user["role"] == "HOD" else request.args.get("department", "").strip() or None
        return jsonify(demo_db.list_categories(department=department, org_id=user["org_id"]))

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Request body is required."}), 400
    category_name = (payload.get("category_name") or "").strip()
    assigned_ca_id = safe_int(payload.get("assigned_ca_id"))
    department = user["department"] if user["role"] == "HOD" else (payload.get("department") or "").strip()
    if not all([category_name, department, assigned_ca_id]):
        return jsonify({"error": "category_name, department, and assigned_ca_id are required."}), 400

    # Enforce department is in user's organization
    allowed_depts = {d["code"] for d in live_departments(user["org_id"])}
    if department not in allowed_depts:
        return jsonify({"error": "Access denied: Department does not belong to your organization."}), 403

    category_id = demo_db.create_category(
        {
            "category_name": category_name,
            "department": department,
            "assigned_ca_id": assigned_ca_id,
        }
    )
    return jsonify({"id": category_id}), 201


@app.route("/api/demo/categories/<int:category_id>", methods=["PUT", "DELETE"])
@role_required("SUPER_ADMIN", "HOD")
def api_demo_category_detail(category_id):
    user = current_user()
    existing_cat = demo_db.get_category(category_id)
    if not existing_cat:
        return jsonify({"error": "Category not found."}), 404

    # Enforce department of category belongs to user's org
    allowed_depts = {d["code"] for d in live_departments(user["org_id"])}
    if existing_cat["department"] not in allowed_depts:
        return jsonify({"error": "Access denied: Category belongs to a different organization."}), 403

    if request.method == "DELETE":
        try:
            demo_db.delete_category(category_id)
            return "", 204
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Request body is required."}), 400
    category_name = (payload.get("category_name") or "").strip()
    assigned_ca_id = safe_int(payload.get("assigned_ca_id"))
    department = user["department"] if user["role"] == "HOD" else (payload.get("department") or "").strip()
    if not all([category_name, department, assigned_ca_id]):
        return jsonify({"error": "category_name, department, and assigned_ca_id are required."}), 400

    # Enforce new department is also in user's organization
    if department not in allowed_depts:
        return jsonify({"error": "Access denied: New department does not belong to your organization."}), 403

    demo_db.update_category(
        category_id,
        {
            "category_name": category_name,
            "department": department,
            "assigned_ca_id": assigned_ca_id,
        },
    )
    return "", 204


@app.route("/api/demo/tickets", methods=["GET", "POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "FACULTY")
def api_demo_tickets():
    user = current_user()
    if request.method == "GET":
        scope = request.args.get("scope", "all")
        if user["role"] == "FACULTY":
            scope = "own"
        elif user["role"] == "CA" and scope not in {"assigned", "own"}:
            scope = "assigned"
        elif user["role"] in {"HOD"}:
            scope = "all"
        return jsonify(demo_db.list_tickets(user, scope=scope, filters=filters_from_request()))

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Request body is required."}), 400
    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    category_id = safe_int(payload.get("category_id"))
    if not all([title, description, category_id]):
        return jsonify({"error": "title, description, and category_id are required."}), 400
    if len(title) > 180:
        return jsonify({"error": "title cannot exceed 180 characters."}), 400
    if len(description) > 5000:
        return jsonify({"error": "description cannot exceed 5000 characters."}), 400
    org_id = live_db.resolve_org_id(email=user["email"], department=user["department"])
    ticket_id = demo_db.create_ticket(
        title=title,
        description=description,
        category_id=category_id,
        created_by=user["id"],
        org_id=org_id,
    )
    return jsonify({"id": ticket_id}), 201


@app.route("/api/demo/tickets/<int:ticket_id>", methods=["GET", "PUT"])
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def api_demo_ticket_detail(ticket_id):
    user = current_user()
    ticket = demo_db.get_ticket(ticket_id)
    if not ticket:
        return jsonify({"error": "Ticket not found."}), 404

    # Access check: creator, assigned CA, same department HOD, or admin/super_admin
    allowed = False
    if user["role"] in ("SUPER_ADMIN", "ADMIN"):
        allowed = True
    elif user["role"] == "HOD" and ticket["department"] == user["department"]:
        allowed = True
    elif ticket["created_by_email"].lower() == user["email"].lower():
        allowed = True
    elif ticket["assigned_to_email"].lower() == user["email"].lower():
        allowed = True

    if not allowed or ticket["org_id"] != user["org_id"]:
        return jsonify({"error": "Access denied: You do not have access to this ticket."}), 403

    if request.method == "GET":
        # Serialize datetime fields
        result = dict(ticket)
        for k in ("created_at", "updated_at"):
            if result.get(k):
                result[k] = result[k].isoformat()
        result["activity"] = []
        for a in demo_db.list_ticket_activity(ticket_id):
            entry = dict(a)
            if entry.get("created_at"):
                entry["created_at"] = entry["created_at"].isoformat()
            result["activity"].append(entry)
        return jsonify(result)

    # PUT: update status
    payload = request.get_json(force=True)
    if not payload or not (payload.get("status") or "").strip():
        return jsonify({"error": "status is required."}), 400
    status = payload["status"].strip().upper()
    if status not in {"PENDING", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "REOPENED"}:
        return jsonify({"error": f"Invalid status: {status}"}), 400
    try:
        demo_db.update_ticket_status(
            ticket_id,
            actor=user,
            status=status,
            remarks=(payload.get("remarks") or "").strip(),
            time_taken=(payload.get("time_taken") or "").strip(),
            attachment_path=(payload.get("attachment_path") or "").strip(),
        )
        return "", 204
    except (PermissionError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/demo/tickets/<int:ticket_id>/activity")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def api_ticket_activity(ticket_id):
    user = current_user()
    ticket = demo_db.get_ticket(ticket_id)
    if not ticket:
        return jsonify({"error": "Ticket not found."}), 404

    # Access check: creator, assigned CA, same department HOD, or admin/super_admin
    allowed = False
    if user["role"] in ("SUPER_ADMIN", "ADMIN"):
        allowed = True
    elif user["role"] == "HOD" and ticket["department"] == user["department"]:
        allowed = True
    elif ticket["created_by_email"].lower() == user["email"].lower():
        allowed = True
    elif ticket["assigned_to_email"].lower() == user["email"].lower():
        allowed = True

    if not allowed or ticket["org_id"] != user["org_id"]:
        return jsonify({"error": "Access denied: You do not have access to this ticket's activity."}), 403

    activity = demo_db.list_ticket_activity(ticket_id)
    result = []
    for a in activity:
        entry = dict(a)
        if entry.get("created_at"):
            entry["created_at"] = entry["created_at"].isoformat()
        result.append(entry)
    return jsonify(result)


@app.route("/api/analytics/summary")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_analytics_summary():
    user = current_user()
    department = user["department"] if user["role"] == "HOD" else request.args.get("department") or None
    summary = demo_db.dashboard_summary(user)
    dept_stats = demo_db.ticket_stats_by_department(org_id=user["org_id"])
    cat_stats = demo_db.ticket_stats_by_category(department=department, org_id=user["org_id"])
    # Serialize
    def ser(rows):
        out = []
        for r in rows:
            out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()})
        return out
    return jsonify({
        "summary": dict(summary) if summary else {},
        "by_department": ser(dept_stats),
        "by_category": ser(cat_stats),
    })


@app.route("/change-password", methods=["GET", "POST"])
@role_required("ADMIN", "HOD", "CA", "FACULTY")
def change_password():
    user = current_user()
    if request.method == "POST":
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        if not old_password or not new_password:
            flash("All fields are required.", "error")
            return redirect(url_for("change_password"))
        if len(new_password) < 4:
            flash("New password must be at least 4 characters.", "error")
            return redirect(url_for("change_password"))
        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "error")
            return redirect(url_for("change_password"))
        try:
            if not demo_db.change_password(user["id"], old_password, new_password):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("change_password"))
            flash("Password changed successfully.", "success")
            return redirect(url_for("change_password"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("change_password"))
    return render_template("change_password.html", **page_context("Change Password"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/uploads/<path:filename>")
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "FACULTY")
def download_attachment(filename):
    safe_name = secure_filename(filename)
    if not safe_name or not (UPLOAD_DIR / safe_name).is_file():
        abort(404)
    return send_from_directory(UPLOAD_DIR, safe_name)


@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/png"
    )


@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html", error_code=500, error_title="Server Error", error_message="Something went wrong. Please try again later."), 500


@app.errorhandler(404)
def not_found_error(error):
    return render_template("error.html", error_code=404, error_title="Not Found", error_message="The page you are looking for does not exist."), 404


@app.after_request
def add_security_headers(response):
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https://snist.sreenidhi.edu.in https://sreenidhi.edu.in;"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.route("/impersonate-hod", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN")
def impersonate_hod():
    department = request.form.get("department", "").strip()
    if not department:
        flash("Department is required to impersonate HOD.", "error")
        return redirect(url_for(route_for_role(session["role"])))
    session["acting_role"] = "HOD"
    session["acting_department"] = department
    session["available_departments"] = [d["code"] for d in live_departments(session.get("org_id") or resolve_user_org(session["user_email"], session["department"]))]
    # Audit: impersonation start
    demo_db.log_audit_event(
        "IMPERSONATION_START", session["user_id"],
        session.get("org_id", ""),
        target_type="department", target_id=None,
        details={"department": department, "original_role": session["role"]},
    )
    flash(f"Now acting as HOD for {department} department.", "success")
    return redirect(url_for("hod_dashboard"))


@app.route("/exit-hod-mode")
@role_required("HOD")
def exit_hod_mode():
    acting_dept = session.get("acting_department", "")
    if "acting_role" in session:
        del session["acting_role"]
    if "acting_department" in session:
        del session["acting_department"]
    if "available_departments" in session:
        del session["available_departments"]
    # Audit: impersonation end
    demo_db.log_audit_event(
        "IMPERSONATION_STOP", session["user_id"],
        session.get("org_id", ""),
        target_type="department", target_id=None,
        details={"department": acting_dept},
    )
    flash("Stopped impersonating HOD.", "success")
    return redirect(url_for(route_for_role(session["role"])))


@app.route("/switch-acting-department", methods=["POST"])
@role_required("HOD")
def switch_acting_department():
    if "acting_role" not in session:
        flash("You are not currently impersonating HOD.", "error")
        return redirect(url_for(route_for_role(session["role"])))
    old_dept = session.get("acting_department", "")
    department = request.form.get("department", "").strip()
    if not department:
        flash("Invalid department selected.", "error")
        return redirect(url_for("hod_dashboard"))
    session["acting_department"] = department
    # Audit: department switch
    demo_db.log_audit_event(
        "IMPERSONATION_SWITCH", session["user_id"],
        session.get("org_id", ""),
        target_type="department", target_id=None,
        details={"from_department": old_dept, "to_department": department},
    )
    flash(f"Switched acting HOD department to {department}.", "success")
    return redirect(url_for("hod_dashboard"))


@app.route("/super-admin/locations", methods=["GET", "POST"])
@role_required("SUPER_ADMIN")
def location_management():
    user = current_user()
    if request.method == "POST":
        block = request.form.get("block", "").strip()
        floor = request.form.get("floor", "").strip()
        room_no = request.form.get("room_no", "").strip()
        name = request.form.get("name", "").strip()
        if not all([block, floor, room_no]):
            flash("Block, Floor, and Room Number are required.", "error")
            return redirect(url_for("location_management"))
        try:
            demo_db.create_location(user["org_id"], block, floor, room_no, name)
            demo_db.log_audit_event("LOCATION_CREATED", user["id"], user["org_id"],
                                   target_type="location", details={"block": block, "floor": floor, "room_no": room_no})
            flash(f"Location {block} - {floor} - {room_no} created successfully.", "success")
        except Exception as e:
            flash(f"Failed to create location: {e}", "error")
        return redirect(url_for("location_management"))

    search = request.args.get("q", "").strip()
    locations = live_db.fetch_locations()
    filtered_locations = [loc for loc in locations if str(loc.get("ORG_ID", "2000")) == str(user["org_id"])]
    if search:
        search_lower = search.lower()
        filtered_locations = [loc for loc in filtered_locations
                              if search_lower in (loc.get("block") or "").lower()
                              or search_lower in (loc.get("floor") or "").lower()
                              or search_lower in (loc.get("room_no") or "").lower()
                              or search_lower in (loc.get("name") or "").lower()]
    return render_template("location_management.html", locations=filtered_locations, search=search, **page_context("Location Management"))


# Department Management removed (handled directly in DB)


@app.route("/hod/ca-assignments", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN")
def ca_assignments():
    user = current_user()
    
    # Super Admin manages assignments organization-wide (no department filter)
    is_super = user["role"] == "SUPER_ADMIN"
    dept_filter = None if is_super else user["department"]

    if request.method == "POST":
        faculty_id_str = request.form.get("faculty_id", "").strip()
        
        # Support both multi-select category checkboxes and single select category_id (for tests/APIs)
        category_ids = [safe_int(cid) for cid in request.form.getlist("categories") if safe_int(cid) > 0]
        if not category_ids:
            single_cat = safe_int(request.form.get("category_id", "0"))
            if single_cat > 0:
                category_ids = [single_cat]
        
        # Support both multi-select checkbox list and single select block (for tests/APIs)
        blocks = request.form.getlist("blocks")
        if not blocks:
            single_block = request.form.get("block", "").strip()
            if single_block:
                blocks = [single_block]

        if not faculty_id_str or not category_ids or not blocks:
            flash("Faculty, Category/s, and Problem (Block/s) are required.", "error")
            return redirect(url_for("ca_assignments"))

        try:
            # Group category IDs by department to promote the CA for each department they get mapped to
            dept_to_categories = {}
            for cat_id in category_ids:
                cat = demo_db.get_category(cat_id)
                if cat:
                    dept = cat["department"]
                    if dept not in dept_to_categories:
                        dept_to_categories[dept] = []
                    dept_to_categories[dept].append(cat_id)

            if not dept_to_categories:
                flash("Selected categories are invalid.", "error")
                return redirect(url_for("ca_assignments"))

            success_count = 0
            already_assigned_count = 0
            
            with demo_db.transaction():
                for dept, cat_ids in dept_to_categories.items():
                    ca_id = resolve_and_promote_ca(faculty_id_str, dept, user["id"], user["org_id"])
                    for cat_id in cat_ids:
                        for b in blocks:
                            b_stripped = b.strip()
                            if not b_stripped:
                                continue
                            try:
                                demo_db.create_ca_assignment(cat_id, ca_id, b_stripped)
                                demo_db.log_audit_event(
                                    "CA_BLOCK_ASSIGNED", user["id"], user["org_id"],
                                    target_type="ca_assignment", target_id=ca_id,
                                    details={"category_id": cat_id, "block": b_stripped},
                                )
                                success_count += 1
                            except ValueError as ve:
                                if "already assigned" in str(ve).lower():
                                    already_assigned_count += 1
                                else:
                                    raise ve

            if success_count > 0:
                if already_assigned_count > 0:
                    flash(f"Assigned CA to {success_count} mapping(s) successfully ({already_assigned_count} mapping(s) were already assigned to this CA).", "success")
                else:
                    flash(f"CA assigned to {success_count} mapping(s) successfully.", "success")
            elif already_assigned_count > 0:
                flash("This CA is already assigned to all the selected category-block mappings.", "warning")
            else:
                flash("No valid mappings were selected.", "error")
        except Exception as e:
            flash(f"Assignment failed: {e}", "error")
        return redirect(url_for("ca_assignments"))

    faculties = demo_db.list_users(role="FACULTY", department=dept_filter, org_id=user["org_id"])
    cas = demo_db.list_users(role="CA", department=dept_filter, org_id=user["org_id"])
    
    promoteable_users = []
    seen_emails = set()
    for u in (faculties + cas):
        email_lower = u["email"].lower().strip()
        seen_emails.add(email_lower)
        promoteable_users.append({
            "id": u["id"],
            "name": u["name"],
            "email": u["email"],
            "role": u["role"],
            "department": u["department"],
        })

    if live_db.enabled:
        ref_users = live_db.fetch_reference_users(department=dept_filter, org_id=user["org_id"], limit=1000)
        for r in ref_users:
            email_lower = (r.get("EMAIL_ID") or "").lower().strip()
            if email_lower and email_lower not in seen_emails:
                seen_emails.add(email_lower)
                promoteable_users.append({
                    "id": f"ref:{r['EMAIL_ID']}",
                    "name": r.get("TEACHER_NAME") or "Unknown",
                    "email": r["EMAIL_ID"],
                    "role": "FACULTY",
                    "department": r.get("department_code") or r.get("department_name") or "",
                })

    categories = demo_db.list_categories(department=dept_filter, org_id=user["org_id"], active_only=True)
    
    locations = live_db.fetch_locations()
    blocks = sorted(list(set(loc["block"] for loc in locations if loc.get("block"))))

    assignments = demo_db.list_ca_assignments(department=dept_filter, org_id=user["org_id"])
    total_assignments_count = len(assignments)

    from collections import defaultdict
    grouped = defaultdict(list)
    for a in assignments:
        grouped[a["ca_id"]].append(a)

    grouped_assignments = []
    for ca_id, items in grouped.items():
        grouped_assignments.append({
            "ca_id": ca_id,
            "ca_name": items[0]["ca_name"],
            "ca_email": items[0]["ca_email"],
            "mappings": items
        })
    grouped_assignments.sort(key=lambda x: x["ca_name"])

    return render_template(
        "ca_assignments.html",
        users=promoteable_users,
        categories=categories,
        blocks=blocks,
        assignments=grouped_assignments,
        total_count=total_assignments_count,
        **page_context("CA Assignments")
    )


@app.route("/hod/ca-assignments/<int:assignment_id>/delete", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN")
def delete_ca_assignment(assignment_id):
    try:
        demo_db.delete_ca_assignment(assignment_id)
        flash("CA assignment removed successfully.", "success")
    except Exception as e:
        flash(f"Failed to delete assignment: {e}", "error")
    return redirect(url_for("ca_assignments"))

# ── New Feature Routes ──────────────────────────────────────────────

# Location edit/delete (Feature 2)
@app.route("/super-admin/locations/<int:location_id>/update", methods=["POST"])
@role_required("SUPER_ADMIN")
def update_location(location_id):
    user = current_user()
    block = request.form.get("block", "").strip()
    floor = request.form.get("floor", "").strip()
    room_no = request.form.get("room_no", "").strip()
    name = request.form.get("name", "").strip()
    if not all([block, floor, room_no]):
        flash("Block, Floor, and Room Number are required.", "error")
        return redirect(url_for("location_management"))
    try:
        live_db.update_location(location_id, block, floor, room_no, name)
        demo_db.log_audit_event("LOCATION_UPDATED", user["id"], user["org_id"],
                               target_type="location", target_id=location_id,
                               details={"block": block, "floor": floor, "room_no": room_no})
        flash("Location updated successfully.", "success")
    except Exception as e:
        flash(f"Failed to update location: {e}", "error")
    return redirect(url_for("location_management"))


@app.route("/super-admin/locations/<int:location_id>/delete", methods=["POST"])
@role_required("SUPER_ADMIN")
def delete_location(location_id):
    user = current_user()
    try:
        loc = live_db.get_location(location_id)
        live_db.delete_location(location_id)
        demo_db.log_audit_event("LOCATION_DELETED", user["id"], user["org_id"],
                               target_type="location", target_id=location_id,
                               details={"block": loc.get("block") if loc else "", "room_no": loc.get("room_no") if loc else ""})
        flash("Location deleted successfully.", "success")
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"Failed to delete location: {e}", "error")
    return redirect(url_for("location_management"))


# Department edit/archive routes removed


# API: Categories by department (Feature 7)
@app.route("/api/categories-by-department")
def api_categories_by_department():
    department = request.args.get("department", "").strip()
    if not department:
        return jsonify([])
    user = current_user()
    cats = demo_db.list_categories(department=department, org_id=user["org_id"], active_only=True)
    return jsonify([{"id": c["id"], "category_name": c["category_name"], "department": c["department"]} for c in cats])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
