"""Tickets blueprint — create, detail, status update, reopen, export, CA dashboard, reports."""

from __future__ import annotations

import logging
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

    categories = demo_db.list_categories(org_id=user["org_id"], active_only=True)
    if request.method == "POST":
        category_id = safe_int(request.form.get("category_id", "0"))
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
        org_id = user["org_id"]
        demo_db.create_ticket(title=title, description=description, category_id=category_id,
                              created_by=user["id"], org_id=org_id, location_id=location_id)
        flash("Ticket created and auto-assigned to the mapped Concerned Authority.", "success")
        return redirect(url_for(route_for_role(user["role"])))

    locations = live_db.fetch_locations()
    return render_template("create_ticket.html", categories=categories, locations=locations,
                           departments=live_departments(user["org_id"]), **page_context("Create Ticket"))


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

    # Access check
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
        return redirect(url_for("dashboards.user_dashboard" if user["role"] == "FACULTY" else "tickets.authority_tickets"))

    activity = demo_db.list_ticket_activity(ticket_id)
    next_statuses = list(demo_db.ALLOWED_TRANSITIONS.get(ticket["status"], set()))
    can_update = user["role"] == "SUPER_ADMIN" or (
        user["role"] == "CA" and ticket["assigned_to_email"].lower() == user["email"].lower()
    )
    can_reopen = (
        ticket["status"] == "RESOLVED"
        and ticket["created_by_email"].lower() == user["email"].lower()
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
@role_required("CA", "SUPER_ADMIN")
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
@role_required("FACULTY", "CA", "HOD", "ADMIN", "SUPER_ADMIN")
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
@role_required("CA", "HOD", "ADMIN", "SUPER_ADMIN")
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
@role_required("CA")
def authority_tickets():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    own_tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    dept_tickets = demo_db.list_tickets(user, scope="department", filters=filters)

    # Dashboard summary for stat cards
    summary = demo_db.dashboard_summary(user)
    return render_template(
        "authority_tickets.html",
        assigned_tickets=assigned_tickets,
        own_tickets=own_tickets,
        dept_tickets=dept_tickets,
        filters=filters,
        summary=summary,
        **page_context("Concerned Authority"),
    )


@tickets_bp.route("/authority/dept-tickets")
@role_required("CA")
def authority_dept_tickets():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    assigned_tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    own_tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    dept_tickets = demo_db.list_tickets(user, scope="department", filters=filters)

    summary = demo_db.dashboard_summary(user)
    return render_template(
        "authority_tickets.html",
        assigned_tickets=assigned_tickets,
        own_tickets=own_tickets,
        dept_tickets=dept_tickets,
        filters=filters,
        summary=summary,
        show_dept_first=True,
        **page_context("Concerned Authority"),
    )


@tickets_bp.route("/ca/report")
@role_required("CA")
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
@role_required("SUPER_ADMIN", "ADMIN", "HOD", "CA", "FACULTY")
def export_tickets(scope, export_format):
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    filters = filters_from_request()
    if export_format not in {"csv", "xls"}:
        flash("Unsupported export format.", "error")
        return redirect(url_for(route_for_role(user["role"])))

    role = user["role"]
    if role == "FACULTY":
        tickets = demo_db.list_tickets(user, scope="own", filters=filters)
    elif role == "CA":
        if scope == "authority_own":
            tickets = demo_db.list_tickets(user, scope="own", filters=filters)
        else:
            tickets = demo_db.list_tickets(user, scope="assigned", filters=filters)
    else:
        tickets = demo_db.list_tickets(user, scope="all", filters=filters)
    return export_response(tickets, export_format, f"{scope}-{datetime.now().strftime('%Y%m%d')}")
