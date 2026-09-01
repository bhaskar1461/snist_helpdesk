# Project Knowledge & Rules for snist_helpdesk

## Architecture & Project Structure
- **Framework**: Flask Python Web Application with MySQL / DemoDbService.
- **Factory & Blueprints**: `app/__init__.py` exposes `create_app()`. Blueprints are located in `app/`:
  - `auth`: Authentication & session management.
  - `tickets`: Ticket creation (`/tickets/create`), status transitions, notes.
  - `management`: Admin, HOD, Category & CA assignment management.
  - `dashboards`: Role-specific dashboard views.
  - `analytics`: Analytics metrics, Chart.js fallback, Metabase embedding.
  - `api`: RESTful endpoints.
- **Legacy Routes**: `app.py` contains core legacy routes and standalone handlers.
- **Database Access Layer**: `db_services.py` (`DemoDbService` & `LiveDbService`). Provides connection pooling, SQL queries, user authentication, ticket mutations, and audit logging.

## Database Tables & Schema
- `helpdesk_users`: User ID, name, email, password hash, role (`SUPER_ADMIN`, `ADMIN`, `HOD`, `CA` / `ASSIGNEE`, `FACULTY`), department, phone, org_id.
- `helpdesk_tickets`: Ticket ID, title, description, category_id, created_by, assigned_to, status (`PENDING`, `IN_PROGRESS`, `ON_HOLD`, `RESOLVED`, `REOPENED`), org_id, location_id.
- `helpdesk_categories`: Category ID, category_name, department, assigned_ca_id (fallback/default CA), org_id, is_active.
- `helpdesk_ca_assignments`: Assignment ID, ca_id, category_id, block, org_id.
- `helpdesk_audit_events` & `helpdesk_ticket_activity`: Action logs and activity history.
- `branch_detail` & `location`: Organizational metadata, departments, and room/block mappings.

## SMS & WhatsApp Messaging System
- **SMS Gateway**: BulkSMS HTTP API (`http://bulksmsapps.com/api/apismsv2.aspx`) with Sender ID `SNISTA`.
- **WhatsApp Gateway**: Unified Messaging Platform API (`https://103.229.250.150/unified/v2/send`) using Template ID `1773697` and From Number `919133386678`.
- **Phone Lookup Priority**: `DemoDbService.get_user_phone()` checks `helpdesk_users.phone` $\rightarrow$ `teacher_info.MOBILE_PHONE` $\rightarrow$ `sys_administrators.MOBILE_NO` $\rightarrow$ `SMS_TEST_NUMBER`.

## Roles & Access Control
- `SUPER_ADMIN` / `ADMIN`: Full access to system configuration, user management, and category assignment.
- `HOD`: Department head managing CA assignments and department tickets.
- `CA` / `ASSIGNEE`: Concerned Authority / Assignee managing assigned tickets and updating ticket status. (`CA` and `ASSIGNEE` are alias roles in `role_required`).
- `FACULTY`: Standard user role creating and tracking complaints/tickets.

## Business Logic & UI Invariants
- **Ticket Creation**: Users can select any department that has active categories. Backend must validate category active status (`is_active == 1`) and category department matching.
- **Assignee Selection**: Assignee dropdowns and category assignments must strictly filter users by the category's department. Cross-department assignee mapping is strictly prohibited on both frontend and backend.
- **Assignee Ticket Mutations**: All permission checks for updating ticket status (`can_update` in frontend and `update_ticket_status` in backend) must check `role in ["CA", "ASSIGNEE"]` and compare `ticket.assigned_to == user.id` OR `ticket.assigned_to_email.lower() == user.email.lower()`, with administrative override for `SUPER_ADMIN`, `ADMIN`, and departmental `HOD`.
- **Multi-CA Allocation & Least-Loaded Auto-Routing**: Multiple CAs can be mapped to a single category for specific blocks or "All Blocks". When routing new tickets (`resolve_assigned_ca`), the engine first matches exact location block mappings (`LOWER(block) = LOWER(input) OR block IN ('All Blocks', 'all', 'campus')`). If multiple CAs match, auto-routing dynamically selects the CA with the least number of open tickets (`PENDING`, `IN_PROGRESS`, `REOPENED`).
- **Role-Based Navigation & Ticket Scoping**:
  - Super Admin, Admin, HOD: Segregated "My Tickets" (`scope="own"`) and "All Tickets" (`scope="all"` or department tickets).
  - Assignees (CA / ASSIGNEE): "Dashboard", "Create Ticket", "My Tickets", "Assigned Tickets", and "Reports".
  - Faculty: Restricted strictly to "My Tickets" (no access to All Tickets).
- **Terminology**: Use "Assignee" instead of "Concerned Authority / CA" across UI labels, page titles, navigation links, and flash messages.
- **Department Normalization**: When filtering or mapping departments (e.g. in `filterAssigneesByDept` or `dept_map`), match both the short `BRANCH_CODE` (e.g. `Facilities`, `CSE`, `ECE`) and full `BRANCH_NAME` (e.g. `Facilities & Estates`, `Computer Science & Engineering`) to prevent dropdown options from being hidden by strict string comparisons.

## Seed Data Sources & Legacy Dumps
- **`teacher_info` (`New Project 20260803 1346.sql`)**:
  - Contains 2,240 SNIST faculty & staff records.
  - Notice: ~724 records use personal `@gmail.com` and have `ACTIVE = 0`. Database loaders (`fetch_reference_users` in `db_services.py` and `init_demo_db.py`) must NOT restrict by `ACTIVE = 1` so that all personal and institutional email addresses are seeded into `helpdesk_users`.
