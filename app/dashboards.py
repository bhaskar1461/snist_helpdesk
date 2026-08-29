"""Dashboards blueprint — role-specific dashboards, impersonation, all-tickets views."""

from __future__ import annotations

import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.config import ORG_LABELS
from app.helpers import (
    current_user, filters_from_request, live_departments, page_context,
    role_required, route_for_role,
)

log = logging.getLogger(__name__)

dashboards_bp = Blueprint("dashboards", __name__)


@dashboards_bp.route("/super-admin/dashboard")
@role_required("SUPER_ADMIN")
def super_admin_dashboard():
    from app import get_demo_db
    demo_db = get_demo_db()
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
        page_heading=f"{org_label} Super Admin Overview",
        highlight_title="HOD Overview",
        highlight_note="",
        primary_cta=("management.category_assignments", "Assignee Management"),
        secondary_cta=("dashboards.super_admin_all_tickets", "View All Tickets"),
        **page_context("Super Admin"),
    )


@dashboards_bp.route("/admin/dashboard")
@role_required("ADMIN")
def admin_dashboard():
    from app import get_demo_db
    demo_db = get_demo_db()
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
        page_heading="Admin Panel",
        highlight_title="Recent Users",
        highlight_note="",
        primary_cta=("management.category_assignments", "Assignee Management"),
        secondary_cta=("dashboards.admin_all_tickets", "View Tickets"),
        **page_context("Admin"),
    )


@dashboards_bp.route("/hod/dashboard")
@role_required("HOD")
def hod_dashboard():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    highlights = demo_db.list_categories(department=user["department"])
    return render_template(
        "management_dashboard.html",
        summary=summary,
        highlights=highlights,
        page_title="HOD Dashboard",
        kicker="Department Control",
        page_heading=f"{user['department']} HOD Dashboard",
        highlight_title="Category to Assignee Mapping",
        highlight_note="",
        primary_cta=("management.management_category", "Assignee Management"),
        secondary_cta=("dashboards.hod_all_tickets", "View Department Tickets"),
        **page_context("HOD"),
    )


@dashboards_bp.route("/user/dashboard")
@role_required("FACULTY")
def user_dashboard():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    summary = demo_db.dashboard_summary(user)
    tickets = demo_db.list_tickets(user, scope="own")
    return render_template("user_dashboard.html", summary=summary, tickets=tickets[:5],
                           **page_context("User"))


@dashboards_bp.route("/user/my-tickets")
@role_required("FACULTY")
def my_tickets():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    tickets = demo_db.list_tickets(user, scope="own", filters=filters_from_request())
    return render_template("my_tickets.html", tickets=tickets, filters=filters_from_request(),
                           **page_context("My Tickets"))


# ── All Tickets Views ───────────────────────────────────────────────

def render_all_tickets(role_title, endpoint_name):
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()
    user = current_user()
    filters = filters_from_request()
    tickets = demo_db.list_tickets(user, scope="all", filters=filters)
    departments = live_departments()
    locations = live_db.fetch_locations() if live_db.enabled else []
    return render_template(
        "management_all_tickets.html",
        tickets=tickets,
        filters=filters,
        departments=departments,
        locations=locations,
        export_scope=endpoint_name,
        **page_context(role_title),
    )


@dashboards_bp.route("/super-admin/all-tickets")
@role_required("SUPER_ADMIN")
def super_admin_all_tickets():
    return render_all_tickets("Super Admin", "super_admin_all_tickets")


@dashboards_bp.route("/admin/all-tickets")
@role_required("ADMIN")
def admin_all_tickets():
    return render_all_tickets("Admin", "admin_all_tickets")


@dashboards_bp.route("/hod/all-tickets")
@role_required("HOD")
def hod_all_tickets():
    return render_all_tickets("HOD", "hod_all_tickets")


# ── Impersonation ───────────────────────────────────────────────────

@dashboards_bp.route("/impersonate-hod", methods=["POST"])
@role_required("SUPER_ADMIN", "ADMIN")
def impersonate_hod():
    from app import get_demo_db
    demo_db = get_demo_db()
    department = request.form.get("department", "").strip()
    if not department:
        flash("Department is required to impersonate HOD.", "error")
        return redirect(url_for(route_for_role(session["role"])))
    session["acting_role"] = "HOD"
    session["acting_department"] = department
    from app.helpers import resolve_user_org
    from app import get_live_db
    session["available_departments"] = [d["code"] for d in live_departments(
        session.get("org_id") or resolve_user_org(session["user_email"], session["department"], get_live_db())
    )]
    demo_db.log_audit_event(
        "IMPERSONATION_START", session["user_id"],
        session.get("org_id", ""),
        target_type="department", target_id=None,
        details={"department": department, "original_role": session["role"]},
    )
    flash(f"Now acting as HOD for {department} department.", "success")
    return redirect(url_for("dashboards.hod_dashboard"))


@dashboards_bp.route("/exit-hod-mode")
@role_required("HOD")
def exit_hod_mode():
    from app import get_demo_db
    demo_db = get_demo_db()
    acting_dept = session.get("acting_department", "")
    if "acting_role" in session:
        del session["acting_role"]
    if "acting_department" in session:
        del session["acting_department"]
    if "available_departments" in session:
        del session["available_departments"]
    demo_db.log_audit_event(
        "IMPERSONATION_STOP", session["user_id"],
        session.get("org_id", ""),
        target_type="department", target_id=None,
        details={"department": acting_dept},
    )
    flash("Stopped impersonating HOD.", "success")
    return redirect(url_for(route_for_role(session["role"])))


@dashboards_bp.route("/switch-acting-department", methods=["POST"])
@role_required("HOD")
def switch_acting_department():
    from app import get_demo_db
    demo_db = get_demo_db()
    if "acting_role" not in session:
        flash("You are not currently impersonating HOD.", "error")
        return redirect(url_for(route_for_role(session["role"])))
    old_dept = session.get("acting_department", "")
    department = request.form.get("department", "").strip()
    if not department:
        flash("Invalid department selected.", "error")
        return redirect(url_for("dashboards.hod_dashboard"))
    session["acting_department"] = department
    demo_db.log_audit_event(
        "IMPERSONATION_SWITCH", session["user_id"],
        session.get("org_id", ""),
        target_type="department", target_id=None,
        details={"from_department": old_dept, "to_department": department},
    )
    flash(f"Switched acting HOD department to {department}.", "success")
    return redirect(url_for("dashboards.hod_dashboard"))
