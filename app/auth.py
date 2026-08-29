"""Authentication blueprint — login, logout, SSO, password management."""

from __future__ import annotations

import logging
import os

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.config import (
    EMERGENCY_ADMIN_ENABLED, SSO_AUTHORIZE_URL, SSO_CLIENT_ID,
    SSO_CLIENT_SECRET, SSO_ENABLED, SSO_REDIRECT_URI, SSO_SCOPES,
    SSO_TOKEN_URL, SSO_USERINFO_URL, SSO_DEFAULT_ROLE,
    SSO_ROLE_CLAIM, SSO_DEPT_CLAIM,
)
from app.helpers import (
    clear_login_attempts, current_user, is_login_rate_limited,
    is_valid_email, page_context, record_login_attempt,
    resolve_user_org, role_required, route_for_role,
)

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/", methods=["GET", "POST"])
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()

    # If SSO is enabled and this is a GET, show SSO login page
    if request.method == "GET":
        if current_user():
            return redirect(url_for(route_for_role(session["role"])))
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    # POST — local authentication
    if not demo_db.enabled:
        flash("MySQL demo database is not configured. Start the app with MYSQL_* environment variables.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    ip = request.remote_addr
    if is_login_rate_limited(ip):
        flash("Too many failed login attempts. Please try again in 1 minute.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()

    try:
        # 1) Try demo_users first
        user = demo_db.authenticate_user(email, password)

        # 2) Auto-provision from teacher_info for institutional emails
        teacher_lookup_occurred = False
        if not user and email.endswith(("@sreenidhi.edu.in", "@suh.edu.in", "@sreegroup.edu.in")):
            if demo_db.get_user_by_email(email):
                record_login_attempt(ip)
                flash("Invalid email or password.", "error")
                return render_template("login.html", sso_enabled=SSO_ENABLED)

            teacher_lookup_occurred = True
            try:
                teacher = live_db.lookup_teacher_by_email(email)
            except Exception as e:
                log.warning("Live DB teacher lookup failed: %s", e)
                teacher = None

            if teacher and teacher.get("sap_id"):
                sap_id = str(teacher["sap_id"]).strip()
                if password == sap_id:
                    teacher_name = (teacher.get("name") or "User").strip()
                    teacher_dept = (teacher.get("department") or "").strip() or "General"
                    try:
                        user_id = demo_db.create_user({
                            "name": teacher_name,
                            "email": email,
                            "password": sap_id,
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
                        return render_template("login.html", sso_enabled=SSO_ENABLED)
    except Exception as db_err:
        log.error("Database connection error during login: %s", db_err)
        flash("Database temporarily unavailable. Please try again in a few moments.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    if not user:
        record_login_attempt(ip)
        flash("Invalid email or password.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    clear_login_attempts(ip)
    _set_session(user, email)
    return redirect(url_for(route_for_role(user["role"])))


@auth_bp.route("/admin-login", methods=["GET", "POST"])
def emergency_admin_login():
    """Hidden emergency admin login — always uses local auth."""
    if not EMERGENCY_ADMIN_ENABLED:
        return redirect(url_for("auth.login"))

    from app import get_demo_db
    demo_db = get_demo_db()

    if request.method == "GET":
        if current_user():
            return redirect(url_for(route_for_role(session["role"])))
        return render_template("login.html", sso_enabled=False, emergency_mode=True)

    if not demo_db.enabled:
        flash("Database not configured.", "error")
        return render_template("login.html", sso_enabled=False, emergency_mode=True)

    ip = request.remote_addr
    if is_login_rate_limited(ip):
        flash("Too many failed login attempts. Please try again in 1 minute.", "error")
        return render_template("login.html", sso_enabled=False, emergency_mode=True)

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    user = demo_db.authenticate_user(email, password)

    if not user:
        record_login_attempt(ip)
        flash("Invalid email or password.", "error")
        return render_template("login.html", sso_enabled=False, emergency_mode=True)

    clear_login_attempts(ip)
    _set_session(user, email)
    return redirect(url_for(route_for_role(user["role"])))


@auth_bp.route("/sso/login", methods=["GET", "POST"])
def sso_login():
    """Redirect to Google / OIDC SSO provider, or handle mock SSO if unconfigured."""
    from app.config import (
        GOOGLE_CLIENT_ID, GOOGLE_HOSTED_DOMAIN, SSO_AUTHORIZE_URL,
        SSO_CLIENT_ID, SSO_ENABLED, SSO_SCOPES,
    )
    if not SSO_ENABLED:
        flash("SSO is not configured.", "error")
        return redirect(url_for("auth.login"))

    client_id = GOOGLE_CLIENT_ID or SSO_CLIENT_ID

    # If no client ID configured or set to mock, use mock SSO simulator
    if not client_id or SSO_AUTHORIZE_URL == "mock" or client_id == "snist-helpdesk-client":
        if request.method == "POST":
            email = request.form.get("email", "faculty@sreenidhi.edu.in").strip().lower()
            role = request.form.get("role", "FACULTY").strip().upper()
            dept = request.form.get("department", "CSE").strip()
            name = request.form.get("name", "").strip() or email.split("@")[0].replace(".", " ").title()

            from app import get_demo_db, get_live_db
            demo_db = get_demo_db()
            live_db = get_live_db()

            existing = demo_db.get_user_by_email(email)
            if existing:
                user = existing
            else:
                teacher = live_db.lookup_teacher_by_email(email) if live_db.enabled else None
                if teacher:
                    name = teacher.get("name") or name
                    dept = teacher.get("department") or dept

                import secrets as _s
                user_id = demo_db.create_user({
                    "name": name,
                    "email": email,
                    "password": _s.token_hex(16),
                    "role": role,
                    "department": dept,
                })
                user = {"id": user_id, "name": name, "email": email, "role": role, "department": dept}

            _set_session(user, email)
            flash(f"Signed in via Google SSO ({email}).", "success")
            return redirect(url_for(route_for_role(user["role"])))

        return render_template("mock_sso.html", default_email="faculty@sreenidhi.edu.in")

    import secrets
    import urllib.parse

    state = secrets.token_urlsafe(32)
    session["sso_state"] = state

    params = {
        "client_id": client_id,
        "redirect_uri": url_for("auth.sso_callback", _external=True),
        "response_type": "code",
        "scope": SSO_SCOPES,
        "state": state,
        "prompt": "select_account",
    }
    if GOOGLE_HOSTED_DOMAIN:
        params["hd"] = GOOGLE_HOSTED_DOMAIN

    query = urllib.parse.urlencode(params)
    authorize_endpoint = SSO_AUTHORIZE_URL if SSO_AUTHORIZE_URL.startswith("http") else "https://accounts.google.com/o/oauth2/v2/auth"
    return redirect(f"{authorize_endpoint}?{query}")


@auth_bp.route("/sso/callback")
def sso_callback():
    """Handle SSO provider callback with authorization code."""
    if not SSO_ENABLED:
        return redirect(url_for("auth.login"))

    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()

    error = request.args.get("error")
    if error:
        flash(f"SSO authentication failed: {error}", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or state != session.pop("sso_state", None):
        flash("Invalid SSO response. Please try again.", "error")
        return redirect(url_for("auth.login"))

    try:
        import urllib.request
        import urllib.parse
        import json

        if not SSO_TOKEN_URL:
            # Fallback for dev callback simulation
            email = "sso.user@sreenidhi.edu.in"
            name = "SSO Institutional User"
            userinfo = {"email": email, "name": name}
        else:
            # Exchange code for tokens
            token_data = urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "client_id": SSO_CLIENT_ID,
                "client_secret": SSO_CLIENT_SECRET,
                "code": code,
                "redirect_uri": SSO_REDIRECT_URI or url_for("auth.sso_callback", _external=True),
            }).encode()

            token_req = urllib.request.Request(SSO_TOKEN_URL, data=token_data,
                                               headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(token_req, timeout=10) as resp:
                token_resp = json.loads(resp.read())

            access_token = token_resp.get("access_token")
            if not access_token:
                raise ValueError("No access token in response")

            # Fetch user info
            userinfo_req = urllib.request.Request(SSO_USERINFO_URL,
                                                  headers={"Authorization": f"Bearer {access_token}"})
            with urllib.request.urlopen(userinfo_req, timeout=10) as resp:
                userinfo = json.loads(resp.read())

        email = (userinfo.get("email") or "").lower().strip()
        name = userinfo.get("name") or userinfo.get("preferred_username") or email.split("@")[0]

        if not email:
            raise ValueError("No email in SSO user info")

        # Resolve role from IdP claims or default
        role = SSO_DEFAULT_ROLE
        if SSO_ROLE_CLAIM and SSO_ROLE_CLAIM in userinfo:
            claimed_role = str(userinfo[SSO_ROLE_CLAIM]).upper()
            if claimed_role in ("SUPER_ADMIN", "ADMIN", "HOD", "CA", "FACULTY"):
                role = claimed_role

        department = "General"
        if SSO_DEPT_CLAIM and SSO_DEPT_CLAIM in userinfo:
            department = str(userinfo[SSO_DEPT_CLAIM]).strip()

        # Auto-provision or update user
        existing = demo_db.get_user_by_email(email)
        if existing:
            # Update profile from SSO
            demo_db.update_user(existing["id"], {
                "name": name,
                "email": email,
            })
            user = {
                "id": existing["id"],
                "name": name,
                "email": email,
                "role": existing["role"],
                "department": existing["department"],
            }
        else:
            # Try to resolve department from teacher_info
            teacher = live_db.lookup_teacher_by_email(email) if live_db.enabled else None
            if teacher:
                department = (teacher.get("department") or department).strip()
                name = (teacher.get("name") or name).strip()

            import secrets as _s
            user_id = demo_db.create_user({
                "name": name,
                "email": email,
                "password": _s.token_hex(16),  # random password (SSO users won't use it)
                "role": role,
                "department": department,
            })
            user = {
                "id": user_id,
                "name": name,
                "email": email,
                "role": role,
                "department": department,
            }
            log.info("Auto-provisioned SSO user %s (%s) as %s.", name, email, role)

        _set_session(user, email)
        return redirect(url_for(route_for_role(user["role"])))

    except Exception as exc:
        log.error("SSO callback failed: %s", exc)
        flash("SSO authentication failed. Please try again or contact your administrator.", "error")
        return redirect(url_for("auth.login"))


@auth_bp.route("/change-password", methods=["GET", "POST"])
@role_required("ADMIN", "HOD", "CA", "FACULTY")
def change_password():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()

    if request.method == "POST":
        old_password = request.form.get("old_password", "").strip()
        new_password = request.form.get("new_password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        if not old_password or not new_password:
            flash("All fields are required.", "error")
            return redirect(url_for("auth.change_password"))
        if len(new_password) < 4:
            flash("New password must be at least 4 characters.", "error")
            return redirect(url_for("auth.change_password"))
        if new_password != confirm_password:
            flash("New password and confirmation do not match.", "error")
            return redirect(url_for("auth.change_password"))
        try:
            if not demo_db.change_password(user["id"], old_password, new_password):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("auth.change_password"))
            flash("Password changed successfully.", "success")
            return redirect(url_for("auth.change_password"))
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("auth.change_password"))
    return render_template("change_password.html", **page_context("Change Password"))


@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("auth.login"))


def _set_session(user: dict, email: str) -> None:
    """Populate session after successful login."""
    from app import get_live_db
    live_db = get_live_db()
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]
    session["role"] = user["role"]
    session["department"] = user["department"]
    session["org_id"] = user.get("org_id") or resolve_user_org(email, user["department"], live_db)
