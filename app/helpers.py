"""Shared helpers and utilities used across all blueprints."""

from __future__ import annotations

import csv
import io
import time
import logging
from collections import defaultdict
from datetime import datetime
from functools import wraps

from flask import Response, flash, redirect, request, session, url_for
from markupsafe import escape
from werkzeug.utils import secure_filename

from app.config import (
    ALLOWED_EXTENSIONS, EMAIL_RE, LOCKOUT_TIME, MAX_ATTEMPTS,
    MAX_UPLOAD_SIZE, ORG_LABELS, ROLE_DASHBOARD_ROUTES, UPLOAD_DIR,
)

log = logging.getLogger(__name__)

# ── Brute-force Rate Limiter ────────────────────────────────────────
LOGIN_ATTEMPTS: dict[str, list[float]] = defaultdict(list)


def is_login_rate_limited(ip: str) -> bool:
    now = time.time()
    LOGIN_ATTEMPTS[ip] = [t for t in LOGIN_ATTEMPTS[ip] if now - t < LOCKOUT_TIME]
    return len(LOGIN_ATTEMPTS[ip]) >= MAX_ATTEMPTS


def record_login_attempt(ip: str) -> None:
    LOGIN_ATTEMPTS[ip].append(time.time())


def clear_login_attempts(ip: str) -> None:
    if ip in LOGIN_ATTEMPTS:
        del LOGIN_ATTEMPTS[ip]


# ── Validation ──────────────────────────────────────────────────────
def is_valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email))


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def verify_file_signature(file_stream) -> bool:
    try:
        header = file_stream.read(4)
        file_stream.seek(0)
        signatures = [
            b'\x89PNG',       # PNG
            b'\xff\xd8',      # JPEG
            b'%PDF',          # PDF
            b'GIF8',          # GIF
            b'PK\x03\x04',   # ZIP / DOCX / XLSX
            b'\xd0\xcf\x11\xe0',  # OLE CF (legacy doc, xls)
        ]
        return any(header.startswith(sig) for sig in signatures)
    except Exception:
        return False


def safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ── Org Resolution ──────────────────────────────────────────────────
def resolve_user_org(email, department, live_db=None):
    """Determine which organization a user belongs to."""
    email_lower = (email or "").lower().strip()

    if live_db and live_db.enabled and email_lower:
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

    if department and live_db and live_db.enabled:
        resolved = live_db.resolve_org_id(department=department)
        if resolved:
            return resolved

    return "2000"


# ── Session Helpers ─────────────────────────────────────────────────
def current_user():
    """Get the current logged-in user from session."""
    if not session.get("user_id"):
        return None
    from app import get_live_db
    live_db = get_live_db()
    email = session["user_email"]
    dept = session.get("acting_department") or session["department"]
    role = session.get("acting_role") or session["role"]
    return {
        "id": session["user_id"],
        "name": session["user_name"],
        "email": email,
        "role": role,
        "department": dept,
        "org_id": resolve_user_org(email, dept, live_db),
    }


def route_for_role(role: str) -> str:
    return ROLE_DASHBOARD_ROUTES.get(role, "auth.login")


