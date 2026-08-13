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


# Cache for location blocks
_BLOCKS_CACHE: dict[str, list[str]] = {}
_BLOCKS_CACHE_TIME: float = 0.0

@api_bp.route("/locations/blocks")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def list_blocks():
    """List unique blocks for location selection with 60s TTL memory caching."""
    global _BLOCKS_CACHE, _BLOCKS_CACHE_TIME
    import time
    from app import get_live_db
    user = current_user()
    org_id = str(user.get("org_id", "2000")) if user else "2000"
    now = time.time()

    if org_id in _BLOCKS_CACHE and (now - _BLOCKS_CACHE_TIME < 60.0):
        return jsonify({"blocks": _BLOCKS_CACHE[org_id]})

    live_db = get_live_db()
    locations = live_db.fetch_locations() if live_db.enabled else []
    filtered = [loc for loc in locations if str(loc.get("ORG_ID", "2000")) == org_id]
    blocks = sorted(list(set(loc.get("block", "") for loc in filtered if loc.get("block"))))

    _BLOCKS_CACHE[org_id] = blocks
    _BLOCKS_CACHE_TIME = now
    return jsonify({"blocks": blocks})


@api_bp.route("/users/assignees")
def list_assignees():
    """On-demand async endpoint: Fetch active users belonging ONLY to the selected department with search and limit."""
    from app import get_demo_db, get_live_db
    from app.helpers import safe_int
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    if not user:
        return jsonify({"results": [], "error": "Unauthorized"}), 401

    department = request.args.get("department", "").strip()
    search = request.args.get("search", "").strip().lower()
    limit = min(safe_int(request.args.get("limit", "20"), 20), 50)

    if not department:
        return jsonify({"results": [], "total": 0})

    results = []
    seen = set()

    # 1. Active users matching department from demo_db
    demo_users = demo_db.list_users(org_id=user["org_id"])
    for u in demo_users:
        if (u.get("department") or "").strip().lower() == department.lower():
            if str(u.get("is_active", 1)) == "0":
                continue
            name = (u.get("name") or "").strip()
            email = (u.get("email") or "").strip()
            if search and search not in name.lower() and search not in email.lower():
                continue
            seen.add(email.lower())
            results.append({
                "id": u["id"],
                "name": name,
                "email": email,
                "department": u.get("department"),
            })
            if len(results) >= limit:
                break

    # 2. Active reference users from live_db if needed
    if live_db and live_db.enabled and len(results) < limit:
        ref_users = live_db.fetch_reference_users(department=department, org_id=user["org_id"], limit=limit)
        for ru in ref_users:
            ref_email = (ru.get("email") or "").strip()
            if ref_email.lower() in seen:
                continue
            ref_name = (ru.get("name") or "").strip()
            if search and search not in ref_name.lower() and search not in ref_email.lower():
                continue
            seen.add(ref_email.lower())
            results.append({
                "id": ref_email,
                "name": ref_name,
                "email": ref_email,
                "department": department,
            })
            if len(results) >= limit:
                break

    return jsonify({"results": results, "total": len(results)})


@api_bp.route("/categories-by-department")
def categories_by_department():
    """Returns active categories matching department."""
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    department = request.args.get("department", "").strip()
    if not department:
        return jsonify([])
    org_id = user["org_id"] if user else "2000"
    cats = demo_db.list_categories(department=department, org_id=org_id, active_only=True)
    return jsonify([{"id": c["id"], "category_name": c["category_name"], "department": c["department"]} for c in cats])


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
