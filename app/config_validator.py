"""Centralized Configuration Validator for SNIST Helpdesk.

Validates environment variables, secret key entropy, database connection parameters,
and production safety flags before the application boots.
"""
from __future__ import annotations

import os
import socket
from typing import Any, Dict, List, Optional


def validate_config(env: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """
    Validate application configuration and environment variables.

    Returns a list of structured issue dictionaries:
        [{"level": "ERROR"|"WARNING", "check": str, "message": str, "fix": str}]
    """
    if env is None:
        env = dict(os.environ)

    issues: List[Dict[str, str]] = []
    flask_env = env.get("FLASK_ENV", env.get("ENV", "production")).strip().lower()
    is_development = flask_env in ("development", "dev", "local")

    # 1. REQUIRED VARS PRESENT & NON-EMPTY
    required_vars = [
        "SECRET_KEY",
        "MYSQL_HOST",
        "MYSQL_USER",
        "MYSQL_DATABASE",
        "MYSQL_PASSWORD",
    ]
    for var in required_vars:
        val = env.get(var)
        if val is None or str(val).strip() == "":
            issues.append({
                "level": "ERROR",
                "check": "required_vars",
                "message": f"Required environment variable '{var}' is missing or empty.",
                "fix": f"Define '{var}' with a non-empty value in .env or server environment.",
            })

    # 2. SECRET_KEY STRENGTH
    secret_key = env.get("SECRET_KEY", "").strip()
    weak_keys = {"", "dev", "changeme", "secret", "password", "test", "demo"}
    is_weak = secret_key.lower() in weak_keys or len(secret_key) < 32

    if secret_key:
        if is_weak:
            if is_development:
                issues.append({
                    "level": "WARNING",
                    "check": "secret_key_strength",
                    "message": f"SECRET_KEY is weak or short (< 32 chars: length={len(secret_key)}). Allowed only in development.",
                    "fix": "Generate a cryptographically secure key: python -c \"import secrets; print(secrets.token_hex(32))\"",
                })
            else:
                issues.append({
                    "level": "ERROR",
                    "check": "secret_key_strength",
                    "message": f"SECRET_KEY is too weak or shorter than 32 characters (length={len(secret_key)}) in production mode.",
                    "fix": "Generate a 64-character hex secret: python -c \"import secrets; print(secrets.token_hex(32))\" and set SECRET_KEY in .env.",
                })

    # 3. TYPE/FORMAT CHECKS
    # MYSQL_PORT
    port_str = env.get("MYSQL_PORT", "3306").strip()
    port_val = None
    try:
        port_val = int(port_str)
        if not (1 <= port_val <= 65535):
            issues.append({
                "level": "ERROR",
                "check": "mysql_port",
                "message": f"MYSQL_PORT '{port_str}' is outside valid TCP port range (1-65535).",
                "fix": "Set MYSQL_PORT=3306 or appropriate valid integer port in .env.",
            })
    except ValueError:
        issues.append({
            "level": "ERROR",
            "check": "mysql_port",
            "message": f"MYSQL_PORT '{port_str}' is not a valid integer.",
            "fix": "Set MYSQL_PORT=3306 in .env.",
        })

    # MYSQL_HOST DNS resolution check
    host = env.get("MYSQL_HOST", "").strip()
    if host:
        try:
            target_port = port_val if (port_val and 1 <= port_val <= 65535) else 3306
            socket.getaddrinfo(host, target_port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as exc:
            issues.append({
                "level": "ERROR",
                "check": "mysql_host_dns",
                "message": f"MYSQL_HOST '{host}' cannot be resolved via DNS: {exc}",
                "fix": "Check hostname spelling, DNS server settings, or /etc/hosts mapping.",
            })
        except Exception:
            # Network blip or unexpected socket check error
            pass

    # INIT_DEMO_DB check
    init_demo = env.get("INIT_DEMO_DB", "false").strip().lower()
    if init_demo in ("true", "1", "yes"):
        if not is_development:
            issues.append({
                "level": "ERROR",
                "check": "init_demo_db_production",
                "message": "INIT_DEMO_DB is set to 'true' in production. This will attempt DDL schema modifications and user overwrites.",
                "fix": "Set INIT_DEMO_DB=false in production .env.",
            })
        else:
            issues.append({
                "level": "WARNING",
                "check": "init_demo_db_development",
                "message": "INIT_DEMO_DB is 'true' — startup will ensure demo tables and seed default demo users.",
                "fix": "Set INIT_DEMO_DB=false when working against a shared or persistent database.",
            })

    # 4. MYSQL_INSTITUTIONAL_DATABASE
    inst_db = env.get("MYSQL_INSTITUTIONAL_DATABASE", "").strip()
    main_db = env.get("MYSQL_DATABASE", "").strip()
    user = env.get("MYSQL_USER", "demo").strip()
    if inst_db and inst_db != main_db:
        issues.append({
            "level": "WARNING",
            "check": "institutional_database_prefix",
            "message": (
                f"MYSQL_INSTITUTIONAL_DATABASE is set to '{inst_db}', which differs from MYSQL_DATABASE ('{main_db}'). "
                f"Direct institutional table access requires cross-database SELECT grants."
            ),
            "fix": (
                f"DBA grant required: GRANT SELECT ON `{inst_db}`.* TO '{user}'@'%'; "
                f"OR unset MYSQL_INSTITUTIONAL_DATABASE to use local SQL SECURITY DEFINER views."
            ),
        })

    return issues


def format_issues_panel(issues: List[Dict[str, str]], title: str = "CONFIGURATION VALIDATION FAILED") -> str:
    """Format structured issues into a human-readable diagnostic panel."""
    lines = []
    lines.append("=" * 80)
    lines.append(f" {title}")
    lines.append("=" * 80)
    for idx, item in enumerate(issues, 1):
        lvl = item.get("level", "ERROR").upper()
        check = item.get("check", "general")
        msg = item.get("message", "")
        fix = item.get("fix", "")
        lines.append(f"[{lvl}] #{idx} Check: {check}")
        lines.append(f"  Problem: {msg}")
        if fix:
            lines.append(f"  Action : {fix}")
        lines.append("-" * 80)
    return "\n".join(lines)
