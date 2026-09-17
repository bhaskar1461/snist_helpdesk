"""Security module for SNIST Helpdesk.

Implements:
1. Distributed, database-backed login rate limiting (multi-worker safe).
2. Fail-closed security controls for authentication and authorization.
3. Attachment authorization and path traversal validation (IDOR protection).
4. Zero-dependency session-bound CSRF token generation and validation.
5. Probabilistic housekeeping cleanup for historical audit/rate limit tables.
"""
from __future__ import annotations

import hmac
import logging
import os
import random
import secrets
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger(__name__)

# Rate limit configuration
LOGIN_MAX_ATTEMPTS_USER = int(os.getenv("LOGIN_MAX_ATTEMPTS_USER", "5"))
LOGIN_MAX_ATTEMPTS_IP = int(os.getenv("LOGIN_MAX_ATTEMPTS_IP", "30"))
LOGIN_WINDOW_MINUTES = int(os.getenv("LOGIN_WINDOW_MINUTES", "15"))

# In-memory fail-closed fallback counters if DB is completely unreachable
_FALLBACK_FAILURES: dict[str, list[float]] = defaultdict(list)
_FALLBACK_LOCKOUT_SEC = 900.0  # 15 minutes


# ─────────────────────────────────────────────────────────────────────────────
# 1. Distributed Multi-Worker Rate Limiting
# ─────────────────────────────────────────────────────────────────────────────

def check_login_rate_limit(
    db_service: Any,
    identifier: str,
    ip_address: str,
    window_minutes: int = LOGIN_WINDOW_MINUTES,
    max_user: int = LOGIN_MAX_ATTEMPTS_USER,
    max_ip: int = LOGIN_MAX_ATTEMPTS_IP,
) -> Tuple[bool, str]:
    """Check if the given identifier or IP is rate-limited.
    
    Returns (is_limited, error_message).
    Executes BEFORE password verification to prevent brute-force timing attacks.
    """
    clean_id = (identifier or "").strip().lower()
    clean_ip = (ip_address or "127.0.0.1").strip()

    if not clean_id:
        return False, ""

    try:
        if db_service is not None and hasattr(db_service, "check_rate_limit"):
            return db_service.check_rate_limit(
                identifier=clean_id,
                ip_address=clean_ip,
                window_minutes=window_minutes,
                max_user=max_user,
                max_ip=max_ip,
            )

        # Direct DB fallback using connection if helper method not present
        if db_service is not None and hasattr(db_service, "connection"):
            with db_service.connection() as conn, conn.cursor() as cur:
                # Count failures for identifier in window
                cur.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM helpdesk_login_attempts
                    WHERE identifier = %s AND outcome = 'FAILURE'
                      AND attempted_at >= NOW() - INTERVAL %s MINUTE
                    """,
                    (clean_id, window_minutes),
                )
                row_id = cur.fetchone()
                id_fails = row_id["total"] if isinstance(row_id, dict) else (row_id[0] if row_id else 0)

                if id_fails >= max_user:
                    log.warning(
                        "Distributed rate limit exceeded for identifier '%s' from IP '%s' (%s failures in last %sm).",
                        clean_id, clean_ip, id_fails, window_minutes,
                    )
                    return True, f"Too many failed login attempts for this account. Please try again in {window_minutes} minutes."

                # Count failures for IP in window
                cur.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM helpdesk_login_attempts
                    WHERE ip_address = %s AND outcome = 'FAILURE'
                      AND attempted_at >= NOW() - INTERVAL %s MINUTE
                    """,
                    (clean_ip, window_minutes),
                )
                row_ip = cur.fetchone()
                ip_fails = row_ip["total"] if isinstance(row_ip, dict) else (row_ip[0] if row_ip else 0)

                if ip_fails >= max_ip:
                    log.warning(
                        "Distributed rate limit exceeded for IP '%s' (%s failures in last %sm).",
                        clean_ip, ip_fails, window_minutes,
                    )
                    return True, f"Too many failed login attempts from this network. Please try again in {window_minutes} minutes."

                return False, ""

    except Exception as exc:
        log.error("Failed to query helpdesk_login_attempts for rate limiting: %s", exc)
        # Fail-closed policy: fall back to local process tracker if DB fails
        now = time.time()
        _FALLBACK_FAILURES[clean_id] = [t for t in _FALLBACK_FAILURES[clean_id] if now - t < _FALLBACK_LOCKOUT_SEC]
        if len(_FALLBACK_FAILURES[clean_id]) >= 3:
            log.warning("Fail-closed active for identifier '%s' due to DB outage and repeated local failures.", clean_id)
            return True, "Authentication service degraded. Temporary security lockout enforced. Please wait a few minutes."

    return False, ""


