"""Health Check & Diagnostic Endpoints for SNIST Helpdesk.

Exposes:
- GET /health: Lightweight liveness check (no DB dependency, for load balancers).
- GET /health/deep: Comprehensive readiness check (requires X-Health-Token header).
"""
from __future__ import annotations

import os
import time
from flask import Blueprint, jsonify, request

from app.startup_checks import check_database

health_bp = Blueprint("health", __name__, url_prefix="/health")
_SERVER_START_TIME = time.time()


@health_bp.route("", methods=["GET"])
@health_bp.route("/", methods=["GET"])
def liveness():
    """
    Lightweight liveness probe.
    Does NOT touch the database so load balancers can verify process responsiveness
    without being impacted by brief database latency or network jitter.
    """
    uptime = round(time.time() - _SERVER_START_TIME, 2)
    return jsonify({
        "status": "ok",
        "service": "snist_helpdesk",
        "uptime_seconds": uptime,
    }), 200


@health_bp.route("/deep", methods=["GET"])
def readiness():
    """
    Deep database readiness and dependency health probe.
    Protected by a shared secret (X-Health-Token) to prevent exposure of internal infrastructure details.
    Returns 200 if all database and view checks pass, or 503 if any check fails.
    """
    configured_token = os.getenv("X_HEALTH_TOKEN", os.getenv("HEALTH_TOKEN", "snist-health-secret")).strip()
    provided_token = request.headers.get("X-Health-Token", "").strip()

    if not provided_token or provided_token != configured_token:
        return jsonify({
            "error": "Forbidden",
            "message": "Missing or invalid X-Health-Token header.",
        }), 403

    from app import get_demo_db, get_live_db
    from app.pool_metrics import POOL_METRICS
    demo_db = get_demo_db() or get_live_db()

    report = check_database(db_service=demo_db)

    # Pool metrics and utilization
    pool_metrics_data = POOL_METRICS.get_metrics()
    maxsize = getattr(demo_db, "_maxsize", 20)
    in_use = getattr(demo_db, "_in_use", 0)
    waiters = getattr(demo_db, "_waiters", 0)
    p50_ms = pool_metrics_data.get("p50_checkout_ms", 0.0)
    p95_ms = pool_metrics_data.get("p95_checkout_ms", 0.0)

    pool_info = {
        "maxsize": maxsize,
        "in_use": in_use,
        "waiters": waiters,
        "p50_checkout_ms": p50_ms,
        "p95_checkout_ms": p95_ms,
        "metrics": pool_metrics_data,
    }

    # Readiness logic:
    # WARN: unpooled_fallbacks > 10 in last 5m OR p95 checkout latency > 500ms
    # FAIL (503): pool_timeout_errors > 0 in last minute
    recent_fallbacks = POOL_METRICS.get_fallbacks_last_5m()
    recent_timeouts = POOL_METRICS.get_timeouts_last_minute()

    has_warning = report.get("has_warning", False)
    has_failure = report.get("has_failure", False)
    checks = list(report.get("checks", []))

    if recent_timeouts > 0:
        has_failure = True
        checks.append({
            "name": "pool_timeout_check",
            "status": "FAIL",
            "message": f"{recent_timeouts} pool timeout error(s) occurred in the last minute.",
        })

    if recent_fallbacks > 10:
        has_warning = True
        checks.append({
            "name": "pool_fallbacks_check",
            "status": "WARN",
            "message": f"High rate of unpooled fallbacks: {recent_fallbacks} in last 5 minutes.",
        })

    if p95_ms > 500.0:
        has_warning = True
        checks.append({
            "name": "pool_latency_check",
            "status": "WARN",
            "message": f"High p95 checkout latency: {p95_ms}ms (> 500ms).",
        })

    is_healthy = not has_failure
    status_code = 200 if is_healthy else 503
    status_label = "healthy" if is_healthy else "unhealthy"

    return jsonify({
        "status": status_label,
        "uptime_seconds": round(time.time() - _SERVER_START_TIME, 2),
        "db_latency_ms": report.get("latency_ms", 0.0),
        "has_failure": has_failure,
        "has_warning": has_warning,
        "pool": pool_info,
        "checks": checks,
        "metrics": report.get("metrics", {}),
    }), status_code


