# SNIST Helpdesk System

A production-grade, secure enterprise ticketing and campus service platform developed for the **Sreenidhi Institute of Science and Technology (SNIST)**. The platform provides automated multi-tier ticket routing, department-isolated Concerned Authority (CA / Assignee) allocations, selective ticket reassignment for absent authorities, multi-channel messaging (SMS & WhatsApp), and Metabase visual analytics.

---

## Key Features

- **Least-Loaded Dynamic Ticket Auto-Routing**:
  - Maps multiple Concerned Authorities (CAs) to problem categories for specific campus blocks or all campus facilities.
  - Automatically routes newly submitted tickets to the least-loaded matching Assignee with fallback protection to department HOD and Administrators.
- **HOD Selective Ticket Reassignment (`/hod/ticket-management`)**:
  - Enables Department Heads (HODs) to view open tickets assigned to absent or unavailable CAs, selectively check specific tickets, and transfer them atomically to another active CA within the department with audit logging.
- **Role-Based Governance & Security Architecture**:
  - **Super Admin**: Institution-wide governance across all 20+ departments, user account management, campus hierarchy (blocks/floors/rooms), global category management, audit log access, and read-only ticket supervision.
  - **HOD (Head of Department)**: Departmental ticket oversight, category CA assignment, and selective ticket reassignment.
  - **Concerned Authority (CA / Assignee)**: Operational status transitions (`PENDING` $\rightarrow$ `IN_PROGRESS` $\rightarrow$ `ON_HOLD` $\rightarrow$ `RESOLVED`), resolution remarks, time tracking, attachments, and internal staff notes.
  - **Faculty**: Ticket submission with multi-level location cascades, live tracking of submitted tickets, and ticket reopening within SLA windows.
- **Context-Aware Contact Phone Scoping**:
  - CAs directly see the faculty submitter's verified mobile number for rapid field communication.
  - Faculty see only the assigned CA's direct phone number for call assistance.
- **High-Performance Server-Side Pagination**:
  - Instantaneous load times (< 50ms) across 2,300+ institutional faculty and staff directory records with backend search and multi-role filtering.
- **Embedded Metabase Analytics**:
  - JWT-signed Metabase dashboards (Overview, Departmental Trends, CA Performance, SLA Breaches) with automatic containerized bootstrapping and Chart.js fallback.
- **Multi-Channel Notification Gateway**:
  - Asynchronous dispatch queues supporting BulkSMS HTTP API (`SNISTA`) and Unified Messaging Platform WhatsApp templates (`1773697`).
- **Enterprise Security Hardening**:
  - Magic-byte file signature validation blocking executable masquerading.
  - Anti-duplication UUID `submission_key` idempotency constraints.
  - CSRF protection, rate limiting, and session security.

---

## Technology Stack

- **Backend**: Python 3.11, Flask 3.1.0, Flask-WTF, PyMySQL Connection Pooling
- **WSGI / App Server**: Granian (Rust-based WSGI engine) / Gunicorn
- **Database**: MySQL 8.x (`seg_demo` database schema)
- **Analytics & BI**: Metabase 0.49+ (Docker containerized with JWT static embedding)
- **Frontend & UI**: Google Fonts (`Inter`, `Outfit`, `Space Grotesk`), Vanilla CSS Design System, Lucide Icons, Smart-Select Components
- **Containerization**: Docker, Docker Compose

---

## User Roles & Permission Matrix

| Capability | Super Admin | HOD | Assignee (CA) | Faculty |
| :--- | :---: | :---: | :---: | :---: |
| **View All Campus Tickets** | ✅ *All Depts* | 🏢 *Own Dept* | ❌ | ❌ |
| **Update Ticket Status** | ❌ *View-Only* | ✅ *Own Dept* | ✅ *Assigned Only* | ❌ *(Reopen own)* |
| **Selective Ticket Reassignment** | 🌐 *(Acting as HOD)* | ✅ *Own Dept* | ❌ | ❌ |
| **Category & Assignee Allocations** | ✅ *All Depts* | ✅ *Own Dept* | ❌ | ❌ |
| **User Directory Management** | ✅ *Full Access* | 🏢 *Dept Users* | ❌ | ❌ |
| **Campus Location Management** | ✅ *Full Access* | ❌ | ❌ | ❌ |
| **Metabase & Institutional Analytics** | ✅ *Campus-Wide* | 🏢 *Dept KPIs* | 📌 *CA Reports* | ❌ |

---

## Quick Start (Docker)

### 1. Clone & Configure Environment
```bash
git clone https://github.com/bhaskar1461/snist_helpdesk.git
cd snist_helpdesk
cp .env.example .env
```

### 2. Boot All Services
```bash
docker compose up -d --build
```

### 3. Access Portals
- **Web Application**: [http://localhost:5000](http://localhost:5000) (or port `5001`)
- **Metabase BI**: [http://localhost:3002](http://localhost:3002)

---

## Automated VPS / VM Installation

To deploy on a clean Ubuntu VPS or VirtualBox guest VM:
```bash
bash install.sh
```

---

## Automated Test Suite

Run the full automated test suite (74 tests covering RBAC, mutations, auto-routing, exports, and edge cases):
```bash
python -m pytest tests
```

---

## Database Architecture & Migrations

- **Production Schema**: [`sql/production_schema.sql`](sql/production_schema.sql)
- **Legacy Migration Pipeline**:
  - `scripts/migrate_legacy_data.py`: Imports historical complaints (`sys_complaint`) and administrators (`sys_administrators`) into normalized `helpdesk_*` tables.
  - `scripts/fix_legacy_creators.py`: Resolves legacy ticket creators to verified faculty records in `teacher_info`.
- **Demo DB Initializer**: `python scripts/init_demo_db.py`

---

## License

Distributed under the MIT License. Developed for Sreenidhi Educational Group.
