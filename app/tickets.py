"""Tickets blueprint — create, detail, status update, reopen, export, CA dashboard, reports."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

from app.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_SIZE, UPLOAD_DIR
from app.helpers import (
    allowed_file, current_user, export_response, filters_from_request,
    live_departments, page_context, role_required, route_for_role,
    safe_int, verify_file_signature,
)

log = logging.getLogger(__name__)

tickets_bp = Blueprint("tickets", __name__)


@tickets_bp.route("/tickets/create", methods=["GET", "POST"])
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def create_ticket_for_role():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    user_dept = (user.get("department") or "").strip()

    all_depts = live_departments(user["org_id"])
    matched_dept = next((d for d in all_depts if d["code"].lower() == user_dept.lower() or d["name"].lower() == user_dept.lower()), None)
    user_dept_code = matched_dept["code"] if matched_dept else user_dept
    user_dept_name = matched_dept["name"] if matched_dept else user_dept

    # Build list of departments that have at least one active category (for the dropdown)
    all_active_cats = demo_db.list_categories(org_id=user["org_id"], active_only=True)
    depts_with_active_cats = {(c.get("department") or "").strip() for c in all_active_cats if c.get("department")}
    available_depts = [d for d in all_depts if d["code"] in depts_with_active_cats or d["name"] in depts_with_active_cats]
    # Ensure the user's own dept appears first when it has active categories
    available_depts.sort(key=lambda d: (0 if d["code"] == user_dept_code else 1, d["name"]))

    if request.method == "POST":
        category_id = safe_int(request.form.get("category_id", "0"))
        selected_dept = (request.form.get("department", "") or user_dept_code).strip()
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        location_id = safe_int(request.form.get("location_id", "0")) or None
        if not category_id:
            flash("Category is required.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))
        if not description:
            flash("Description is required.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))
        if title and len(title) > 180:
            flash("Title cannot exceed 180 characters.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))
        if len(description) > 5000:
            flash("Description cannot exceed 5000 characters.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))

        # Server-side security validation
        category = demo_db.get_category(category_id)
        if not category:
            flash("Selected category does not exist.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))

        if category.get("is_active") == 0:
            flash("Selected category is inactive.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))

        cat_dept = (category.get("department") or "").strip()
        matched_sel_dept = next((d for d in all_depts if d["code"].lower() == selected_dept.lower() or d["name"].lower() == selected_dept.lower()), None)
        valid_selected_codes = {selected_dept.lower()}
        if matched_sel_dept:
            valid_selected_codes.add(matched_sel_dept["code"].lower())
            valid_selected_codes.add(matched_sel_dept["name"].lower())

        if cat_dept.lower() not in valid_selected_codes:
            flash("Selected category does not belong to the selected department.", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))

        if user["role"] not in ("SUPER_ADMIN", "ADMIN"):
            if cat_dept not in depts_with_active_cats and (matched_sel_dept and matched_sel_dept["code"] not in depts_with_active_cats):
                flash("The selected department has no active categories.", "error")
                return redirect(url_for("tickets.create_ticket_for_role"))

        org_id = user["org_id"]
        submission_key = request.form.get("submission_key", "").strip() or None
        try:
            demo_db.create_ticket(title=title, description=description, category_id=category_id,
                                  created_by=user["id"], org_id=org_id, location_id=location_id,
                                  submission_key=submission_key)
            flash("Ticket created and auto-assigned to the mapped Assignee.", "success")
            return redirect(url_for(route_for_role(user["role"])))
        except Exception as e:
            flash(f"Ticket creation failed: {e}", "error")
            return redirect(url_for("tickets.create_ticket_for_role"))

    # Default: show categories for the user's own department initially
    selected_dept = request.args.get("dept", user_dept_code).strip()
    categories = demo_db.list_categories(department=selected_dept, org_id=user["org_id"], active_only=True)
    if not categories and user_dept_name != user_dept_code:
        categories = demo_db.list_categories(department=user_dept_name, org_id=user["org_id"], active_only=True)

    locations = live_db.fetch_locations()
    return render_template(
        "create_ticket.html",
        categories=categories,
        locations=locations,
        user_dept_code=user_dept_code,
        user_dept_name=user_dept_name,
        current_user_dept=user_dept,
        departments=all_depts,
        available_depts=available_depts,
        selected_dept=selected_dept,
        submission_key=str(uuid.uuid4()),
        **page_context("Create Ticket"),
    )


@tickets_bp.route("/tickets/<int:ticket_id>")
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def ticket_detail(ticket_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    ticket = demo_db.get_ticket(ticket_id)
    if not ticket:
        flash("Ticket not found.", "error")
        return redirect(url_for("dashboards.user_dashboard" if user["role"] == "FACULTY" else "tickets.authority_tickets"))

    created_email = (ticket.get("created_by_email") or "").lower()
    assigned_email = (ticket.get("assigned_to_email") or "").lower()
    user_email = (user.get("email") or "").lower()

    # Access check
    allowed = False
    if user["role"] in ("SUPER_ADMIN", "ADMIN"):
        allowed = True
    elif user["role"] == "HOD" and ticket.get("department") == user.get("department"):
        allowed = True
    elif created_email and created_email == user_email:
        allowed = True
    elif assigned_email and assigned_email == user_email:
        allowed = True
    if not allowed or ticket.get("org_id") != user.get("org_id"):
        flash("You do not have access to this ticket.", "error")
        return redirect(url_for("dashboards.user_dashboard" if user["role"] == "FACULTY" else "tickets.authority_tickets"))

    activity = demo_db.list_ticket_activity(ticket_id)
    assigned_email = ticket.get("assigned_to_email") or ""
    created_email = ticket.get("created_by_email") or ""
    user_email = user.get("email") or ""
    next_statuses = list(demo_db.ALLOWED_TRANSITIONS.get(ticket.get("status", ""), set()))
    
    can_update = (
        user.get("role") in ["CA", "ASSIGNEE"] and (
            (assigned_email and user_email and assigned_email.lower() == user_email.lower())
            or (ticket.get("assigned_to") and ticket.get("assigned_to") == user.get("id"))
        )
    ) or (
        user.get("role") == "HOD" and user.get("department") == ticket.get("department")
    )
    
    can_reopen = (
        ticket.get("status") == "RESOLVED"
        and (
            (created_email and user_email and created_email.lower() == user_email.lower())
            or (ticket.get("created_by") and ticket.get("created_by") == user.get("id"))
        )
    )


    # Fetch internal notes
    notes = demo_db.list_ticket_notes(ticket_id) if hasattr(demo_db, 'list_ticket_notes') else []

    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        activity=activity,
        notes=notes,
        next_statuses=next_statuses,
        can_update=can_update,
        can_reopen=can_reopen,
        **page_context("Ticket #" + str(ticket_id)),
    )


@tickets_bp.route("/authority/update-status/<int:ticket_id>", methods=["POST"])
@role_required("ASSIGNEE", "CA", "HOD")
def authority_update_status(ticket_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    status = request.form.get("status", "").strip().upper()
    remarks = request.form.get("remarks", "").strip()
    time_taken = request.form.get("time_taken", "").strip()
    attachment = request.files.get("attachment")

    if status not in {"PENDING", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "REOPENED"}:
        flash("Invalid status selected.", "error")
        return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
    if status == "RESOLVED" and not remarks:
        flash("Resolution remarks are required.", "error")
        return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))

    attachment_path = ""
    if attachment and attachment.filename:
        if not allowed_file(attachment.filename) or not verify_file_signature(attachment):
            flash(f"File type not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}.", "error")
            return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
        attachment.seek(0, 2)
        size = attachment.tell()
        attachment.seek(0)
        if size > MAX_UPLOAD_SIZE:
            flash(f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024 * 1024)} MB.", "error")
            return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
        safe_name = secure_filename(attachment.filename)
        attachment_name = f"{ticket_id}-{int(datetime.now().timestamp())}-{safe_name}"
        attachment.save(str(UPLOAD_DIR / attachment_name))
        attachment_path = attachment_name

    try:
        demo_db.update_ticket_status(ticket_id, actor=user, status=status, remarks=remarks,
                                     time_taken=time_taken, attachment_path=attachment_path)
        flash("Ticket updated successfully.", "success")
    except PermissionError:
        flash("You do not have access to that page.", "error")
        return redirect(url_for(route_for_role(user["role"])))
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))


@tickets_bp.route("/tickets/<int:ticket_id>/reopen", methods=["POST"])
@role_required("FACULTY", "ASSIGNEE", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def reopen_ticket(ticket_id):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    remarks = request.form.get("remarks", "").strip()
    if not remarks:
        flash("Please provide a reason for reopening.", "error")
        return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
    try:
        demo_db.update_ticket_status(ticket_id, actor=user, status="REOPENED", remarks=remarks)
        flash("Ticket has been reopened.", "success")
    except PermissionError as exc:
        flash(str(exc), "error")
    except ValueError as exc:
        flash(str(exc), "error")
    return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))


@tickets_bp.route("/tickets/<int:ticket_id>/notes", methods=["POST"])
@role_required("ASSIGNEE", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
def add_ticket_note(ticket_id):
    """Add an internal note to a ticket."""
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    note_text = request.form.get("note", "").strip()
    is_internal = request.form.get("is_internal", "1") == "1"
    if not note_text:
        flash("Note cannot be empty.", "error")
        return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
    try:
        demo_db.add_ticket_note(ticket_id, user["id"], note_text, is_internal)
        flash("Note added successfully.", "success")
    except Exception as exc:
        flash(f"Failed to add note: {exc}", "error")
    return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))


@tickets_bp.route("/authority/tickets")
@role_required("ASSIGNEE", "CA")
def authority_tickets():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    own_tickets = demo_db.list_tickets(user, scope="own", filters=filters)

    # Dashboard summary for stat cards
    summary = demo_db.dashboard_summary(user)
    return render_template(
        "authority_tickets.html",
        assigned_tickets=assigned_tickets,
        own_tickets=own_tickets,
        filters=filters,
        summary=summary,
        **page_context("Assignee"),
    )


@tickets_bp.route("/authority/my-tickets")
@role_required("ASSIGNEE", "CA")
def authority_my_tickets():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    return render_template(
        "my_tickets.html",
        tickets=tickets,
        filters=filters,
        form_action="tickets.authority_my_tickets",
        export_scope="authority_own",
        **page_context("Assignee"),
    )


@tickets_bp.route("/authority/assigned-tickets")
@tickets_bp.route("/authority/dept-tickets")
@tickets_bp.route("/authority/all-tickets")
@role_required("ASSIGNEE", "CA")
def authority_assigned_tickets():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    filters = filters_from_request()
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    departments = live_departments(user.get("org_id"))
    locations = live_db.fetch_locations() if live_db.enabled else []
    return render_template(
        "management_all_tickets.html",
        tickets=assigned_tickets,
        filters=filters,
        departments=departments,
        locations=locations,
        export_scope="authority_assigned",
        page_title="Assignee Tickets Repository",
        **page_context("Assignee"),
    )


@tickets_bp.route("/ca/report")
@role_required("ASSIGNEE", "CA")
def ca_report():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    filters["status"] = "RESOLVED"
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)

    for t in assigned_tickets:
        if t.get("created_at") and t.get("updated_at"):
            try:
                created = datetime.fromisoformat(str(t["created_at"]))
                updated = datetime.fromisoformat(str(t["updated_at"]))
                diff = updated - created
                days = diff.days
                hours, remainder = divmod(diff.seconds, 3600)
                minutes, _ = divmod(remainder, 60)
                parts = []
                if days > 0:
                    parts.append(f"{days}d")
                if hours > 0:
                    parts.append(f"{hours}h")
                if minutes > 0:
                    parts.append(f"{minutes}m")
                t["time_taken"] = " ".join(parts) if parts else "< 1m"
            except Exception:
                t["time_taken"] = "N/A"
        else:
            t["time_taken"] = "N/A"

    return render_template("ca_report.html", resolved_tickets=assigned_tickets,
                           filters=filters, **page_context("CA Report"))


@tickets_bp.route("/tickets/export/<scope>.<export_format>")
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "ASSIGNEE", "FACULTY")
def export_tickets(scope, export_format):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    if export_format not in {"csv", "xls"}:
        flash("Unsupported export format.", "error")
        return redirect(url_for(route_for_role(user["role"])))

    role = user["role"]
    if scope in ("authority_own", "faculty_own", "super_admin_own", "admin_own", "hod_own", "my_tickets", "own") or role == "FACULTY":
        tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    elif scope in ("authority_assigned", "assigned"):
        tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    elif scope in ("authority_dept", "dept", "department"):
        tickets = demo_db.list_tickets(user, scope="department", filters=filters)
    else:
        tickets = demo_db.list_tickets(user, scope="all", filters=filters)

    return export_response(tickets, export_format, f"{scope}-{datetime.now().strftime('%Y%m%d')}")
