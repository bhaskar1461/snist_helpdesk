# Org-Separated Super Admin Scope Implementation Plan (Revised)

This plan outlines the changes to partition system management and ticket analytics between SNIST (org_id=2000) and SNU (org_id=3000) Super Admins without modifying the `demo_users` database table structure. Organization scoping is determined dynamically in Python.

## Proposed Changes

### Database Schema

#### [MODIFY] [demo_schema.sql](file:///C:/Users/bhask/Desktop/Projects/project-share/snist_helpdesk/sql/demo_schema.sql)
- Ensure the `demo_users` table definition does not have the `org_id` column or index.
- Keep the `org_id` column on `demo_tickets` as originally defined.

---

### Database Services

#### [MODIFY] [db_services.py](file:///C:/Users/bhask/Desktop/Projects/project-share/snist_helpdesk/db_services.py)

1. **`list_users`**: Add optional `org_id` filtering parameter. Filter returned users dynamically in Python by resolving their email domain or department organization from the live database.
2. **`hod_overview`**: Add optional `org_id` parameter to scope HOD summary count. Filter by HODs whose departments match the given organization in the live `branch_detail` table.
3. **`ticket_stats_by_department`**: Add optional `org_id` parameter to scope department stats.
4. **`ticket_stats_by_category`**: Add optional `org_id` parameter to scope category stats.
5. **`dashboard_summary`**: Filter tickets by the viewer's dynamic `org_id`.
6. **`list_tickets`**: Filter tickets by the viewer's dynamic `org_id`.

---

### Application Controllers

#### [MODIFY] [app.py](file:///C:/Users/bhask/Desktop/Projects/project-share/snist_helpdesk/app.py)

1. **`bootstrap_demo_database`**: Remove/avoid any migration that adds `org_id` column to the `demo_users` table.
2. **`current_user`**: Dynamically resolve and inject `org_id` in the user session object using Python-side logic:
   * Emails containing `"snu"` or ending with `suh.edu.in` resolve to **`3000` (SNU)**.
   * Emails containing `"sreenidhi"` or ending with `sreenidhi.edu.in` resolve to **`2000` (SNIST)**.
   * Check department mappings to respective organizations in the live database.
   * Default fallback is **`2000` (SNIST)**.
3. **`live_departments`**: Add optional `org_id` parameter to filter returned departments so dropdowns only show valid values for the logged-in user's organization.
4. **`user_management`**: Pass the current user's dynamic `org_id` to `list_users` to scope the view.
5. **`api_demo_users`**: Filter listed users by current user's dynamic `org_id`.
6. **`api_live_departments`**: Filter live departments by current user's dynamic `org_id`.
7. **`api_live_users`**: Filter live reference users by current user's dynamic `org_id`.

---

## Verification Plan

### Automated Tests
- Restart the Flask server.
- Verify migration checks do not alter `demo_users`.

### Manual Verification
1. Login as **Super Admin** (`admin@gmail.com`) and verify that only **SNIST** dashboard statistics, HODs, tickets, and departments are visible.
2. Login as **SNU Admin** (`snu.admin@gmail.com`) and verify that only **SNU** dashboard statistics, HODs, tickets, and departments are visible.
3. Verify that the user management table for SNU Admin only shows SNU users and SNU departments.
