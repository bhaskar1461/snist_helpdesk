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
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
)
csrf = CSRFProtect(app)

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "sql" / "demo_schema.sql"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "doc", "docx", "xls", "xlsx"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

DB_CONFIG = env_db_config()
live_db = LiveDbService(DB_CONFIG)
demo_db = DemoDbService(DB_CONFIG)

DEFAULT_DEMO_USERS = [
    {"name": "Super Admin", "email": "admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration"},
    {"name": "Campus Admin", "email": "campus.admin@gmail.com", "password": "123", "role": "ADMIN", "department": "Administration"},
    {"name": "Dr. Kavya", "email": "hod@gmail.com", "password": "123", "role": "HOD", "department": "CSE"},
    {"name": "Dr. Harini", "email": "hod.ece@gmail.com", "password": "123", "role": "HOD", "department": "ECE"},
    {"name": "Chandini", "email": "ca@gmail.com", "password": "123", "role": "CA", "department": "CSE"},
    {"name": "Sravan", "email": "sravan.ca@gmail.com", "password": "123", "role": "CA", "department": "Facilities"},
    {"name": "Bhaskar", "email": "bhaskar.ca@gmail.com", "password": "123", "role": "CA", "department": "Maintenance"},
    {"name": "Faculty User", "email": "faculty@gmail.com", "password": "123", "role": "FACULTY", "department": "CSE"},
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
        demo_db.ensure_schema(SCHEMA_PATH)
        demo_db.seed_defaults(DEFAULT_DEMO_USERS, DEFAULT_DEMO_CATEGORIES)
        # Migration: add location_id if it doesn't exist yet
        try:
            conn = demo_db.connection()
            cur = conn.cursor()
            cur.execute("SHOW COLUMNS FROM demo_tickets LIKE 'location_id'")
            if not cur.fetchone():
                cur.execute("ALTER TABLE demo_tickets ADD COLUMN location_id INT UNSIGNED NULL COMMENT 'FK to location table' AFTER org_id")
                log.info("Migration: added location_id column to demo_tickets.")
            cur.close()
            conn.close()
        except Exception as mig_exc:
            log.warning("Migration check for location_id: %s", mig_exc)
        log.info("Demo database bootstrapped successfully.")
    except Exception as exc:
        log.error("Demo DB bootstrap failed: %s", exc)


bootstrap_demo_database()


def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def current_user():
    if not session.get("user_id"):
        return None
    return {
        "id": session["user_id"],
        "name": session["user_name"],
        "email": session["user_email"],
        "role": session["role"],
        "department": session["department"],
    }


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in to continue.", "error")
                return redirect(url_for("login"))
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
        "FACULTY": "faculty_dashboard",
    }.get(role, "login")


def sidebar_links(role):
    mapping = {
        "SUPER_ADMIN": [
            ("super_admin_dashboard", "Dashboard"),
            ("super_admin_all_tickets", "All Tickets"),
            ("user_management", "User Management"),
            ("create_ticket_for_role", "Create Ticket"),
        ],
        "ADMIN": [
            ("admin_dashboard", "Dashboard"),
            ("admin_all_tickets", "All Tickets"),
            ("user_management", "User Management"),
            ("create_ticket_for_role", "Create Ticket"),
        ],
        "HOD": [
            ("hod_dashboard", "Dashboard"),
            ("hod_all_tickets", "Department Tickets"),
            ("management_category", "CA Mapping"),
            ("create_ticket_for_role", "Create Ticket"),
        ],
        "CA": [
            ("authority_tickets", "CA Dashboard"),
            ("ca_report", "Reports"),
            ("create_ticket_for_role", "Create Ticket"),
        ],
        "FACULTY": [
            ("faculty_dashboard", "Dashboard"),
            ("my_tickets", "My Tickets"),
            ("create_ticket_for_role", "Create Ticket"),
        ],
    }
    links = mapping.get(role, [])
    if role != "SUPER_ADMIN":
        links = links + [("change_password", "Change Password")]
    return links + [("logout", "Logout")]


def page_context(role_title):
    user = current_user()
    return {
        "role_title": role_title,
        "user_name": user["name"] if user else "",
        "role_email": user["email"] if user else "",
        "current_role": user["role"] if user else "",
        "sidebar_links": sidebar_links(user["role"]) if user else [],
        "db_ready": demo_db.enabled,
    }


