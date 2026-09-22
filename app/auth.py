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
    is_valid_email, normalize_role, page_context, record_login_attempt,
    resolve_user_org, role_required, route_for_role,
)

from app.security import check_login_rate_limit, record_login_attempt as db_record_login_attempt

log = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


def _get_sso_redirect_uri() -> str:
    """Resolve authoritative SSO redirect URI, ensuring HTTPS in production."""
    from app.config import SSO_REDIRECT_URI
    if SSO_REDIRECT_URI:
        uri = SSO_REDIRECT_URI
    else:
        uri = url_for("auth.sso_callback", _external=True)

    # Force HTTPS when running on production domain or behind proxy
    host = (request.host or "").lower()
    is_prod_domain = "sreenidhi.edu.in" in host or "1sports.app" in host
    if uri.startswith("http://") and (is_prod_domain or request.is_secure or request.headers.get("X-Forwarded-Proto") == "https"):
        uri = "https://" + uri[len("http://"):]
    return uri


@auth_bp.route("/", methods=["GET", "POST"])
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    from app import get_demo_db, get_live_db
    demo_db = get_demo_db()
    live_db = get_live_db()

    # If SSO is enabled and this is a GET, check if user is already authenticated
    if request.method == "GET":
        user = current_user()
        if user and session.get("user_id"):
            target_endpoint = route_for_role(user.get("role"))
            if target_endpoint and target_endpoint != "auth.login":
                target_url = url_for(target_endpoint)
                if target_url != request.path and target_url != request.url:
                    return redirect(target_url)
            # If target resolves back to login or session has unroutable state, clear it
            session.clear()
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    # POST — local authentication
    if not demo_db.enabled:
        flash("MySQL demo database is not configured. Start the app with MYSQL_* environment variables.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()

    # Distributed rate limit check BEFORE password verification (prevents timing oracles)
    is_limited, limit_msg = check_login_rate_limit(demo_db, email, ip)
    if is_limited:
        flash(limit_msg or "Too many failed login attempts. Please try again later.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    try:
        # Authenticate user directly (checks staff roles and authoritative teacher_info)
        user = demo_db.authenticate_user(email, password)
    except Exception as db_err:
        log.error("Database connection error during login: %s", db_err)
        flash("Database temporarily unavailable. Please try again in a few moments.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    if not user:
        db_record_login_attempt(demo_db, email, ip, outcome="FAILURE")
        record_login_attempt(ip)  # In-memory backwards compatibility
        flash("Invalid email or password.", "error")
        return render_template("login.html", sso_enabled=SSO_ENABLED)

    db_record_login_attempt(demo_db, email, ip, outcome="SUCCESS")
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

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "").strip()
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "127.0.0.1").split(",")[0].strip()

    is_limited, limit_msg = check_login_rate_limit(demo_db, email, ip)
    if is_limited:
        flash(limit_msg or "Too many failed login attempts. Please try again later.", "error")
        return render_template("login.html", sso_enabled=False, emergency_mode=True)

    user = demo_db.authenticate_user(email, password)

    if not user:
        db_record_login_attempt(demo_db, email, ip, outcome="FAILURE")
        record_login_attempt(ip)
        flash("Invalid email or password.", "error")
        return render_template("login.html", sso_enabled=False, emergency_mode=True)

    db_record_login_attempt(demo_db, email, ip, outcome="SUCCESS")
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

    # Support developer / test mock submission via POST or when explicitly set to mock
    if request.method == "POST" or not client_id or SSO_AUTHORIZE_URL == "mock" or client_id == "snist-helpdesk-client":
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
                    resolved_role = "HOD" if teacher.get("is_hod") else role
                    user = {
                        "id": teacher["id"],
                        "name": teacher.get("name") or name,
                        "email": email,
                        "role": resolved_role,
                        "department": teacher.get("department") or dept,
                        "org_id": teacher.get("org_id", "2000"),
                    }
                else:
                    session.clear()
                    flash(f"Access restricted: The account ({email}) is not registered in the SNIST staff directory. Please contact the administrator.", "error")
                    return redirect(url_for("auth.login"))

            _set_session(user, email)
            flash(f"Signed in via Google SSO ({email}).", "success")
            return redirect(url_for(route_for_role(user["role"])))

        return render_template("mock_sso.html", default_email="faculty@sreenidhi.edu.in")

    import secrets
    import urllib.parse

    state = secrets.token_urlsafe(32)
    session["sso_state"] = state

    redirect_uri = _get_sso_redirect_uri()
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
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
    from app.config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    demo_db = get_demo_db()
    live_db = get_live_db()

    error = request.args.get("error")
    if error:
        session.clear()
        flash(f"SSO authentication failed: {error}", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or state != session.pop("sso_state", None):
        session.clear()
        flash("Invalid SSO response. Please try again.", "error")
        return redirect(url_for("auth.login"))

    try:
        import urllib.request
        import urllib.parse
        import json

        client_id = GOOGLE_CLIENT_ID or SSO_CLIENT_ID
        client_secret = GOOGLE_CLIENT_SECRET or SSO_CLIENT_SECRET
        redirect_uri = _get_sso_redirect_uri()

        if not SSO_TOKEN_URL:
            # Fallback for dev callback simulation
            email = "sso.user@sreenidhi.edu.in"
            name = "SSO Institutional User"
            userinfo = {"email": email, "name": name}
        else:
            # Exchange code for tokens
            token_data = urllib.parse.urlencode({
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
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

        # Direct institutional resolution - zero duplicate user creation
        existing = demo_db.get_user_by_email(email)
        if existing:
            user = existing
            if name and not user.get("name"):
                user["name"] = name
        else:
            teacher = live_db.lookup_teacher_by_email(email) if live_db.enabled else None
            if teacher:
                resolved_role = "HOD" if teacher.get("is_hod") else role
                user = {
                    "id": teacher["id"],
                    "name": teacher.get("name") or name,
                    "email": email,
                    "role": resolved_role,
                    "department": teacher.get("department") or department,
                    "org_id": teacher.get("org_id", "2000"),
                }
            else:
                log.warning("SSO login denied for unregistered user: %s", email)
                session.clear()
                flash(
                    f"Access restricted: The account ({email}) is not registered in the SNIST staff directory. "
                    "Please contact the system administrator.",
                    "error",
                )
                return redirect(url_for("auth.login"))

        _set_session(user, email)
        return redirect(url_for(route_for_role(user["role"])))

    except Exception as exc:
        log.error("SSO callback failed: %s", exc)
        session.clear()
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
    from flask import current_app
    session.clear()
    flash("Logged out successfully.", "success")
    resp = redirect(url_for("auth.login"))
    cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
    resp.delete_cookie(cookie_name)
    return resp


def _set_session(user: dict, email: str) -> None:
    """Populate session after successful login, regenerating session to prevent fixation."""
    from app import get_live_db
    live_db = get_live_db()
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]
    session["role"] = normalize_role(user.get("role"))
    session["department"] = user.get("department") or "General"
    session["org_id"] = user.get("org_id") or resolve_user_org(email, session["department"], live_db)
