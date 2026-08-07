"""Analytics blueprint — embedded analytics dashboard with Chart.js fallback and Metabase integration."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, render_template, request

from app.config import METABASE_DASHBOARD_IDS, METABASE_INTERNAL_URL, METABASE_SECRET_KEY, METABASE_SITE_URL
from app.helpers import current_user, live_departments, page_context, role_required

log = logging.getLogger(__name__)

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.route("/analytics")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def analytics_dashboard():
    user = current_user()
    departments = live_departments(user["org_id"])

    # Bulletproof Metabase check:
    #   Use METABASE_INTERNAL_URL (Docker service name) for health checks,
    #   fall back to METABASE_SITE_URL (localhost) for non-Docker setups.
    metabase_enabled = False
    candidate_urls = [
        METABASE_INTERNAL_URL,
        "http://metabase:3000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3002",
        METABASE_SITE_URL,
    ]
    for health_url in candidate_urls:
        if not health_url or not METABASE_SECRET_KEY:
            continue
        try:
            import json
            import urllib.request

            api_url = f"{health_url.rstrip('/')}/api/health"
            req = urllib.request.Request(api_url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read())
                if data.get("status") == "ok":
                    metabase_enabled = True
                    break
        except Exception as exc:
            log.debug("Metabase health check failed for %s: %s", health_url, exc)

    return render_template(
        "analytics.html",
        departments=departments,
        metabase_enabled=metabase_enabled,
        metabase_url=METABASE_SITE_URL if metabase_enabled else "",
        **page_context("Analytics"),
    )


@analytics_bp.route("/api/analytics/summary")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_analytics_summary():
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    department = user["department"] if user["role"] == "HOD" else request.args.get("department") or None
    summary = demo_db.dashboard_summary(user)
    dept_stats = demo_db.ticket_stats_by_department(org_id=user["org_id"])
    cat_stats = demo_db.ticket_stats_by_category(department=department, org_id=user["org_id"])

    def ser(rows):
        out = []
        for r in rows:
            out.append({k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in dict(r).items()})
        return out

    return jsonify({
        "summary": dict(summary) if summary else {},
        "by_department": ser(dept_stats),
        "by_category": ser(cat_stats),
    })


@analytics_bp.route("/api/analytics/trends")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_analytics_trends():
    """Return ticket creation/resolution trends over time."""
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    period = request.args.get("period", "monthly")  # daily, weekly, monthly
    department = user["department"] if user["role"] == "HOD" else request.args.get("department") or None

    trends = demo_db.ticket_trends(org_id=user["org_id"], department=department, period=period) \
        if hasattr(demo_db, 'ticket_trends') else []

    return jsonify({"trends": trends, "period": period})


@analytics_bp.route("/api/analytics/ca-performance")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_analytics_ca_performance():
    """Return CA performance metrics."""
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    department = user["department"] if user["role"] == "HOD" else request.args.get("department") or None

    performance = demo_db.ca_performance_stats(org_id=user["org_id"], department=department) \
        if hasattr(demo_db, 'ca_performance_stats') else []

    return jsonify({"ca_performance": performance})


@analytics_bp.route("/api/analytics/resolution-time")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_analytics_resolution_time():
    """Return average resolution time by category."""
    from app import get_demo_db
    demo_db = get_demo_db()
    user = current_user()
    department = user["department"] if user["role"] == "HOD" else request.args.get("department") or None

    resolution_data = demo_db.resolution_time_stats(org_id=user["org_id"], department=department) \
        if hasattr(demo_db, 'resolution_time_stats') else []

    return jsonify({"resolution_time": resolution_data})


@analytics_bp.route("/api/analytics/metabase-embed")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_metabase_embed():
    """Generate a signed Metabase embed URL."""
    if not METABASE_SITE_URL or not METABASE_SECRET_KEY:
        return jsonify({"error": "Metabase is not configured."}), 503

    dashboard_key = request.args.get("dashboard", "overview")
    raw_id = METABASE_DASHBOARD_IDS.get(dashboard_key)
    overview_id = METABASE_DASHBOARD_IDS.get("overview")
    dashboard_id = raw_id if (raw_id and raw_id > 0) else (overview_id if (overview_id and overview_id > 0) else 2)

    try:
        import jwt
        import time

        user = current_user()
        payload = {
            "resource": {"dashboard": dashboard_id},
            "params": {},
            "exp": int(time.time()) + (10 * 60),  # 10 minute expiry
        }

        token = jwt.encode(payload, METABASE_SECRET_KEY, algorithm="HS256")
        embed_url = f"{METABASE_SITE_URL}/embed/dashboard/{token}#bordered=false&titled=false"

        return jsonify({"embed_url": embed_url})
    except ImportError:
        return jsonify({"error": "PyJWT not installed. Install with: pip install PyJWT"}), 503
    except Exception as exc:
        log.error("Metabase embed generation failed: %s", exc)
        return jsonify({"error": "Failed to generate embed URL."}), 500