def live_departments():
    rows = live_db.fetch_departments() if live_db.enabled else []
    departments = []
    seen = set()
    for row in rows:
        code = row.get("department_code") or row.get("department_name")
        if not code or code in seen:
            continue
        seen.add(code)
        departments.append(
            {
                "code": code,
                "name": row.get("department_name") or code,
                "org_id": row.get("org_id") or "2000",
            }
        )
    if not departments:
        departments = [
            {"code": "CSE", "name": "Computer Science and Engineering", "org_id": "2000"},
            {"code": "ECE", "name": "Electronics and Communication Engineering", "org_id": "2000"},
            {"code": "Facilities", "name": "Facilities", "org_id": "2000"},
            {"code": "Maintenance", "name": "Maintenance", "org_id": "2000"},
        ]
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


def export_response(tickets, export_format, filename):
    rows = serialize_tickets(tickets)
    fieldnames = list(rows[0].keys()) if rows else [
        "Ticket ID", "Title", "Description", "Category", "Department",
        "Created By", "Assigned To", "Status", "Org ID", "Created At", "Updated At",
    ]
    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return Response(buffer.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename={filename}.csv"})

    table_rows = "".join("<tr>" + "".join(f"<td>{escape(row.get(key, ''))}</td>" for key in fieldnames) + "</tr>" for row in rows)
    table_html = "<table><thead><tr>" + "".join(f"<th>{key}</th>" for key in fieldnames) + f"</tr></thead><tbody>{table_rows}</tbody></table>"
    return Response(table_html, mimetype="application/vnd.ms-excel", headers={"Content-Disposition": f"attachment; filename={filename}.xls"})


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not demo_db.enabled:
            flash("MySQL demo database is not configured. Start the app with MYSQL_* environment variables.", "error")
            return render_template("login.html")

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()

        # 1) Try demo_users first (existing accounts)
        user = demo_db.authenticate_user(email, password)

        # 2) If not found and email is @sreenidhi.edu.in, try teacher_info
        if not user and email.endswith("@sreenidhi.edu.in"):
            teacher = live_db.lookup_teacher_by_email(email)
            if teacher and teacher.get("sap_id"):
                # Verify password against SAP ID
                sap_id = str(teacher["sap_id"]).strip()
                if password == sap_id:
                    # Auto-provision into demo_users as FACULTY
                    teacher_name = (teacher.get("name") or "Faculty").strip()
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

        if not user:
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["user_name"] = user["name"]
        session["user_email"] = user["email"]
        session["role"] = user["role"]
        session["department"] = user["department"]
        return redirect(url_for(route_for_role(user["role"])))

    if current_user():
        return redirect(url_for(route_for_role(session["role"])))
    return render_template("login.html")


@app.route("/faculty/dashboard")
@role_required("FACULTY")
def faculty_dashboard():
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    tickets = demo_db.list_tickets(user, scope="own")
    return render_template("faculty_dashboard.html", summary=summary, tickets=tickets[:5], **page_context("Faculty"))


@app.route("/faculty/my-tickets")
@role_required("FACULTY")
def my_tickets():
    user = current_user()
    tickets = demo_db.list_tickets(user, scope="own", filters=filters_from_request())
    return render_template("my_tickets.html", tickets=tickets, filters=filters_from_request(), **page_context("My Tickets"))


@app.route("/tickets/create", methods=["GET", "POST"])
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def create_ticket_for_role():
    user = current_user()
    categories = demo_db.list_categories(department=user["department"])
    if request.method == "POST":
        category_id = safe_int(request.form.get("category_id", "0"))
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location_id = safe_int(request.form.get("location_id", "0")) or None
        if not title or not description or not category_id:
            flash("Title, description, and category are required.", "error")
            return redirect(url_for("create_ticket_for_role"))
        org_id = live_db.resolve_org_id(email=user["email"], department=user["department"])
        demo_db.create_ticket(title=title, description=description, category_id=category_id, created_by=user["id"], org_id=org_id, location_id=location_id)
        flash("Ticket created and auto-assigned to the mapped Concerned Authority.", "success")
        return redirect(url_for(route_for_role(user["role"])))

    locations = live_db.fetch_locations()
    return render_template("create_ticket.html", categories=categories, locations=locations, departments=live_departments(), **page_context("Create Ticket"))


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


@app.route("/super-admin/dashboard")
@role_required("SUPER_ADMIN")
def super_admin_dashboard():
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    return render_template(
        "management_dashboard.html",
        summary=summary,
        highlights=demo_db.hod_overview(),
        dept_stats=demo_db.ticket_stats_by_department(),
        cat_stats=demo_db.ticket_stats_by_category(),
        page_title="Super Admin Dashboard",
        kicker="RBAC Control",
        page_heading="Super Admin overview",
        page_description="Full control over users, roles, departments, and ticket visibility.",
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
        return redirect(url_for("faculty_dashboard" if user["role"] == "FACULTY" else "authority_tickets"))
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
    if not allowed:
        flash("You do not have access to this ticket.", "error")
        return redirect(url_for("faculty_dashboard" if user["role"] == "FACULTY" else "authority_tickets"))
    activity = demo_db.list_ticket_activity(ticket_id)
    # Determine next allowed transitions for status action
    next_statuses = list(demo_db.ALLOWED_TRANSITIONS.get(ticket["status"], set()))
    can_update = user["role"] == "SUPER_ADMIN" or (user["role"] == "CA" and ticket["assigned_to_email"].lower() == user["email"].lower())
    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        activity=activity,
        next_statuses=next_statuses,
        can_update=can_update,
        **page_context("Ticket #" + str(ticket_id)),
    )


@app.route("/authority/update-status/<int:ticket_id>", methods=["POST"])
@role_required("CA")
def authority_update_status(ticket_id):
    user = current_user()
    status = request.form.get("status", "").strip().upper()
    remarks = request.form.get("remarks", "").strip()
    time_taken = request.form.get("time_taken", "").strip()
    attachment = request.files.get("attachment")

    if status not in {"PENDING", "IN_PROGRESS", "RESOLVED"}:
        flash("Invalid status selected.", "error")
        return redirect(url_for("authority_tickets"))
    if status == "RESOLVED" and not remarks:
        flash("Resolution remarks are required.", "error")
        return redirect(url_for("authority_tickets"))

    attachment_path = ""
    if attachment and attachment.filename:
        if not allowed_file(attachment.filename):
            flash(f"File type not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}.", "error")
            return redirect(url_for("authority_tickets"))
        attachment.seek(0, 2)
        size = attachment.tell()
        attachment.seek(0)
        if size > MAX_UPLOAD_SIZE:
            flash(f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.", "error")
            return redirect(url_for("authority_tickets"))
        safe_name = secure_filename(attachment.filename)
        attachment_name = f"{ticket_id}-{int(datetime.now().timestamp())}-{safe_name}"
        attachment.save(UPLOAD_DIR / attachment_name)
        attachment_path = attachment_name

    try:
        demo_db.update_ticket_status(ticket_id, actor=user, status=status, remarks=remarks, time_taken=time_taken, attachment_path=attachment_path)
        flash("Ticket updated successfully.", "success")
    except PermissionError as exc:
        flash(str(exc), "error")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("authority_tickets"))


@app.route("/user-management", methods=["GET", "POST"])
@role_required("SUPER_ADMIN", "ADMIN")
def user_management():
    user = current_user()
    if request.method == "POST":
        role = request.form.get("role", "").strip().upper()
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
        if not is_valid_email(payload["email"]):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("user_management"))
        existing = demo_db.list_users(search=payload["email"])
        if any(u["email"].lower() == payload["email"] for u in existing):
            flash(f"A user with email '{payload['email']}' already exists.", "error")
            return redirect(url_for("user_management"))
        demo_db.create_user(payload)
        flash("Demo user created successfully.", "success")
        return redirect(url_for("user_management"))

    search = request.args.get("q", "").strip()
    roles_filter = [r.upper() for r in request.args.getlist("role") if r.strip()]
    department = request.args.get("department", "").strip() or None
    role_arg = roles_filter if len(roles_filter) > 1 else (roles_filter[0] if roles_filter else None)
    users = demo_db.list_users(role=role_arg, department=department, search=search)
    departments = live_departments()
    return render_template(
        "user_management.html",
        users=users,
        departments=departments,
        filters={"q": search, "role": roles_filter[0] if len(roles_filter) == 1 else "", "roles": roles_filter, "department": department or ""},
        roles=list(ROLE_MAP.keys()),
        **page_context("User Management"),
    )


