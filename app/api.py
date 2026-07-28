"""REST API blueprint — user search autocomplete, department/location lookups, and data APIs."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.helpers import current_user, role_required

log = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/users/search")
@role_required("HOD", "ADMIN", "SUPER_ADMIN", "CA")
def search_users():
    """Live user search autocomplete. Searches by name, email, or employee ID."""
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()

    q = request.args.get("q", "").strip()
    search_type = request.args.get("type", "name")  # name, email, employee_id
    role_filter = request.args.get("role", "")
    department_filter = request.args.get("department", "")
    limit = min(int(request.args.get("limit", "20")), 50)

    if len(q) < 2:
        return jsonify({"results": []})

    results = []
    seen_emails = set()

    # Search demo_users
    demo_users = demo_db.search_users(q=q, role=role_filter, department=department_filter,
                                       org_id=user["org_id"], limit=limit) \
        if hasattr(demo_db, 'search_users') else []

    for u in demo_users:
        email_lower = (u.get("email") or "").lower().strip()
        if email_lower in seen_emails:
            continue
        seen_emails.add(email_lower)
        results.append({
            "id": u["id"],
            "name": u.get("name", ""),
            "email": u.get("email", ""),
            "employee_id": u.get("employee_id", ""),
            "department": u.get("department", ""),
            "role": u.get("role", ""),
            "source": "demo",
        })

    # Search live teacher_info if available
    if live_db.enabled and len(results) < limit:
        ref_users = live_db.search_reference_users(q=q, search_type=search_type,
                                                     department=department_filter,
                                                     org_id=user["org_id"],
                                                     limit=limit - len(results)) \
            if hasattr(live_db, 'search_reference_users') else []

        for r in ref_users:
            email_lower = (r.get("EMAIL_ID") or "").lower().strip()
            if email_lower in seen_emails or not email_lower:
                continue
            seen_emails.add(email_lower)
            results.append({
                "id": f"ref:{r['EMAIL_ID']}",
                "name": r.get("TEACHER_NAME") or "Unknown",
                "email": r.get("EMAIL_ID", ""),
                "employee_id": str(r.get("SAP_ID") or r.get("TEACHER_ID") or ""),
                "department": r.get("department_code") or r.get("department_name") or "",
                "role": "FACULTY",
                "source": "live",
            })

    return jsonify({"results": results[:limit]})


@api_bp.route("/departments")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def list_departments():
    """List departments for the current org."""
    from app.helpers import live_departments
    user = current_user()
    departments = live_departments(user["org_id"])
    return jsonify({"departments": departments})


@api_bp.route("/locations")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def list_locations():
    """List locations, optionally filtered by block/floor."""
    from app import get_live_db
    live_db = get_live_db()
    user = current_user()

    block = request.args.get("block", "").strip()
    floor = request.args.get("floor", "").strip()
    q = request.args.get("q", "").strip().lower()

    locations = live_db.fetch_locations() if live_db.enabled else []

    # Filter by org
    filtered = [loc for loc in locations if str(loc.get("ORG_ID", "2000")) == str(user.get("org_id", "2000"))]

    if block:
        filtered = [loc for loc in filtered if (loc.get("block") or "").lower() == block.lower()]
    if floor:
        filtered = [loc for loc in filtered if (loc.get("floor") or "").lower() == floor.lower()]
    if q:
        filtered = [loc for loc in filtered
                     if q in (loc.get("block") or "").lower()
                     or q in (loc.get("floor") or "").lower()
                     or q in (loc.get("room_no") or "").lower()
                     or q in (loc.get("name") or "").lower()]

    result = []
    for loc in filtered[:100]:
        result.append({
            "id": loc.get("id"),
            "block": loc.get("block", ""),
            "floor": loc.get("floor", ""),
            "room_no": loc.get("room_no", ""),
            "name": loc.get("name", ""),
            "label": f"{loc.get('block', '')} → {loc.get('floor', '')} → {loc.get('room_no', '')}" +
                     (f" ({loc.get('name', '')})" if loc.get("name") else ""),
        })

    return jsonify({"locations": result})


@api_bp.route("/locations/blocks")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def list_blocks():
    """List unique blocks for location selection."""
    from app import get_live_db
    live_db = get_live_db()
    user = current_user()
    locations = live_db.fetch_locations() if live_db.enabled else []
    filtered = [loc for loc in locations if str(loc.get("ORG_ID", "2000")) == str(user.get("org_id", "2000"))]
    blocks = sorted(list(set(loc.get("block", "") for loc in filtered if loc.get("block"))))
    return jsonify({"blocks": blocks})


@api_bp.route("/categories")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def list_categories():
    """List active categories, optionally filtered by department."""
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    department = request.args.get("department", "").strip() or None

    categories = demo_db.list_categories(department=department, org_id=user["org_id"], active_only=True)
    result = [{
        "id": c["id"],
        "category_name": c["category_name"],
        "department": c["department"],
        "assigned_ca_name": c.get("assigned_ca_name", ""),
    } for c in categories]

    return jsonify({"categories": result})


@api_bp.route("/tickets/<int:ticket_id>/attachment/<path:filename>")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def download_attachment(ticket_id, filename):
    """Serve ticket attachment files."""
    from flask import send_from_directory
    from app.config import UPLOAD_DIR
    from werkzeug.utils import secure_filename
    safe_name = secure_filename(filename)
    return send_from_directory(str(UPLOAD_DIR), safe_name)
