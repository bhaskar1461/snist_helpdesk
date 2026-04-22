# Project Plan

## Project Snapshot

This project is now a Flask + MySQL helpdesk system designed around:

- strict RBAC
- automatic category-based CA assignment
- safe separation between live read-only data and demo write tables
- role-specific dashboards and APIs

Current system roles:

- `SUPER_ADMIN`
- `ADMIN`
- `HOD`
- `CA`
- `FACULTY`

Current architecture:

- `app.py`
  Handles web routes, RBAC checks, dashboards, form flows, exports, and API endpoints.
- `db_services.py`
  Contains:
  - `LiveDbService` for read-only access to live MySQL tables
  - `DemoDbService` for all application CRUD against demo tables
- `sql/demo_schema.sql`
  Defines the normalized demo schema
- `scripts/init_demo_db.py`
  Initializes demo schema and seeds starter data

Live DB usage:

- Read-only reference access to:
  - `teacher_info`
  - `branch_detail`
  - optionally `location`

Demo DB usage:

- `demo_users`
- `demo_categories`
- `demo_tickets`
- `demo_ticket_activity`

## Important Constraints

1. Never modify live application/reference tables.
2. Use only `SELECT` on live tables.
3. All write operations must go to `demo_*` tables only.
4. Keep role logic strict and explicit.
5. Preserve automatic assignment:
   `category -> assigned_ca_id -> demo_tickets.assigned_to`

## Current Build Status

### Implemented

1. Demo schema designed and created
- `demo_users`
- `demo_categories`
- `demo_tickets`
- `demo_ticket_activity`

2. Service-layer split added
- `LiveDbService`
- `DemoDbService`

3. RBAC login flow added using `demo_users`

4. Faculty flow added
- dashboard
- own tickets
- ticket creation

5. CA flow added
- assigned tickets
- self-created tickets
- status updates
- remarks
- attachment upload
- time taken

6. HOD flow added
- dashboard
- department ticket visibility
- category-to-CA mapping

7. Admin / Super Admin flow added
- dashboards
- user management
- full ticket list

8. Ticket filtering and export added
- status
- department
- org
- date range
- CSV
- Excel

9. Automatic assignment added
- ticket creation resolves CA from `demo_categories.assigned_ca_id`

10. Safe live integration added
- org resolution from live DB
- department list from live DB
- reference user fetch API from live DB

### Verified

1. Demo schema initialized successfully in MySQL
2. Admin login and dashboard routes responded correctly
3. User management and live reference APIs returned successfully
4. Faculty ticket creation auto-assigned the mapped CA
5. CA status update successfully changed ticket status

## Technical Notes / Known Limitations

1. MySQL permission limitation
- The current MySQL user can create tables, but cannot create foreign key constraints because `REFERENCES` privilege is denied.
- We still keep a normalized schema shape.
- Referential integrity is currently enforced in the service layer instead of the DB engine.

2. Password storage
- Demo users are still using plain text passwords.
- This must be replaced with hashed passwords before any production use.

3. Attachment storage
- Attachments are stored locally under `uploads/`.
- Metadata is tracked in `demo_ticket_activity`.
- No file size/type whitelist is enforced yet.

4. App structure
- The service split is done, but route logic is still concentrated in `app.py`.

## Feature Backlog

Below is the updated feature list, grouped by priority.

### Phase 1: Stabilization And Safety

Priority: Highest

1. Move secrets/config to environment-only mode
- move `app.secret_key` to env
- document required `MYSQL_*` variables
- add `.env.example`

2. Harden bootstrap behavior
- make demo schema init optional by environment flag
- surface DB bootstrap errors more clearly in UI/logs

3. Add stronger validation
- email validation
- duplicate user/category handling
- safer integer parsing
- safer empty-field handling

4. Add upload restrictions
- allowed extensions
- max file size
- safe download/view path handling

5. Add graceful DB failure states
- friendly message when live DB or demo DB is unavailable
- avoid silent fallback for important failures

### Phase 2: RBAC Hardening

Priority: Highest

1. Review every route for role access
- confirm all page routes
- confirm all API routes
- confirm export routes

2. Tighten scope rules
- `SUPER_ADMIN`: full access
- `ADMIN`: manage users, view system tickets
- `HOD`: only department-scoped ticket/category access
- `CA`: only assigned tickets for status changes
- `FACULTY`: only own tickets

3. Formalize allowed status transitions
- `PENDING -> IN_PROGRESS`
- `IN_PROGRESS -> RESOLVED`
- optionally allow rollback rules only if explicitly needed

4. Prevent unauthorized category mapping
- HOD should not assign CA outside allowed department rules unless Super Admin overrides