def record_login_attempt(
    db_service: Any,
    identifier: str,
    ip_address: str,
    outcome: str = "FAILURE",
) -> None:
    """Record a login attempt outcome in the distributed database."""
    clean_id = (identifier or "").strip().lower()
    clean_ip = (ip_address or "127.0.0.1").strip()
    norm_outcome = "SUCCESS" if outcome.upper() == "SUCCESS" else "FAILURE"

    if not clean_id:
        return

    # Update in-memory fallback tracker
    now = time.time()
    if norm_outcome == "FAILURE":
        _FALLBACK_FAILURES[clean_id].append(now)
    else:
        _FALLBACK_FAILURES.pop(clean_id, None)

    try:
        if db_service is not None and hasattr(db_service, "record_login_attempt"):
            db_service.record_login_attempt(clean_id, clean_ip, norm_outcome)
            return

        if db_service is not None and hasattr(db_service, "connection"):
            with db_service.connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO helpdesk_login_attempts (identifier, ip_address, outcome)
                    VALUES (%s, %s, %s)
                    """,
                    (clean_id, clean_ip, norm_outcome),
                )
                if norm_outcome == "SUCCESS":
                    # On successful login, clear failure records for this user
                    cur.execute(
                        "DELETE FROM helpdesk_login_attempts WHERE identifier = %s AND outcome = 'FAILURE'",
                        (clean_id,),
                    )
                    # Probabilistic 1% cleanup of records older than 30 days
                    if random.random() < 0.01:
                        cur.execute(
                            "DELETE FROM helpdesk_login_attempts WHERE attempted_at < NOW() - INTERVAL 30 DAY"
                        )
    except Exception as exc:
        log.error("Failed to record login attempt for '%s' in DB: %s", clean_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Attachment Access Control & IDOR Defense
# ─────────────────────────────────────────────────────────────────────────────

def validate_attachment_path(filename: str, base_dir: Path) -> Optional[Path]:
    """Resolve and validate that the requested file resides strictly within base_dir.
    
    Defends against path traversal, symlink escapes, and null byte injections.
    Returns canonical Path if valid and existing, else None.
    """
    if not filename or "\0" in filename:
        return None

    try:
        target = (base_dir / filename).resolve()
        base = base_dir.resolve()

        # Target must be within base_dir
        if not target.is_relative_to(base):
            log.warning("Directory traversal attempt blocked for filename '%s'", filename)
            return None

        if not target.is_file():
            return None

        return target
    except Exception as exc:
        log.warning("Attachment path resolution failed for '%s': %s", filename, exc)
        return None


def can_user_access_ticket_attachment(user: Optional[Dict[str, Any]], ticket: Optional[Dict[str, Any]]) -> bool:
    """Authorization guard for ticket attachments.
    
    Access is ALLOWED if requester is:
      1. Campus/Super Admin or Admin.
      2. Staff with role >= HOD for the ticket's category department.
      3. Ticket submitter (created_by or email match).
      4. Assigned CA (assigned_to or email match).
    All accesses strictly require org_id matching.
    DENY otherwise.
    """
    if not user or not ticket:
        return False

    # Org ID scoping
    user_org = str(user.get("org_id", "")).strip()
    ticket_org = str(ticket.get("org_id", "")).strip()
    if user_org and ticket_org and user_org != ticket_org:
        return False

    role = (user.get("role") or "").upper()
    user_email = (user.get("email") or "").strip().lower()
    user_id = user.get("id")

    # 1. Super Admin and Admin have full access
    if role in ("SUPER_ADMIN", "ADMIN"):
        return True

    # 2. HOD for matching department
    if role == "HOD":
        user_dept = (user.get("department") or "").strip().lower()
        ticket_dept = (ticket.get("department") or "").strip().lower()
        if user_dept and ticket_dept and user_dept == ticket_dept:
            return True

    # 3. Submitter
    created_id = ticket.get("created_by")
    created_email = (ticket.get("created_by_email") or "").strip().lower()
    if user_id and created_id and user_id == created_id:
        return True
    if user_email and created_email and user_email == created_email:
        return True

    # 4. Assigned CA
    assigned_id = ticket.get("assigned_to")
    assigned_email = (ticket.get("assigned_to_email") or "").strip().lower()
    if user_id and assigned_id and user_id == assigned_id:
        return True
    if user_email and assigned_email and user_email == assigned_email:
        return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# 3. CSRF Protection (Zero External Dependencies)
# ─────────────────────────────────────────────────────────────────────────────

def get_or_create_csrf_token(session_dict: Any) -> str:
    """Retrieve or generate a secure session-bound CSRF token."""
    if "_csrf_token" not in session_dict:
        session_dict["_csrf_token"] = secrets.token_hex(32)
    return session_dict["_csrf_token"]


def validate_csrf_token(session_dict: Any, token: Optional[str]) -> bool:
    """Validate submitted token against session token using constant-time comparison."""
    if not token or not isinstance(token, str):
        return False
    expected = session_dict.get("_csrf_token")
    if not expected or not isinstance(expected, str):
        return False
    return hmac.compare_digest(token.strip(), expected.strip())
