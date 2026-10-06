"""REST API blueprint — user search autocomplete, department/location lookups, and data APIs."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.helpers import current_user, role_required, safe_int, departments_match, resolve_user_org

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
                "id": r.get("TEACHER_ID") or r.get("id") or r['EMAIL_ID'],
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
                "id": ru.get("id") or ru.get("TEACHER_ID") or ref_email,
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
    """Serve ticket attachment files with strict IDOR access control and traversal defense."""
    from flask import abort, send_file
    from app import get_demo_db
    from app.config import UPLOAD_DIR
    from app.helpers import current_user
    from app.security import can_user_access_ticket_attachment, validate_attachment_path

    user = current_user()
    demo_db = get_demo_db()
    ticket = demo_db.get_ticket(ticket_id)
    if not ticket:
        abort(404)

    if not can_user_access_ticket_attachment(user, ticket):
        abort(404)

    safe_file_path = validate_attachment_path(filename, UPLOAD_DIR)
    if not safe_file_path:
        abort(404)

    file_ticket_id = demo_db.get_attachment_ticket_id(filename)
    if file_ticket_id is not None and file_ticket_id != ticket_id:
        abort(404)

    resp = send_file(safe_file_path, as_attachment=False)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


# ── User Management REST APIs ───────────────────────────────────────

@api_bp.route("/users/<int:user_id>", methods=["GET"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "FACULTY")
def api_get_user(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = demo_db.get_user(user_id)
    if not user:
        return jsonify({"error": "User not found."}), 404
    cats = demo_db.list_ca_categories(user_id) if hasattr(demo_db, "list_ca_categories") else []
    return jsonify({"user": user, "categories": cats}), 200


@api_bp.route("/users/<int:user_id>", methods=["PUT", "PATCH"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_update_user(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    actor = current_user()
    data = request.get_json(silent=True) or {}
    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404

    target_org = resolve_user_org(target_user.get("email"), target_user.get("department"))
    if target_org != actor.get("org_id"):
        return jsonify({"error": "Access denied: User belongs to a different organization."}), 403

    if actor["role"] == "HOD":
        target_depts = [d.strip().lower() for d in (target_user.get("department") or "").split(",")]
        if actor["department"].lower() not in target_depts:
            return jsonify({"error": "Access denied: You can only modify users in your own department."}), 403

    try:
        demo_db.update_user(user_id, data)
        updated = demo_db.get_user(user_id)
        return jsonify({"message": "User updated successfully.", "user": updated}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Failed to update user: {exc}"}), 500


@api_bp.route("/users/<int:user_id>", methods=["DELETE"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_delete_user(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    actor = current_user()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404

    target_org = resolve_user_org(target_user.get("email"), target_user.get("department"))
    if target_org != actor.get("org_id"):
        return jsonify({"error": "Access denied: User belongs to a different organization."}), 403

    if actor["role"] == "HOD":
        target_depts = [d.strip().lower() for d in (target_user.get("department") or "").split(",")]
        if actor["department"].lower() not in target_depts:
            return jsonify({"error": "Access denied: You can only delete users in your own department."}), 403

    try:
        res = demo_db.delete_user(user_id)
        return jsonify({"message": "User deleted or deactivated successfully.", "result": res}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ── CA Category Assignment REST APIs ────────────────────────────────

@api_bp.route("/users/<int:user_id>/categories", methods=["GET"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA")
def api_get_ca_categories(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404
    cats = demo_db.list_ca_categories(user_id)
    return jsonify({"categories": cats, "user_id": user_id}), 200


@api_bp.route("/users/<int:user_id>/categories", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_add_ca_category(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    actor = current_user()
    data = request.get_json(silent=True) or {}
    category_id = safe_int(data.get("category_id"))
    block = data.get("block", "All Blocks").strip() or "All Blocks"

    if not category_id:
        return jsonify({"error": "category_id is required."}), 400

    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404

    category = demo_db.get_category(category_id)
    if not category:
        return jsonify({"error": "Category not found."}), 404

    # Validate department match
    if not departments_match(target_user.get("department"), category.get("department")):
        return jsonify({"error": "Unable to assign category: department mismatch between CA and category."}), 400

    try:
        demo_db.create_ca_assignment(category_id, user_id, block=block)
        return jsonify({"message": "Category assigned successfully.", "category_id": category_id, "user_id": user_id}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.route("/users/<int:user_id>/categories/<int:category_id>", methods=["DELETE"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_remove_ca_category(user_id, category_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404
    category = demo_db.get_category(category_id)
    if not category:
        return jsonify({"error": "Category not found."}), 404

    try:
        demo_db.remove_ca_from_category(category_id, user_id)
        return jsonify({"message": "Category unassigned successfully."}), 200
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@api_bp.route("/users/<int:user_id>/categories", methods=["PUT"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_reassign_ca_category(user_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    actor = current_user()
    data = request.get_json(silent=True) or {}
    old_cat_id = safe_int(data.get("old_category_id"))
    new_cat_id = safe_int(data.get("new_category_id") or data.get("category_id"))
    block = data.get("block", "All Blocks").strip() or "All Blocks"

    if not new_cat_id:
        return jsonify({"error": "new_category_id is required."}), 400

    target_user = demo_db.get_user(user_id)
    if not target_user:
        return jsonify({"error": "User not found."}), 404

    new_cat = demo_db.get_category(new_cat_id)
    if not new_cat:
        return jsonify({"error": "New category not found."}), 404

    if not departments_match(target_user.get("department"), new_cat.get("department")):
        return jsonify({"error": "Unable to assign category: department mismatch between CA and category."}), 400

    if old_cat_id:
        try:
            demo_db.remove_ca_from_category(old_cat_id, user_id)
        except Exception:
            pass

    demo_db.create_ca_assignment(new_cat_id, user_id, block=block)
    return jsonify({"message": "Category reassigned successfully.", "category_id": new_cat_id}), 200


# ── Category Deletion REST API ──────────────────────────────────────

@api_bp.route("/categories/<int:category_id>", methods=["DELETE"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD")
def api_delete_category(category_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    cat = demo_db.get_category(category_id)
    if not cat:
        return jsonify({"error": "Category not found."}), 404

    with demo_db.connection() as conn, conn.cursor() as cur:
        # Check if category is referenced by existing tickets
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM helpdesk_tickets WHERE category_id = %s",
            (category_id,),
        )
        row = cur.fetchone()
        ticket_count = row["cnt"] if row else 0
        if ticket_count > 0:
            return jsonify({
                "error": "Unable to remove category: category is referenced by existing tickets."
            }), 400

        cur.execute(
            "UPDATE helpdesk_categories SET is_active = 0 WHERE id = %s",
            (category_id,),
        )
    return jsonify({"message": "Category removed/deactivated successfully."}), 200


# ── Ticket Status REST API ──────────────────────────────────────────

@api_bp.route("/tickets/<int:ticket_id>/status", methods=["POST", "PUT"])
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "ASSIGNEE", "FACULTY")
def api_update_ticket_status(ticket_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    data = request.get_json(silent=True) or {}
    raw_status = (data.get("status") or "").strip()
    remarks = (data.get("remarks") or "").strip()

    if not raw_status:
        return jsonify({"error": "status is required."}), 400

    status = raw_status.upper().replace(" ", "_")
    if status in ("CLOSED", "RESOLVE"):
        status = "RESOLVED"
    elif status == "INPROGRESS":
        status = "IN_PROGRESS"
    elif status == "ONHOLD":
        status = "ON_HOLD"

    if status not in {"PENDING", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "REOPENED"}:
        return jsonify({"error": f"Invalid status: {raw_status}"}), 400

    if status == "RESOLVED" and not remarks:
        remarks = "Ticket resolved directly by CA."

    try:
        demo_db.update_ticket_status(
            ticket_id,
            actor=user,
            status=status,
            remarks=remarks,
            time_taken=(data.get("time_taken") or "").strip(),
            attachment_path=(data.get("attachment_path") or "").strip(),
        )
        return jsonify({"message": "Ticket updated successfully.", "status": status}), 200
    except PermissionError as exc:
        return jsonify({"error": str(exc) or "Forbidden: Access denied."}), 403
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