# ── Decorators ──────────────────────────────────────────────────────
def role_required(*roles):
    """Restrict access to specified roles."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                flash("Please log in to continue.", "error")
                return redirect(url_for("auth.login"))
            if user["role"] not in roles:
                flash("You do not have access to that page.", "error")
                return redirect(url_for(route_for_role(user["role"])))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator


# ── Sidebar ─────────────────────────────────────────────────────────
def sidebar_links(role: str) -> list[tuple[str, str, str]]:
    from app.config import SSO_ENABLED
    mapping = {
        "SUPER_ADMIN": [
            ("dashboards.super_admin_dashboard", "Dashboard", "layout-dashboard"),
            ("tickets.create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("dashboards.super_admin_all_tickets", "All Tickets", "ticket"),
            ("management.category_assignments", "Category & Assignee Management", "folder-open"),
            ("management.location_management", "Locations", "map-pin"),
            ("analytics.analytics_dashboard", "Analytics", "bar-chart-3"),
        ],
        "ADMIN": [
            ("dashboards.admin_dashboard", "Dashboard", "layout-dashboard"),
            ("tickets.create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("dashboards.admin_all_tickets", "All Tickets", "ticket"),
            ("management.category_assignments", "Category & Assignee Management", "folder-open"),
            ("analytics.analytics_dashboard", "Analytics", "bar-chart-3"),
        ],
        "HOD": [
            ("dashboards.hod_dashboard", "Dashboard", "layout-dashboard"),
            ("tickets.create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("dashboards.hod_all_tickets", "Dept. Tickets", "ticket"),
            ("management.category_assignments", "Category & Assignee Management", "folder-open"),
            ("analytics.analytics_dashboard", "Analytics", "bar-chart-3"),
        ],
        "ASSIGNEE": [
            ("tickets.authority_tickets", "Dashboard", "layout-dashboard"),
            ("tickets.create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("tickets.authority_dept_tickets", "My Dept Tickets", "ticket"),
            ("management.category_assignments", "Category & Assignee Management", "folder-open"),
            ("tickets.ca_report", "Reports", "bar-chart-3"),
        ],
        "CA": [
            ("tickets.authority_tickets", "Dashboard", "layout-dashboard"),
            ("tickets.create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("tickets.authority_dept_tickets", "My Dept Tickets", "ticket"),
            ("management.category_assignments", "Category & Assignee Management", "folder-open"),
            ("tickets.ca_report", "Reports", "bar-chart-3"),
        ],
        "FACULTY": [
            ("dashboards.user_dashboard", "Dashboard", "layout-dashboard"),
            ("tickets.create_ticket_for_role", "Create Ticket", "plus-circle"),
            ("dashboards.my_tickets", "My Tickets", "ticket"),
        ],
    }
    links = mapping.get(role, [])
    # Only show Change Password if SSO is not the primary auth
    if not SSO_ENABLED and role != "SUPER_ADMIN":
        links = links + [("auth.change_password", "Change Password", "lock")]
    return links + [("auth.logout", "Logout", "log-out")]


# ── Page Context ────────────────────────────────────────────────────
def page_context(role_title: str) -> dict:
    user = current_user()
    org_id = user["org_id"] if user else "2000"
    org_label = ORG_LABELS.get(org_id, "SNIST")
    logo_filename = "images/snu_logo.webp" if org_id == "3000" else "images/snist_logo.jpg"
    return {
        "user": user,
        "current_user": user,
        "role_title": role_title,
        "user_name": user["name"] if user else "",
        "role_email": user["email"] if user else "",
        "current_role": user["role"] if user else "",
        "sidebar_links": sidebar_links(user["role"]) if user else [],
        "db_ready": True,
        "org_label": org_label,
        "logo_filename": logo_filename,
    }



# ── Department Helpers ──────────────────────────────────────────────
def live_departments(org_id=None):
    from app import get_live_db
    live_db = get_live_db()
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
        departments.append({
            "id": row.get("BRANCH_ID"),
            "code": code,
            "name": row.get("department_name") or code,
            "org_id": row_org_id,
            "is_archived": row.get("is_archived", 0),
        })
    if not departments:
        default_list = [
            {"code": "CSE", "name": "Computer Science and Engineering", "org_id": "2000"},
            {"code": "ECE", "name": "Electronics and Communication Engineering", "org_id": "2000"},
            {"code": "Facilities", "name": "Facilities", "org_id": "2000"},
            {"code": "Maintenance", "name": "Maintenance", "org_id": "2000"},
        ]
        departments = [d for d in default_list if not org_id or d["org_id"] == org_id]
    return departments


# ── Filter Helpers ──────────────────────────────────────────────────
def filters_from_request():
    return {
        "q": request.args.get("q", "").strip(),
        "status": request.args.get("status", "").strip().upper(),
        "department": request.args.get("department", "").strip(),
        "location_id": request.args.get("location_id", "").strip(),
        "org_id": request.args.get("org_id", "").strip(),
        "from_date": request.args.get("from_date", "").strip(),
        "to_date": request.args.get("to_date", "").strip(),
    }


# ── Export Helpers ──────────────────────────────────────────────────
def serialize_tickets(tickets):
    rows = []
    for ticket in tickets:
        rows.append({
            "Ticket ID": ticket["id"],
            "Title": ticket["title"],
            "Description": ticket["description"],
            "Category": ticket["category_name"],
            "Department": ticket["department"],
            "Location": f"{ticket.get('location_block', '')} {ticket.get('location_room_no', '')}".strip() or "—",
            "Created By": ticket["created_by_name"],
            "Assigned To": ticket["assigned_to_name"],
            "Status": ticket["status"],
            "Org ID": ticket["org_id"],
            "Created At": ticket["created_at"],
            "Updated At": ticket["updated_at"],
        })
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
    sanitized_rows = [{k: sanitize_for_csv(v) for k, v in r.items()} for r in rows]

    fieldnames = list(rows[0].keys()) if rows else [
        "Ticket ID", "Title", "Description", "Category", "Department", "Location",
        "Created By", "Assigned To", "Status", "Org ID", "Created At", "Updated At",
    ]
    if export_format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(sanitized_rows)
        return Response(buffer.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": f"attachment; filename={filename}.csv"})

    table_rows = "".join(
        "<tr>" + "".join(f"<td>{escape(row.get(key, ''))}</td>" for key in fieldnames) + "</tr>"
        for row in sanitized_rows
    )
    table_html = ("<table><thead><tr>"
                   + "".join(f"<th>{key}</th>" for key in fieldnames)
                   + f"</tr></thead><tbody>{table_rows}</tbody></table>")
    return Response(table_html, mimetype="application/vnd.ms-excel",
                    headers={"Content-Disposition": f"attachment; filename={filename}.xls"})
