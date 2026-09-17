"""Comprehensive Database Readiness & Startup Checks for SNIST Helpdesk.

Verifies TCP reachability, authentication, core schema presence, institutional
view resolution, schema version markers, and ticket routing health.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from db_services import DbConfig, is_host_reachable

log = logging.getLogger(__name__)

CORE_HELPDESK_TABLES = (
    "helpdesk_tickets",
    "helpdesk_categories",
    "helpdesk_problem_types",
    "helpdesk_ca_assignments",
    "helpdesk_staff_roles",
    "helpdesk_ticket_activity",
    "helpdesk_ticket_notes",
    "helpdesk_audit_events",
)

INSTITUTIONAL_VIEWS = (
    ("teacher_info", 2000),
    ("branch_detail", 50),
    ("location", 100),
)


def check_database(
    db_service: Any = None,
    config: Optional[DbConfig] = None,
) -> Dict[str, Any]:
    """
    Execute comprehensive database readiness checks.

    Returns structured readiness dictionary:
    {
        "checks": [{"check": str, "status": "PASS"|"FAIL"|"WARN", "detail": str, "fix": str}],
        "healthy": bool,
        "has_failure": bool,
        "has_warning": bool,
        "latency_ms": float,
        "metrics": dict
    }
    """
    if db_service is not None and getattr(db_service, "config", None) is not None:
        cfg = db_service.config
    elif config is not None:
        cfg = config
    else:
        host = os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in").strip()
        port = int(os.getenv("MYSQL_PORT", "3306"))
        user = os.getenv("MYSQL_USER", "demo").strip()
        password = os.getenv("MYSQL_PASSWORD", "").strip()
        database = os.getenv("MYSQL_DATABASE", "helpdesk").strip()
        cfg = DbConfig(host=host, port=port, user=user, password=password, database=database)

    checks: List[Dict[str, str]] = []
    metrics: Dict[str, Any] = {}
    start_time = time.time()
    latency_ms = 0.0

    # 1. TCP Reachability (reusing 60s host reachability cache from db_services)
    if not is_host_reachable(cfg.host, cfg.port, timeout_sec=3.0):
        checks.append({
            "check": "tcp_reachability",
            "status": "FAIL",
            "detail": f"MySQL server at {cfg.host}:{cfg.port} is unreachable via TCP.",
            "fix": "Check host name, network route, firewall, or ensure MySQL daemon is active.",
        })
        return {
            "checks": checks,
            "healthy": False,
            "has_failure": True,
            "has_warning": False,
            "latency_ms": 0.0,
            "metrics": metrics,
        }
    else:
        checks.append({
            "check": "tcp_reachability",
            "status": "PASS",
            "detail": f"Host {cfg.host}:{cfg.port} is reachable via TCP.",
            "fix": "",
        })

    # 2. Authentication & Connection
    conn = None
    try:
        connect_start = time.time()
        if db_service is not None and hasattr(db_service, "connection"):
            conn = db_service.connection()
            # If wrapped in PooledConnection, check connection
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        else:
            import pymysql
            conn = pymysql.connect(
                host=cfg.host,
                port=cfg.port,
                user=cfg.user,
                password=cfg.password,
                database=cfg.database,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=5,
            )
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        latency_ms = round((time.time() - connect_start) * 1000, 2)
        metrics["db_latency_ms"] = latency_ms
        checks.append({
            "check": "database_auth",
            "status": "PASS",
            "detail": f"Authenticated to database '{cfg.database}' as user '{cfg.user}' (latency: {latency_ms} ms).",
            "fix": "",
        })
    except Exception as exc:
        checks.append({
            "check": "database_auth",
            "status": "FAIL",
            "detail": f"Authentication failed for user '{cfg.user}' on database '{cfg.database}': {exc}",
            "fix": "Verify MYSQL_USER and MYSQL_PASSWORD credentials in .env.",
        })
        return {
            "checks": checks,
            "healthy": False,
            "has_failure": True,
            "has_warning": False,
            "latency_ms": 0.0,
            "metrics": metrics,
        }

    # Helper function for executing queries through conn
    def run_query(sql: str, params: Optional[tuple] = None):
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            return cur.fetchall()

    try:
        # 3. Schema Presence: 8 Core Helpdesk Tables
        try:
            tbl_rows = run_query("SHOW TABLES LIKE 'helpdesk_%'")
            existing_tables = set()
            for r in tbl_rows:
                # Row may be dict {"Tables_in_...": "tbl"} or tuple
                if isinstance(r, dict):
                    existing_tables.update(v.lower() for v in r.values())
                elif isinstance(r, (list, tuple)):
                    existing_tables.add(str(r[0]).lower())

            missing_tables = [t for t in CORE_HELPDESK_TABLES if t.lower() not in existing_tables]
            if missing_tables:
                checks.append({
                    "check": "schema_presence",
                    "status": "FAIL",
                    "detail": f"Missing {len(missing_tables)} core helpdesk table(s): {', '.join(missing_tables)}.",
                    "fix": "Run database migrations: mysql -u <user> -p <db> < sql/helpdesk_schema_v8.sql.",
                })
            else:
                checks.append({
                    "check": "schema_presence",
                    "status": "PASS",
                    "detail": f"All {len(CORE_HELPDESK_TABLES)} core helpdesk tables are present.",
                    "fix": "",
                })
        except Exception as exc:
            checks.append({
                "check": "schema_presence",
                "status": "FAIL",
                "detail": f"Failed checking schema tables: {exc}",
                "fix": "Verify user has SHOW TABLES privilege on target database.",
            })

        # 4. View Resolution: teacher_info, branch_detail, location
        inst_prefix = getattr(db_service, "inst_prefix", "")
        view_counts: Dict[str, int] = {}
        view_errors: List[str] = []

        for tbl, expected_approx in INSTITUTIONAL_VIEWS:
            target_name = f"{inst_prefix}{tbl}"
            try:
                rows = run_query(f"SELECT COUNT(*) AS total FROM {target_name}")
                count = rows[0]["total"] if rows and isinstance(rows[0], dict) else (rows[0][0] if rows else 0)
                view_counts[tbl] = count
                if count == 0:
                    checks.append({
                        "check": f"view_{tbl}",
                        "status": "WARN",
                        "detail": f"Institutional view '{target_name}' returned 0 records (expected ~{expected_approx}).",
                        "fix": f"Verify underlying institutional source table for '{tbl}' is populated.",
                    })
                else:
                    checks.append({
                        "check": f"view_{tbl}",
                        "status": "PASS",
                        "detail": f"View '{target_name}' resolved with {count} records (baseline ~{expected_approx}).",
                        "fix": "",
                    })
            except Exception as exc:
                view_errors.append(f"{tbl}: {exc}")
                checks.append({
                    "check": f"view_{tbl}",
                    "status": "FAIL",
                    "detail": f"Failed resolving institutional view '{target_name}': {exc}",
                    "fix": (
                        f"Ensure local SQL SECURITY DEFINER view '{tbl}' exists in '{cfg.database}', "
                        f"or grant SELECT on institutional schema if using cross-database queries."
                    ),
                })
        metrics["view_counts"] = view_counts

        # 5. Schema Version / Marker Index
        try:
            idx_rows = run_query("SHOW INDEX FROM helpdesk_ticket_activity")
            key_names = set()
            for r in idx_rows:
                if isinstance(r, dict):
                    key_names.add(r.get("Key_name", ""))
                elif isinstance(r, (list, tuple)) and len(r) > 2:
                    key_names.add(str(r[2]))
            if "uq_activity_dedup" in key_names or "chk_activity_action_by" in key_names:
                checks.append({
                    "check": "schema_version",
                    "status": "PASS",
                    "detail": "Schema version marker verified ('uq_activity_dedup' index present).",
                    "fix": "",
                })
            else:
                checks.append({
                    "check": "schema_version",
                    "status": "WARN",
                    "detail": "Schema may be out of date (missing 'uq_activity_dedup' deduplication index).",
                    "fix": "Run sql/helpdesk_schema_v8.sql and sql/migration_v9_integrity.sql to apply latest schema version.",
                })
        except Exception as exc:
            checks.append({
                "check": "schema_version",
                "status": "WARN",
                "detail": f"Could not inspect schema index version markers: {exc}",
                "fix": "Verify index inspection permissions on helpdesk_ticket_activity.",
            })

        # 6. Routing Sanity
        try:
            ca_rows = run_query("SELECT COUNT(*) AS total FROM helpdesk_ca_assignments")
            ca_count = ca_rows[0]["total"] if ca_rows and isinstance(ca_rows[0], dict) else 0

            unmapped_rows = run_query("SELECT COUNT(*) AS total FROM helpdesk_categories WHERE assigned_ca_id IS NULL AND is_active = 1")
            unmapped_count = unmapped_rows[0]["total"] if unmapped_rows and isinstance(unmapped_rows[0], dict) else 0

            metrics["ca_assignments_count"] = ca_count
            metrics["unmapped_categories_count"] = unmapped_count

            if ca_count == 0 or unmapped_count > 0:
                checks.append({
                    "check": "routing_sanity",
                    "status": "WARN",
                    "detail": (
                        f"Routing is degraded: {ca_count} block assignments found, "
                        f"{unmapped_count} active categories lack an assigned CA."
                    ),
                    "fix": "Ticket routing will fall back to admins. Run scripts/seed_production.py to populate CA mappings.",
                })
            else:
                checks.append({
                    "check": "routing_sanity",
                    "status": "PASS",
                    "detail": f"Routing healthy ({ca_count} block assignments, 0 unmapped active categories).",
                    "fix": "",
                })
        except Exception as exc:
            checks.append({
                "check": "routing_sanity",
                "status": "WARN",
                "detail": f"Failed checking routing sanity: {exc}",
                "fix": "Verify helpdesk_ca_assignments and helpdesk_categories tables exist.",
            })

        # 7. Pool utilization (if accessible)
        if db_service is not None and hasattr(db_service, "_pool"):
            try:
                pool = db_service._pool
                maxsize = pool.maxsize if hasattr(pool, "maxsize") else 10
                qsize = pool.qsize() if hasattr(pool, "qsize") else 0
                metrics["pool_maxsize"] = maxsize
                metrics["pool_available"] = qsize
                metrics["pool_in_use"] = maxsize - qsize
            except Exception:
                pass

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    has_failure = any(c["status"] == "FAIL" for c in checks)
    has_warning = any(c["status"] == "WARN" for c in checks)
    healthy = not has_failure

    return {
        "checks": checks,
        "healthy": healthy,
        "has_failure": has_failure,
        "has_warning": has_warning,
        "latency_ms": latency_ms,
        "metrics": metrics,
    }


def format_readiness_panel(report: Dict[str, Any], title: str = "DATABASE READINESS REPORT") -> str:
    """Format structured database readiness results into a human-readable panel."""
    lines = []
    lines.append("=" * 80)
    lines.append(f" {title} (Health: {'PASS' if report.get('healthy') else 'FAIL'}, Latency: {report.get('latency_ms', 0)} ms)")
    lines.append("=" * 80)

    for idx, c in enumerate(report.get("checks", []), 1):
        status = c.get("status", "PASS")
        name = c.get("check", "check")
        detail = c.get("detail", "")
        fix = c.get("fix", "")
        symbol = "[OK]  " if status == "PASS" else ("[WARN]" if status == "WARN" else "[FAIL]")
        lines.append(f"{symbol} #{idx} Check: {name}")
        lines.append(f"       Detail: {detail}")
        if fix and status != "PASS":
            lines.append(f"       Fix   : {fix}")
        lines.append("-" * 80)

    return "\n".join(lines)