@health_bp.route("/metrics", methods=["GET"])
def prometheus_metrics():
    """
    Expose application and pool performance metrics in Prometheus text exposition format (version 0.0.4).
    Metrics scraped include:
    - snist_helpdesk_uptime_seconds
    - snist_helpdesk_pool_in_use
    - snist_helpdesk_pool_maxsize
    - snist_helpdesk_pool_waiters
    - snist_helpdesk_pool_checkouts_total
    - snist_helpdesk_pool_checkouts_reused_total
    - snist_helpdesk_pool_new_connections_total
    - snist_helpdesk_pool_unpooled_fallbacks_total
    - snist_helpdesk_pool_timeout_errors_total
    - snist_helpdesk_query_retries_total
    - snist_helpdesk_query_failures_total
    - snist_helpdesk_pool_checkout_latency_p50_ms
    - snist_helpdesk_pool_checkout_latency_p95_ms
    - snist_helpdesk_tickets_by_status
    """
    from flask import Response
    from app import get_demo_db, get_live_db
    from app.pool_metrics import POOL_METRICS

    demo_db = get_demo_db() or get_live_db()
    pool_metrics_data = POOL_METRICS.get_metrics()

    uptime = round(time.time() - _SERVER_START_TIME, 2)
    maxsize = getattr(demo_db, "_maxsize", 20)
    in_use = getattr(demo_db, "_in_use", 0)
    waiters = getattr(demo_db, "_waiters", 0)
    p50_ms = pool_metrics_data.get("p50_checkout_ms", 0.0)
    p95_ms = pool_metrics_data.get("p95_checkout_ms", 0.0)

    lines = [
        "# HELP snist_helpdesk_uptime_seconds Total application uptime in seconds.",
        "# TYPE snist_helpdesk_uptime_seconds gauge",
        f"snist_helpdesk_uptime_seconds {uptime}",
        "",
        "# HELP snist_helpdesk_pool_maxsize Maximum capacity of the database connection pool.",
        "# TYPE snist_helpdesk_pool_maxsize gauge",
        f"snist_helpdesk_pool_maxsize {maxsize}",
        "",
        "# HELP snist_helpdesk_pool_in_use Number of database connections currently checked out.",
        "# TYPE snist_helpdesk_pool_in_use gauge",
        f"snist_helpdesk_pool_in_use {in_use}",
        "",
        "# HELP snist_helpdesk_pool_waiters Number of threads waiting for a pool connection.",
        "# TYPE snist_helpdesk_pool_waiters gauge",
        f"snist_helpdesk_pool_waiters {waiters}",
        "",
        "# HELP snist_helpdesk_pool_checkouts_total Total number of successful connection checkouts.",
        "# TYPE snist_helpdesk_pool_checkouts_total counter",
        f"snist_helpdesk_pool_checkouts_total {pool_metrics_data.get('checkouts_total', 0)}",
        "",
        "# HELP snist_helpdesk_pool_checkouts_reused_total Total checkouts reusing a warm pooled connection.",
        "# TYPE snist_helpdesk_pool_checkouts_reused_total counter",
        f"snist_helpdesk_pool_checkouts_reused_total {pool_metrics_data.get('checkouts_reused', 0)}",
        "",
        "# HELP snist_helpdesk_pool_new_connections_total Total new connections created by pool.",
        "# TYPE snist_helpdesk_pool_new_connections_total counter",
        f"snist_helpdesk_pool_new_connections_total {pool_metrics_data.get('new_connections_created', 0)}",
        "",
        "# HELP snist_helpdesk_pool_unpooled_fallbacks_total Total unpooled fallback connections.",
        "# TYPE snist_helpdesk_pool_unpooled_fallbacks_total counter",
        f"snist_helpdesk_pool_unpooled_fallbacks_total {pool_metrics_data.get('unpooled_fallbacks', 0)}",
        "",
        "# HELP snist_helpdesk_pool_timeout_errors_total Total connection checkout timeouts.",
        "# TYPE snist_helpdesk_pool_timeout_errors_total counter",
        f"snist_helpdesk_pool_timeout_errors_total {pool_metrics_data.get('pool_timeout_errors', 0)}",
        "",
        "# HELP snist_helpdesk_query_retries_total Total database query retry attempts on transient errors.",
        "# TYPE snist_helpdesk_query_retries_total counter",
        f"snist_helpdesk_query_retries_total {pool_metrics_data.get('query_retries', 0)}",
        "",
        "# HELP snist_helpdesk_query_failures_total Total unrecoverable database query failures.",
        "# TYPE snist_helpdesk_query_failures_total counter",
        f"snist_helpdesk_query_failures_total {pool_metrics_data.get('query_failures', 0)}",
        "",
        "# HELP snist_helpdesk_pool_checkout_latency_p50_ms 5-minute rolling median (p50) checkout latency in milliseconds.",
        "# TYPE snist_helpdesk_pool_checkout_latency_p50_ms gauge",
        f"snist_helpdesk_pool_checkout_latency_p50_ms {p50_ms}",
        "",
        "# HELP snist_helpdesk_pool_checkout_latency_p95_ms 5-minute rolling 95th percentile (p95) checkout latency in milliseconds.",
        "# TYPE snist_helpdesk_pool_checkout_latency_p95_ms gauge",
        f"snist_helpdesk_pool_checkout_latency_p95_ms {p95_ms}",
    ]

    # Ticket statistics by status if database is available
    if demo_db and hasattr(demo_db, "dashboard_summary"):
        try:
            summary = demo_db.dashboard_summary({"role": "ADMIN", "id": 0, "org_id": None}) or {}
            lines.append("")
            lines.append("# HELP snist_helpdesk_tickets_total Total number of logged tickets.")
            lines.append("# TYPE snist_helpdesk_tickets_total gauge")
            lines.append(f"snist_helpdesk_tickets_total {summary.get('total') or 0}")
            lines.append("")
            lines.append("# HELP snist_helpdesk_tickets_by_status Current count of tickets grouped by status.")
            lines.append("# TYPE snist_helpdesk_tickets_by_status gauge")
            for st in ("pending", "in_progress", "on_hold", "resolved", "reopened"):
                lines.append(f'snist_helpdesk_tickets_by_status{{status="{st}"}} {summary.get(st) or 0}')
        except Exception:
            pass

    body = "\n".join(lines) + "\n"
    return Response(body, mimetype="text/plain; version=0.0.4; charset=utf-8")

