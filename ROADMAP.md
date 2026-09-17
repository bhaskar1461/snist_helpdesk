# SNIST Helpdesk System Roadmap

This document outlines the milestones and roadmap for the SNIST Helpdesk development.

## Milestone 1: Core System Hardening (✅ Completed)
- [x] Database connection pooling (`Queue`-based pool with bounded checkout and idle connection reaper).
- [x] Thread-local database transactions wrapper (`DemoDbService.transaction()`).
- [x] Persistent session store integration using static environment keys.
- [x] Asynchronous background thread pools for email/SMS notifications.
- [x] Strict mime-type signature checks validating magic bytes of uploads.
- [x] Duplicate submit lockouts inside form action pages (`submission_key`).
- [x] Passive SLA escalation detection and unit test verification.

## Milestone 2: Enterprise Integration (✅ Completed)
- [x] Raw SQL performance-tuned queries with SQL SECURITY DEFINER views protecting institutional tables.
- [x] Resilient background notification dispatchers for Email, SMS (BulkSMS SNISTA), and WhatsApp (Unified Messaging).
- [x] Google OAuth SSO integration with strict institutional directory whitelist validation against `teacher_info`.
- [x] Multi-CA least-loaded auto-routing engine with campus block mapping parity and fallback CA defaults.
- [x] Interactive SLA escalation and visual overdue indicators (>24h) across assignee and faculty queues.

## Milestone 3: Monitoring & Logging Analytics (✅ Completed)
- [x] Prometheus metrics scraping endpoint (`/metrics` and `/health/metrics`) exposing pool health, checkout latencies (p50/p95), query retries, and ticket counts.
- [x] Comprehensive dual-probe health endpoints: lightweight liveness (`/health`) and authenticated deep readiness (`/health/deep`).
- [x] Interactive department analytics and 1-click full-screen Metabase business intelligence embedding.
- [x] Structured logging and immutable security audit event ledger (`helpdesk_audit_events`).
- [x] Deterministic migration runner (`scripts/migrate.py`) with advisory locking (`GET_LOCK`), SHA-256 checksum validation, and rollback (`down`) support.

