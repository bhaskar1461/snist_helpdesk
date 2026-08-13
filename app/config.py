"""Centralized configuration for the SNIST Helpdesk application."""

from __future__ import annotations

import os
import re
import logging
from pathlib import Path
from datetime import timedelta

log = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = BASE_DIR / "sql" / "demo_schema.sql"
MIGRATION_V2_PATH = BASE_DIR / "sql" / "migration_v2.sql"
MIGRATION_V3_PATH = BASE_DIR / "sql" / "migration_v3.sql"
MIGRATION_V5_PATH = BASE_DIR / "sql" / "migration_v5_dedup_keys.sql"
MIGRATION_V6_PATH = BASE_DIR / "sql" / "migration_v6_rename_tables.sql"
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

# ── File Uploads ─────────────────────────────────────────────────────
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "gif", "doc", "docx", "xls", "xlsx"}
MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB

# ── Validation ───────────────────────────────────────────────────────
EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# ── Rate Limiting ────────────────────────────────────────────────────
LOCKOUT_TIME = 60   # seconds
MAX_ATTEMPTS = 5    # max attempts within lockout window

# ── Org Labels ───────────────────────────────────────────────────────
ORG_LABELS = {"2000": "SNIST", "3000": "SNU"}

# ── Role Definitions ────────────────────────────────────────────────
ROLES = ["SUPER_ADMIN", "ADMIN", "HOD", "ASSIGNEE", "CA", "FACULTY"]

ROLE_DASHBOARD_ROUTES = {
    "SUPER_ADMIN": "dashboards.super_admin_dashboard",
    "ADMIN": "dashboards.admin_dashboard",
    "HOD": "dashboards.hod_dashboard",
    "ASSIGNEE": "tickets.authority_tickets",
    "CA": "tickets.authority_tickets",
    "FACULTY": "dashboards.user_dashboard",
}

# ── Demo Users & Categories ─────────────────────────────────────────
DEFAULT_DEMO_USERS = [
    {"name": "Super Admin", "email": "admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "org_id": "2000"},
    {"name": "Campus Admin", "email": "campus.admin@gmail.com", "password": "123", "role": "ADMIN", "department": "Administration", "org_id": "2000"},
    {"name": "Dr. Kavya", "email": "hod@gmail.com", "password": "123", "role": "HOD", "department": "CSE", "org_id": "2000"},
    {"name": "Dr. Harini", "email": "hod.ece@gmail.com", "password": "123", "role": "HOD", "department": "ECE", "org_id": "2000"},
    {"name": "Chandini", "email": "ca@gmail.com", "password": "123", "role": "ASSIGNEE", "department": "CSE", "org_id": "2000"},
    {"name": "Sravan", "email": "sravan.ca@gmail.com", "password": "123", "role": "ASSIGNEE", "department": "Facilities", "org_id": "2000"},
    {"name": "Bhaskar", "email": "bhaskar.ca@gmail.com", "password": "123", "role": "ASSIGNEE", "department": "Maintenance", "org_id": "2000"},
    {"name": "Demo User", "email": "faculty@gmail.com", "password": "123", "role": "FACULTY", "department": "CSE", "org_id": "2000"},
    {"name": "SNU Admin", "email": "snu.admin@gmail.com", "password": "123", "role": "SUPER_ADMIN", "department": "Administration", "org_id": "3000"},
]

DEFAULT_DEMO_CATEGORIES = [
    {"category_name": "Internet", "department": "CSE", "authority_email": "ca@gmail.com"},
    {"category_name": "Projector", "department": "CSE", "authority_email": "ca@gmail.com"},
    {"category_name": "Plumbing", "department": "Facilities", "authority_email": "bhaskar.ca@gmail.com"},
    {"category_name": "Electrical", "department": "Maintenance", "authority_email": "bhaskar.ca@gmail.com"},
]

# ── SSO Configuration ───────────────────────────────────────────────
SSO_ENABLED = os.getenv("SSO_ENABLED", "true").lower() == "true"
SSO_PROVIDER = os.getenv("SSO_PROVIDER", "google")  # google, oidc, mock

# Google Workspace OAuth2 Config
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", os.getenv("SSO_CLIENT_ID", ""))
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", os.getenv("SSO_CLIENT_SECRET", ""))
GOOGLE_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_HOSTED_DOMAIN = os.getenv("GOOGLE_HOSTED_DOMAIN", "")  # e.g., sreenidhi.edu.in

# Generic OIDC fallback
SSO_CLIENT_ID = GOOGLE_CLIENT_ID or os.getenv("SSO_CLIENT_ID", "")
SSO_CLIENT_SECRET = GOOGLE_CLIENT_SECRET or os.getenv("SSO_CLIENT_SECRET", "")
SSO_AUTHORIZE_URL = os.getenv("SSO_AUTHORIZE_URL", GOOGLE_AUTHORIZE_URL if GOOGLE_CLIENT_ID else "mock")
SSO_TOKEN_URL = os.getenv("SSO_TOKEN_URL", GOOGLE_TOKEN_URL)
SSO_USERINFO_URL = os.getenv("SSO_USERINFO_URL", GOOGLE_USERINFO_URL)
SSO_REDIRECT_URI = os.getenv("SSO_REDIRECT_URI", "")
SSO_SCOPES = os.getenv("SSO_SCOPES", "openid email profile")
SSO_ROLE_CLAIM = os.getenv("SSO_ROLE_CLAIM", "")
SSO_DEPT_CLAIM = os.getenv("SSO_DEPT_CLAIM", "")
SSO_DEFAULT_ROLE = os.getenv("SSO_DEFAULT_ROLE", "FACULTY")
EMERGENCY_ADMIN_ENABLED = os.getenv("EMERGENCY_ADMIN_ENABLED", "true").lower() == "true"

# ── Metabase Configuration ──────────────────────────────────────────
METABASE_SITE_URL = os.getenv("METABASE_SITE_URL", "https://metabase.1sports.app")
METABASE_INTERNAL_URL = os.getenv("METABASE_INTERNAL_URL", "http://localhost:3000")
METABASE_SECRET_KEY = os.getenv("METABASE_SECRET_KEY", "b6c0144720edd6f7369910c70c66e0519ac0386c2b9d173434c57332a048e685")
METABASE_DASHBOARD_IDS = {
    "overview": int(os.getenv("METABASE_DASHBOARD_OVERVIEW", "4")),
    "department": int(os.getenv("METABASE_DASHBOARD_DEPARTMENT", "4")),
    "ca_performance": int(os.getenv("METABASE_DASHBOARD_CA_PERF", "6")),
    "trends": int(os.getenv("METABASE_DASHBOARD_TRENDS", "5")),
}



def get_flask_config():
    """Return Flask configuration dict."""
    _secret = os.getenv("SECRET_KEY") or "c69fc621e47743c584ea00c3d51053bb09a2e6659f0f9b6e828453ea1a4155b2"
    return {
        "SECRET_KEY": _secret,
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
        "PERMANENT_SESSION_LIFETIME": timedelta(minutes=30),
        "MAX_CONTENT_LENGTH": MAX_UPLOAD_SIZE,
    }