- **`sys_administrators` (`New Project 20260716 1511.sql`)**:
  - Contains 20 real Department Incharges and CAs (ICT: `managerict@sreenidhi.edu.in`, Facilities: `managerfs@sreenidhi.edu.in`, CTO: `cto@sreenidhi.edu.in`, SAP: `srinivas.n@sreenidhi.edu.in`, HCM: `ramkumar.b@sreenidhi.edu.in`, MM: `chakradhar.n@sreenidhi.edu.in`).
  - Roles must be mapped to `CA`, `ADMIN`, or `SUPER_ADMIN` in `helpdesk_users` rather than defaulting to `FACULTY`.
- **`sys_complaint` (`New Project 20260716 1511.sql`)**:
  - Contains 758 historical complaints spanning 24 campus blocks (`Block-I` through `Block-XIII`, `Admin Block`, `Centeral library`, etc.) and 23 problem categories.
  - Can be migrated into `helpdesk_tickets` and `location` tables for realistic analytics and testing.

## Application Server & VM Execution
- **Server Engine**: Running on **Granian (Rust-based WSGI server)** via systemd service `snist_helpdesk.service` (`/etc/systemd/system/snist_helpdesk.service`).
- **Command**: `/home/ubuntu/projects/snist_helpdesk/venv/bin/granian --interface wsgi --host 0.0.0.0 --port 5000 --workers 2 --blocking-threads 4 --respawn-failed-workers --access-log wsgi:application`
- **Testing Guidelines**:
  - **Run Tests**: Always execute `python -m pytest tests` (targeting `tests/` specifically avoids running one-off scripts in `scratch/`).
  - **Test Base**: `tests/test_base.py` provides `HelpdeskTestCase` and `GLOBAL_DB_STATE` mock database state.

## Ubuntu VirtualBox VM Execution Workflow
- **Automated VM Setup**: Inside an Ubuntu VirtualBox VM environment, run `bash install.sh` from the repository root to automatically install dependencies (Git, Docker, Docker Compose), initialize `.env`, boot containers, seed database profiles, and configure Metabase dashboards.
- **Port Forwarding (Host <-> VirtualBox Guest)**:
  - **Web App**: Guest Port `5001` (or `5000`) -> Host Port `5001` (`http://localhost:5001`)
  - **Metabase UI**: Guest Port `3002` -> Host Port `3002` (`http://localhost:3002`)
- **DB Initialization**: Run `python scripts/init_demo_db.py` inside the VM virtualenv.

## Remote Ubuntu VM SSH Execution
- **SSH Keys**: SSH key options available in `C:\Users\bhask\.ssh\` (`bhaskar.pem`, `vm_assistant_key`, `proofsy_key.pem`, `temp_key`).
- **VM SSH Command**: `ssh -i "C:\Users\bhask\.ssh\bhaskar.pem" ubuntu@127.0.0.1 -p 2222` (or target IP).
- **VM Workspace Path**: Projects inside the VM reside under `~/projects/` or `~/snist_helpdesk`.

## UI/UX Design System & Frontend Invariants

### 1. Global Visual Aesthetics & Enterprise Standards
- **Quality Target**: Modern enterprise SaaS (comparable to Linear, Jira Service Management, ServiceNow, Freshservice).
- **Typography**: Google Fonts `Inter` (body/UI), `Outfit` (headings/kpis), and `Space Grotesk` (ticket IDs and monospace codes).
- **Color Palette & Accent Consistency**:
  - Primary: `#4f46e5` (Indigo-600) with hover `#4338ca` (Indigo-700) and light background `#eef2ff`.
  - Status Accents: Pending (`#f59e0b` / Amber), In Progress (`#2563eb` / Blue), On Hold (`#8b5cf6` / Purple), Resolved (`#10b981` / Emerald), Reopened (`#ef4444` / Rose).
  - Neutrals: Slate-50 through Slate-900 with subtle 1px `#e2e8f0` borders and soft multi-layered shadows.
- **De-cluttering & Information Hierarchy**:
  - Strictly avoid developer-facing explanations, database table names, or redundant instructional paragraphs on end-user screens.
  - Structure pages with: Clean Title + Kicker + Subtitle + Actionable Form/Table Card.

### 2. Terminology Standardization (Strict)
- **Assignee**: Use "Assignee" instead of "Concerned Authority" or "CA" across all UI labels, page titles, navigation links, modals, and flash messages.
- **Assigned To**: Use "Assigned To" instead of "Allocated To" or "Assigned CA".
- **Ticket / Tickets**: Use "Ticket" / "Tickets" instead of "Complaint" / "Complaints".
- **Create Ticket**: Use "Create Ticket" instead of "Create Complaint".

### 3. Component Architecture & Ergonomics
- **Data Tables**:
  - Every table must reside inside a `.table-card` or `.dashboard-card` with an `overflow-x: auto;` wrapper.
  - Column headers must use uppercase, bold typography with `#f8fafc` background.
  - Ticket IDs must render as clickable `#<id>` monospace badges linking to ticket details.
  - Numbers and dates must be aligned cleanly with whitespace nowrap.
- **Forms & Location Cascades**:
  - Location blocks, floors, and rooms must align in uniform multi-column grids with equal vertical heights and clear disabled states ("Choose block first").
  - Category dropdowns must dynamically reload upon department selection with zero layout shifts.
- **Action Buttons**:
  - Primary actions (`Submit Ticket`, `Create User`, `Apply`) must use primary gradient with Lucide icons.
  - Secondary actions (`Cancel`, `Back to Dashboard`, `Export`) must use bordered neutral styling.