@app.route("/user-management/<int:user_id>/update", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN")
def update_user(user_id):
    role = request.form.get("role", "").strip().upper()
    if role == "CA":
        department = ",".join([d.strip() for d in request.form.getlist("department") if d.strip()])
    else:
        department = request.form.get("department", "").strip()
    password = request.form.get("password", "").strip()
    payload = {
        "name": request.form.get("name", "").strip(),
        "email": request.form.get("email", "").strip().lower(),
        "role": role,
        "department": department,
    }
    if password:
        payload["password"] = password
    if not all([payload["name"], payload["email"], payload["role"], payload["department"]]):
        flash("All user fields are required.", "error")
        return redirect(url_for("user_management"))
    if not is_valid_email(payload["email"]):
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("user_management"))
    demo_db.update_user(user_id, payload)
    flash("Demo user updated.", "success")
    return redirect(url_for("user_management"))


@app.route("/user-management/<int:user_id>/delete", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN")
def delete_user(user_id):
    try:
        demo_db.delete_user(user_id)
        flash("Demo user deleted.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("user_management"))


@app.route("/management/category-management", methods=["GET", "POST"])
@role_required("HOD", "SUPER_ADMIN")
def management_category():
    user = current_user()
    if request.method == "POST":
        payload = {
            "category_name": request.form.get("category_name", "").strip(),
            "department": user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip(),
            "assigned_ca_id": safe_int(request.form.get("assigned_ca_id", "0")),
        }
        if not payload["category_name"] or not payload["department"] or not payload["assigned_ca_id"]:
            flash("Category name, department, and CA are required.", "error")
            return redirect(url_for("management_category"))
        # Duplicate check
        if demo_db.category_exists(payload["category_name"], payload["department"]):
            flash(f"A category '{payload['category_name']}' already exists in {payload['department']}.", "error")
            return redirect(url_for("management_category"))
        # HOD can only assign CA within their department
        if user["role"] == "HOD":
            ca_user = demo_db.get_user(payload["assigned_ca_id"])
            if not ca_user or user["department"] not in [d.strip() for d in ca_user["department"].split(",")]:
                flash("You can only assign a CA from your own department.", "error")
                return redirect(url_for("management_category"))
        demo_db.create_category(payload)
        flash("Category mapped to Concerned Authority.", "success")
        return redirect(url_for("management_category"))

    # GET: support search/filter
    department = user["department"] if user["role"] == "HOD" else request.args.get("department", "").strip() or None
    search = request.args.get("q", "").strip()
    ca_filter = safe_int(request.args.get("ca", "0")) or None
    categories = demo_db.list_categories(department=department, search=search, ca_id=ca_filter)
    ca_users = demo_db.list_users(role="CA", department=department)
    return render_template(
        "category_management.html",
        categories=categories,
        ca_users=ca_users,
        departments=live_departments(),
        selected_department=department or "",
        filters={"q": search, "department": department or "", "ca": ca_filter or ""},
        **page_context("Category Mapping"),
    )


@app.route("/management/category-management/<int:category_id>/update", methods=["POST"])
@role_required("HOD", "SUPER_ADMIN")
def update_category(category_id):
    user = current_user()
    # HOD can only update categories in their department
    if user["role"] == "HOD":
        existing_cat = demo_db.get_category(category_id)
        if not existing_cat or existing_cat["department"] != user["department"]:
            flash("You can only modify categories in your own department.", "error")
            return redirect(url_for("management_category"))
    payload = {
        "category_name": request.form.get("category_name", "").strip(),
        "department": user["department"] if user["role"] == "HOD" else request.form.get("department", "").strip(),
        "assigned_ca_id": safe_int(request.form.get("assigned_ca_id", "0")),
    }
    if not payload["category_name"] or not payload["department"] or not payload["assigned_ca_id"]:
        flash("Category name, department, and CA are required.", "error")
        return redirect(url_for("management_category"))
    # Duplicate check (exclude self)
    if demo_db.category_exists(payload["category_name"], payload["department"], exclude_id=category_id):
        flash(f"A category '{payload['category_name']}' already exists in {payload['department']}.", "error")
        return redirect(url_for("management_category"))
    # HOD can only assign CA within their department
    if user["role"] == "HOD":
        ca_user = demo_db.get_user(payload["assigned_ca_id"])
        if not ca_user or user["department"] not in [d.strip() for d in ca_user["department"].split(",")]:
            flash("You can only assign a CA from your own department.", "error")
            return redirect(url_for("management_category"))
    demo_db.update_category(category_id, payload)
    flash("Category mapping updated.", "success")
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
        flash("Category mapping deleted.", "success")
    except ValueError as exc:
        flash(str(exc), "error")
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
    return jsonify(live_departments())


@app.route("/api/live/users")
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_live_users():
    search = request.args.get("q", "").strip()
    department = request.args.get("department", "").strip() or None
    rows = live_db.fetch_reference_users(search=search, department=department, limit=100) if live_db.enabled else []
    return jsonify(rows)


@app.route("/api/demo/users", methods=["GET", "POST"])
@csrf.exempt
@role_required("SUPER_ADMIN", "ADMIN")
def api_demo_users():
    if request.method == "GET":
        return jsonify([user_json(row) for row in demo_db.list_users(
            role=request.args.get("role", "").strip().upper() or None,
            department=request.args.get("department", "").strip() or None,
            search=request.args.get("q", "").strip(),
        )])

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
@csrf.exempt
@role_required("SUPER_ADMIN", "ADMIN")
def api_demo_user_detail(user_id):
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
@csrf.exempt
@role_required("SUPER_ADMIN", "HOD")
def api_demo_categories():
    if request.method == "GET":
        department = current_user()["department"] if current_user()["role"] == "HOD" else request.args.get("department", "").strip() or None
        return jsonify(demo_db.list_categories(department=department))

    payload = request.get_json(force=True)
    if not payload:
        return jsonify({"error": "Request body is required."}), 400
    category_name = (payload.get("category_name") or "").strip()
    assigned_ca_id = safe_int(payload.get("assigned_ca_id"))
    department = current_user()["department"] if current_user()["role"] == "HOD" else (payload.get("department") or "").strip()
    if not all([category_name, department, assigned_ca_id]):
        return jsonify({"error": "category_name, department, and assigned_ca_id are required."}), 400
    category_id = demo_db.create_category(
        {
            "category_name": category_name,
            "department": department,
            "assigned_ca_id": assigned_ca_id,
        }
    )
    return jsonify({"id": category_id}), 201


@app.route("/api/demo/categories/<int:category_id>", methods=["PUT", "DELETE"])
@csrf.exempt
@role_required("SUPER_ADMIN", "HOD")
def api_demo_category_detail(category_id):
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
    department = current_user()["department"] if current_user()["role"] == "HOD" else (payload.get("department") or "").strip()
    if not all([category_name, department, assigned_ca_id]):
        return jsonify({"error": "category_name, department, and assigned_ca_id are required."}), 400
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
@csrf.exempt
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
@csrf.exempt
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def api_demo_ticket_detail(ticket_id):
    user = current_user()
    if request.method == "GET":
        ticket = demo_db.get_ticket(ticket_id)
        if not ticket:
            return jsonify({"error": "Ticket not found."}), 404
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
    if status not in {"PENDING", "IN_PROGRESS", "RESOLVED"}:
        return jsonify({"error": f"Invalid status: {status}"}), 400
    try:
        demo_db.update_ticket_status(
            ticket_id,
            actor=current_user(),
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
    dept_stats = demo_db.ticket_stats_by_department()
    cat_stats = demo_db.ticket_stats_by_category(department=department)
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
            demo_db.change_password(user["id"], old_password, new_password)
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


@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html", error_code=500, error_title="Server Error", error_message="Something went wrong. Please try again later."), 500


@app.errorhandler(404)
def not_found_error(error):
    return render_template("error.html", error_code=404, error_title="Not Found", error_message="The page you are looking for does not exist."), 404


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true")
