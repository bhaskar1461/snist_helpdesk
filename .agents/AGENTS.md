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
- `helpdesk_users`: User ID, name, email, password hash, role (`SUPER_ADMIN`, `ADMIN`, `HOD`, `CA` / `ASSIGNEE`, `FACULTY`), department, org_id.
- `helpdesk_tickets`: Ticket ID, title, description, category_id, created_by, assigned_to, status (`PENDING`, `IN_PROGRESS`, `ON_HOLD`, `RESOLVED`, `REOPENED`), org_id, location_id.
- `helpdesk_categories`: Category ID, category_name, department, org_id, is_active.
- `helpdesk_ca_assignments`: Assignment ID, ca_id, category_id, block, org_id.
- `helpdesk_audit_events` & `helpdesk_ticket_activity`: Action logs and activity history.
- `branch_detail` & `location`: Organizational metadata, departments, and room/block mappings.

## Roles & Access Control
- `SUPER_ADMIN` / `ADMIN`: Full access to system configuration, user management, and category assignment.
- `HOD`: Department head managing CA assignments and department tickets.
- `CA` / `ASSIGNEE`: Concerned Authority / Assignee managing assigned tickets and updating ticket status. (`CA` and `ASSIGNEE` are alias roles in `role_required`).
- `FACULTY`: Standard user role creating and tracking complaints/tickets.

## Business Logic & UI Invariants
- **Ticket Creation**: Users can select any department that has active categories. Backend must validate category active status (`is_active == 1`) and category department matching.
- **Assignee Selection**: Assignee dropdowns and category assignments must strictly filter users by the category's department. Cross-department assignee mapping is strictly prohibited on both frontend and backend.
- **Terminology**: Use "Assignee" instead of "Concerned Authority / CA" across UI labels, page titles, navigation links, and flash messages.


## Testing Guidelines
- **Run Tests**: Always execute `python -m pytest tests` (targeting `tests/` specifically avoids running one-off scripts in `scratch/`).
- **Test Base**: `tests/test_base.py` provides `HelpdeskTestCase` and `GLOBAL_DB_STATE` mock database state.

## Ubuntu VirtualBox VM Execution Workflow
- **Automated VM Setup**: Inside an Ubuntu VirtualBox VM environment, run `bash install.sh` from the repository root to automatically install dependencies (Git, Docker, Docker Compose), initialize `.env`, boot containers, seed database profiles, and configure Metabase dashboards.
- **Manual VM Container Start**: Execute `docker compose up -d --build` inside the VM.
- **Port Forwarding (Host <-> VirtualBox Guest)**:
  - **Web App**: Guest Port `5001` (or `5000`) -> Host Port `5001` (`http://localhost:5001`)
  - **Metabase UI**: Guest Port `3002` -> Host Port `3002` (`http://localhost:3002`)
- **DB Initialization**: Run `docker compose exec -T web python scripts/init_demo_db.py` inside the VM.

## Remote Ubuntu VM SSH Execution
- **SSH Keys**: SSH key options available in `C:\Users\bhask\.ssh\` (`bhaskar.pem`, `vm_assistant_key`, `proofsy_key.pem`, `temp_key`).
- **VM SSH Command**: `ssh -i "C:\Users\bhask\.ssh\bhaskar.pem" ubuntu@127.0.0.1 -p 2222` (or target IP).
- **VM Workspace Path**: Projects inside the VM reside under `~/projects/` or `~/snist_helpdesk`.