### Phase 3: User Management Completion

Priority: High

1. Add full edit UI for users
- inline edit or dedicated edit form
- update role, department, email, password

2. Add delete protection UX
- confirmation before deletion
- clear explanation when referenced users cannot be deleted

3. Add department-wise filters
- role
- department
- created date if needed

4. Add HOD assignment workflow clarity
- show which users are currently HODs
- expose role change flow cleanly

### Phase 4: Category / CA Management Completion

Priority: High

1. Add edit UI for category mappings
- currently create/delete is clearer than update flow
- add full edit controls

2. Prevent duplicate mappings with friendly UI feedback
- same `category_name + department`

3. Support search/filter in category management
- by department
- by CA
- by category name

4. Add optional bulk mapping support
- useful if many categories must be assigned at once

### Phase 5: Ticket Workflow Completion (✅ COMPLETED)

Priority: High

1. Add ticket detail page
- single ticket view
- full description
- created by
- assigned CA
- status history
- remarks
- attachments
- timestamps

2. Add ticket activity timeline
- powered by `demo_ticket_activity`
- visible to correct roles only

3. Improve create-ticket UX
- department-aware category dropdowns
- better empty states when no mapping exists

4. Add status badges and transition hints
- show what action is expected next

5. Add ticket comments visibility
- faculty should see CA remarks where appropriate

### Phase 6: Reporting And Export (✅ COMPLETED)

Priority: Medium-High

1. Expand exports
- per-role export scope
- category-wise export
- department-wise export
- monthly export

2. Add dashboard analytics
- tickets by status
- tickets by category
- tickets by department
- overdue/aging tickets

3. Add SLA/reporting groundwork
- created vs resolved age
- time taken summaries from `demo_ticket_activity`

### Phase 7: API Completion (✅ COMPLETED)

Priority: High

1. Review all CRUD API coverage
- `GET live departments`
- `GET live users`
- CRUD `demo_users`
- CRUD `demo_categories`
- CRUD `demo_tickets`

2. Add API validation responses
- standard JSON error format
- field-level error details

3. Add authentication/authorization consistency
- same rules for UI and API

4. Add ticket activity API
- fetch one ticket history
- optionally add a detail endpoint

### Phase 8: Security (✅ COMPLETED)

Priority: High

1. Password hashing
- replace plain text storage
- support password change flow

2. Session security
- secure cookie settings
- session expiry
- CSRF protection review for forms

3. Audit logging
- login success/failure
- user create/update/delete
- category mapping changes
- ticket status changes

4. Production hardening
- disable debug mode
- add proper logging config

### Phase 9: Testing

Priority: High

1. Unit tests
- `LiveDbService`
- `DemoDbService`
- auto-assignment logic
- org resolution logic

2. Route tests
- login
- dashboard access
- user management CRUD
- category mapping CRUD
- ticket creation
- CA status update
- export endpoints

3. API tests
- role enforcement
- payload validation
- CRUD happy paths
- invalid references

4. Smoke checklist
- login for each role
- create ticket as faculty
- verify auto assignment
- update ticket as assigned CA
- export ticket list

### Phase 10: UX / UI Improvements

Priority: Medium

1. Better edit flows
- inline edit forms or modal forms

2. Better empty states
- no categories
- no CA mappings
- no tickets

3. Attachment handling improvements
- download link
- preview for image/pdf where possible

4. Better ticket hover/detail behavior
- currently hover is limited
- move toward dedicated ticket detail screens

5. Consistent messaging
- flash messages
- validation errors
- success/error wording

## Recommended Immediate Order Before More Features

This is the best next implementation order:

1. Config cleanup
- env-based secret key
- `.env.example`
- setup notes

2. Validation and DB error handling pass
- forms
- APIs
- uploads

3. Complete user/category edit flows
- finish the management UI properly

4. Build ticket detail + activity timeline
- this will unlock clearer workflows for all roles

5. Add password hashing and session hardening

6. Add tests for critical flows

## Immediate Next Milestone

### Milestone A: Safe Foundations

- env cleanup
- bootstrap hardening
- validation improvements
- upload restrictions

### Milestone B: Management Completion

- full user CRUD UI
- full category mapping UI
- better role-scope enforcement

### Milestone C: Ticket Lifecycle Completion

- ticket detail screen
- activity timeline
- refined CA/faculty visibility

### Milestone D: Security + Tests

- password hashing
- session hardening
- route/API/service tests

## Current Best Next Step

Before adding new business features, do this next:

1. clean up config and secrets
2. add validation and DB error handling
3. finish user/category edit flows

That will make every later feature safer and easier to maintain.
