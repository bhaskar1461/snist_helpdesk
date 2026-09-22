# Helpdesk System — Pending Changes & Implementation Guide

This document captures the complete technical analysis, root causes, exact file locations, and ready-to-apply code solutions for all reported issues and feature requests across the Helpdesk application.

---

## Table of Contents
1. [Issue 1: Category "Edit" Modal Broken (e.g., Configuration)](#issue-1-category-edit-modal-broken)
2. [Issue 2: HOD Ticket Management Selective Reassignment Shows "0 OPEN TICKETS"](#issue-2-hod-ticket-management-shows-0-open-tickets)
3. [Issue 3: User Role Updates in User Management Not Persisting](#issue-3-user-role-updates-not-persisting)
4. [Issue 4: SSO Login Active Status Validation (`teacher_info.ACTIVE`)](#issue-4-sso-login-active-status-validation)
5. [Issue 5: Metabase Department Filtering & Dynamic Dashboard Refresh](#issue-5-metabase-department-filtering)
6. [Issue 6: Department Dropdowns Filtering (Active HODs & Active Categories)](#issue-6-department-dropdowns-filtering)
7. [Issue 7: Assignee Performance Leaderboard & Fallback Analytics Charts](#issue-7-assignee-performance--fallback-charts)

---

## Issue 1: Category "Edit" Modal Broken

### Problem Description
On `/management/category-assignments`, clicking the "Edit" action button on categories like "Configuration" (or any category with mapped blocks) fails to open the modal dialog.

### Root Cause Analysis
In `templates/category_ca_management.html` (around line 828):
```html
<button type="button" class="tbl-action-btn"
  data-blocks="{{ mapped_blocks|tojson|e }}"
  onclick="openEditModal(..., JSON.parse(this.dataset.blocks || '[]'))">
```
- In Jinja2, `tojson` returns a `Markup` object. Piping it to `|e` does **not** escape HTML double quotes within an attribute enclosed by double quotes (`data-blocks="..."`).
- The rendered HTML becomes `data-blocks="["All Blocks", ...]"`, prematurely terminating the HTML attribute after `"["`.
- When clicked, `JSON.parse("[")` throws an uncaught JavaScript syntax error: `SyntaxError: Unexpected end of JSON input`, halting script execution and preventing the modal from displaying.

### Required Code Fixes

#### 1. In `templates/category_ca_management.html`
Simplify the Edit button to pass only the category ID:
```html
<!-- Replace the existing Edit button on lines 825-835 with: -->
<button type="button" class="tbl-action-btn" onclick="openEditModal({{ item.id }})">
  Edit
</button>
```

#### 2. In JavaScript of `templates/category_ca_management.html`
Update `openEditModal` to look up category data directly from `allCategoriesData` (already injected into `<script id="smart-search-categories-data" type="application/json">`):
```javascript
function openEditModal(catId) {
  const cat = (window.allCategoriesData || []).find(c => Number(c.id) === Number(catId));
  if (!cat) {
    console.error("Category not found for ID:", catId);
    return;
  }

  // Populate hidden input and fields
  document.getElementById('edit-category-id').value = cat.id;
  document.getElementById('edit-category-name').value = cat.category_name;
  document.getElementById('edit-department').value = cat.department;

  // Filter assignees by department and select current default CA
  filterAssigneesByDept('edit-department', 'edit-assigned-ca');
  document.getElementById('edit-assigned-ca').value = cat.assigned_ca_id || '';

  // Set is_active checkbox
  document.getElementById('edit-is-active').checked = (cat.is_active == 1);

  // Set selected blocks in multi-select component
  setSelectedBlocks('edit-block-select', cat.mapped_blocks || []);

  // Display overlay
  const overlay = document.getElementById('edit-overlay');
  if (overlay) {
    overlay.classList.add('active');
  }
}
```

#### 3. Category Filter Dropdown in `app/management.py`
In `category_assignments` view function (`app/management.py` line ~640):
- Pass `departments=modal_departments` (which contains only departments with active categories) instead of `departments=live_departments(...)` (all 70 branches).

---

## Issue 2: HOD Ticket Management Shows "0 OPEN TICKETS"

### Problem Description
On `/hod/ticket-management`, all assignees in ICT (and other departments) display `0 OPEN TICKETS`, which disables the checkbox and prevents the HOD from selectively reassigning tickets, despite ICT having 91 open tickets in the database.

### Root Cause Analysis
In `db_services.py:2564` (`get_ca_open_tickets`):
```sql
sql = self.ticket_query_base() + " AND t.assigned_to = %s AND t.status IN ('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'REOPENED')"
```
- The assignee list displayed on the screen (`cas_in_dept` from `list_users`) uses `helpdesk_staff_roles.id` (e.g. ID `55` for Jitta Chandra Shekar Reddy).
- However, tickets in `helpdesk_tickets` are stored with `assigned_to = teacher_info.TEACHER_ID` (e.g. `457`).
- Querying solely `t.assigned_to = 55` finds 0 tickets because `55 != 457`.

### Required Code Fixes

#### 1. In `db_services.py` (`get_ca_open_tickets`):
Expand the query to resolve both the staff role ID and the associated teacher ID:
```python
def get_ca_open_tickets(self, ca_id: int, department: str = None, org_id: str = None) -> list:
    """Fetch all active open tickets assigned to a specific CA (by staff role ID or teacher ID)."""
    # 1. Resolve teacher_id if ca_id corresponds to a helpdesk_staff_roles row
    teacher_id = None
    with self.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT teacher_id FROM helpdesk_staff_roles WHERE id = %s", (ca_id,))
        row = cur.fetchone()
        if row and row.get("teacher_id"):
            teacher_id = row["teacher_id"]

    # 2. Build query matching either ID
    if teacher_id:
        sql = self.ticket_query_base() + " AND (t.assigned_to = %s OR t.assigned_to = %s) AND t.status IN ('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'REOPENED')"
        params = [ca_id, teacher_id]
    else:
        sql = self.ticket_query_base() + " AND t.assigned_to = %s AND t.status IN ('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'REOPENED')"
        params = [ca_id]

    if department:
        sql += " AND LOWER(c.department) = LOWER(%s)"
        params.append(department)
    if org_id:
        sql += " AND t.org_id = %s"
        params.append(org_id)
    sql += " ORDER BY t.created_at DESC"

    with self.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        tickets = cur.fetchall()
        return [self.add_escalation_status(t) for t in tickets]
```

#### 2. In `db_services.py` (`reassign_tickets`):
Update the ticket ownership validation:
```python
# Check that the ticket was assigned to source_ca or source_teacher_id
source_ids = {source_ca_id}
if source_ca.get("teacher_id"):
    source_ids.add(source_ca["teacher_id"])

if ticket.get("assigned_to") not in source_ids:
    raise ValueError(f"Ticket #{t_id} is not currently assigned to {source_ca.get('name')}.")
```

---

## Issue 3: User Role Updates Not Persisting

### Problem Description
In User Management (`/user-management`), editing a user's role (e.g. changing from `FACULTY` to `CA` or `HOD`) displays a green success flash message, but the role does not persist and reverts back on reload.

### Root Cause Analysis
1. In `db_services.py:1656` (`update_user`):
   - The query executes `UPDATE helpdesk_users ...` followed by `UPDATE helpdesk_staff_roles WHERE id = %s OR teacher_id = %s`.
   - If the user is seeded from institutional `teacher_info`, neither `helpdesk_users` nor `helpdesk_staff_roles` may have an existing row for that user.
   - Result: 0 rows are updated, and the role change is lost silently.
2. In `db_services.py:1138` (`_resolve_teacher_role`):
   - The method previously only recognized roles if `elevated in ("SUPER_ADMIN", "ADMIN")`, completely discarding explicit assignments of `HOD`, `CA`, and `FACULTY`.

### Required Code Fixes

#### 1. In `db_services.py` (`update_user`):
Perform an UPSERT into `helpdesk_staff_roles`:
```python
# In DemoDbService.update_user(self, user_id, payload):
with self.connection() as conn, conn.cursor() as cur:
    # 1. Update helpdesk_users if exists
    cur.execute("""
        UPDATE helpdesk_users 
        SET name = COALESCE(%s, name),
            role = COALESCE(%s, role),
            department = COALESCE(%s, department),
            phone = COALESCE(%s, phone)
        WHERE id = %s
    """, (payload.get("name"), payload.get("role"), payload.get("department"), payload.get("phone"), user_id))

    # 2. Check if a helpdesk_staff_roles row exists for this user_id or teacher_id
    cur.execute("SELECT id FROM helpdesk_staff_roles WHERE id = %s OR teacher_id = %s", (user_id, user_id))
    existing = cur.fetchone()

    if existing:
        cur.execute("""
            UPDATE helpdesk_staff_roles
            SET role = COALESCE(%s, role),
                department = COALESCE(%s, department),
                phone = COALESCE(%s, phone)
            WHERE id = %s
        """, (payload.get("role"), payload.get("department"), payload.get("phone"), existing["id"]))
    else:
        # User only existed in teacher_info, insert into helpdesk_staff_roles
        cur.execute("""
            INSERT INTO helpdesk_staff_roles (teacher_id, name, email, role, department, phone, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE 
                role = VALUES(role),
                department = VALUES(department),
                phone = VALUES(phone)
        """, (
            user_id,
            payload.get("name"),
            payload.get("email"),
            payload.get("role"),
            payload.get("department"),
            payload.get("phone")
        ))
    conn.commit()
```

#### 2. In `db_services.py` (`_resolve_teacher_role`):
Return any elevated role found in `helpdesk_staff_roles`:
```python
def _resolve_teacher_role(self, email: str, staff_roles_map: dict) -> str:
    """Return explicit role from helpdesk_staff_roles if assigned, otherwise fallback."""
    if not email:
        return "FACULTY"
    email_clean = email.strip().lower()
    if email_clean in staff_roles_map:
        return staff_roles_map[email_clean]
    return "FACULTY"
```

---

## Issue 4: SSO Login Active Status Validation

### Problem Description
Teachers with `ACTIVE == 0` in `teacher_info` are currently able to log in via SSO. The system must verify the `ACTIVE` status and block access if `ACTIVE == 0`.

### Root Cause Analysis
- `db_services.py` (`get_user_by_email`) fetches teacher records from `teacher_info` without selecting or checking `COALESCE(t.ACTIVE, 1)`.
- `app/auth.py` (`sso_login` and `sso_callback`) only checks user existence without validating active status.

### Required Code Fixes

#### 1. In `db_services.py` (`get_user_by_email`):
Include the `is_active` status in the returned user dictionary:
```sql
SELECT 
    t.TEACHER_ID AS id,
    t.TEACHER_NAME AS name,
    t.EMAIL AS email,
    t.MOBILE_PHONE AS phone,
    COALESCE(t.ACTIVE, 1) AS is_active,
    ...
FROM teacher_info t
WHERE LOWER(t.EMAIL) = LOWER(%s)
```

#### 2. In `app/auth.py` (`sso_callback` and `mock_sso`):
Check `is_active` after user lookup:
```python
# In app/auth.py sso_callback():
user = demo_db.get_user_by_email(email)
if not user:
    flash("No account found matching this institutional email.", "error")
    return redirect(url_for("auth.login"))

if user.get("is_active") == 0 or user.get("ACTIVE") == 0:
    flash("Access restricted: Your institutional account is marked inactive in the staff directory. Please contact the administrator.", "error")
    return redirect(url_for("auth.login"))
```

---

## Issue 5: Metabase Department Filtering

### Problem Description
On `/analytics`, selecting a department from the department dropdown refreshes the Chart.js summary, but does **not** filter or refresh the embedded Metabase dashboard.

### Root Cause Analysis
In `app/analytics.py:130` (`api_metabase_embed`):
```python
payload = {
    "resource": {"dashboard": dashboard_id},
    "params": {},  # <--- Hardcoded empty dictionary!
    "exp": int(time.time()) + (10 * 60),
}
```
1. The backend ignores `request.args.get("department")` and sends empty parameters to Metabase.
2. In `templates/analytics.html`, the `change` listener on `#analytics-dept-filter` only re-runs `refreshAnalytics()`, but does not invoke `loadMetabaseDashboard()`.

### Required Code Fixes

#### 1. In `app/analytics.py` (`api_metabase_embed`):
Support passing the department parameter into the JWT payload:
```python
@analytics_bp.route("/api/analytics/metabase-embed")
@role_required("HOD", "ADMIN", "SUPER_ADMIN")
def api_metabase_embed():
    """Generate a signed Metabase embed URL with department filtering."""
    if not METABASE_SITE_URL or not METABASE_SECRET_KEY:
        return jsonify({"error": "Metabase is not configured."}), 503

    dashboard_key = request.args.get("dashboard", "overview")
    department = request.args.get("department", "").strip()

    dashboard_map = {
        "overview": int(os.getenv("METABASE_DASHBOARD_OVERVIEW", "4")),
        "department": int(os.getenv("METABASE_DASHBOARD_DEPARTMENT", "4")),
        "trends": int(os.getenv("METABASE_DASHBOARD_TRENDS", "2")),
        "ca_performance": int(os.getenv("METABASE_DASHBOARD_CA_PERF", "3")),
    }
    dashboard_id = dashboard_map.get(dashboard_key) or dashboard_map.get("overview", 4)

    try:
        import jwt
        import time

        params = {}
        if department:
            params["department"] = department

        payload = {
            "resource": {"dashboard": dashboard_id},
            "params": params,
            "exp": int(time.time()) + (10 * 60),
        }

        token = jwt.encode(payload, METABASE_SECRET_KEY, algorithm="HS256")
        embed_url = f"{METABASE_SITE_URL}/embed/dashboard/{token}#bordered=false&titled=false"

        return jsonify({"embed_url": embed_url})
    except Exception as e:
        log.error("Failed to generate Metabase embed URL: %s", e)
        return jsonify({"error": "Failed to generate embedded dashboard URL."}), 500
```

#### 2. In `templates/analytics.html`:
Pass department filter in `loadMetabaseDashboard` and hook it to dropdown change:
```javascript
let currentMetabaseKey = 'overview';

async function loadMetabaseDashboard(key, btnElement) {
  if (key) currentMetabaseKey = key;
  // Update button active state
  ...
  const dept = getDeptFilter();
  const url = `/api/analytics/metabase-embed?dashboard=${currentMetabaseKey}${dept ? '&department=' + encodeURIComponent(dept) : ''}`;
  const res = await fetch(url);
  // ... render iframe with embed_url
}

// In document.getElementById('analytics-dept-filter') change event:
document.getElementById('analytics-dept-filter').addEventListener('change', () => {
  refreshAnalytics();
  {% if metabase_enabled %}
  loadMetabaseDashboard(currentMetabaseKey);
  {% endif %}
});
```

---

## Issue 6: Department Dropdowns Filtering

### Problem Description
1. On Management Dashboard (`/super-admin/dashboard`, `/admin/dashboard`), the HOD Impersonation dropdown showed all 70 institutional branches. User requirement: **"only show departments that have active HODs"**.
2. On Analytics (`/analytics`), the department dropdown showed all 70 branches instead of active Helpdesk departments.

### Required Code Fixes

#### 1. In `app/helpers.py`:
Add helper functions to retrieve departments with active HODs and active categories:
```python
def departments_with_active_hods(demo_db, org_id: str) -> list[dict]:
    """Return only departments that have an active HOD assigned."""
    hod_list = demo_db.list_users(role="HOD", org_id=org_id)
    active_depts = set()
    for u in hod_list:
        dept = (u.get("department") or "").strip()
        if dept and u.get("is_active", 1) == 1:
            active_depts.add(dept)

    # Return formatted list with display names
    out = []
    for dept_code in sorted(active_depts):
        display_name = DEPT_DISPLAY_NAMES.get(dept_code.upper(), dept_code)
        out.append({"code": dept_code, "name": display_name})
    return out
```

#### 2. In `app/dashboards.py` & `app.py`:
Pass `impersonation_departments=departments_with_active_hods(demo_db, user["org_id"])` to `management_dashboard.html`.

#### 3. In `templates/management_dashboard.html`:
```html
<select name="department" id="impersonate_dept" required class="select-control">
  <option value="">Choose Department with Active HOD...</option>
  {% for d in impersonation_departments %}
    <option value="{{ d.code }}">{{ d.code }}{% if d.name and d.name != d.code %} — {{ d.name }}{% endif %}</option>
  {% endfor %}
</select>
```

#### 4. In `app/analytics.py`:
Change `departments = live_departments(user["org_id"])` to:
```python
departments = active_category_departments(demo_db, user["org_id"])
```

---

## Issue 7: Assignee Performance & Fallback Charts

### Problem Description
In the screenshot, the fallback cards:
- "Tickets by Department" (`#deptChart`)
- "Tickets by Category" (`#catChart`)
- "Resolution Velocity Trends" (`#trendChart`)
- "Assignee Performance Leaderboard" (`#ca-perf-table`)

were blank or displaying 0 records when Metabase was also embedded or when fallback endpoints were queried.

### Root Cause Analysis
1. `demo_db.ticket_trends()` and `demo_db.ca_performance_stats()` are returning empty lists `[]` on live database setups because the methods were missing/stubbed or missing proper joins on `helpdesk_tickets` and `helpdesk_staff_roles` / `teacher_info`.
2. The user specified: **"the assignee performance dashboard should be visible [in] the fallback models as well"**. The fallback models must compute real metrics from `helpdesk_tickets` so that both the embedded Metabase dashboard and the native Chart.js/Table fallback views are fully functional.

### Required Code Fixes

#### 1. In `db_services.py` (`ca_performance_stats`):
Implement full query computing assignee statistics:
```python
def ca_performance_stats(self, org_id: str = None, department: str = None) -> list[dict]:
    """Compute performance metrics for each Assignee (CA)."""
    sql = """
        SELECT 
            COALESCE(s.id, t.TEACHER_ID) AS ca_id,
            COALESCE(s.name, t.TEACHER_NAME, u.name) AS name,
            COALESCE(s.email, t.EMAIL, u.email) AS email,
            COALESCE(s.department, u.department, 'ICT') AS department,
            COUNT(tk.id) AS total_assigned,
            SUM(CASE WHEN tk.status = 'RESOLVED' THEN 1 ELSE 0 END) AS total_resolved,
            SUM(CASE WHEN tk.status IN ('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'REOPENED') THEN 1 ELSE 0 END) AS active_tickets,
            ROUND(AVG(CASE WHEN tk.status = 'RESOLVED' AND tk.updated_at IS NOT NULL 
                     THEN TIMESTAMPDIFF(HOUR, tk.created_at, tk.updated_at) 
                     ELSE NULL END), 1) AS avg_resolution_hours
        FROM helpdesk_tickets tk
        LEFT JOIN helpdesk_staff_roles s ON (tk.assigned_to = s.id OR tk.assigned_to = s.teacher_id)
        LEFT JOIN teacher_info t ON tk.assigned_to = t.TEACHER_ID
        LEFT JOIN helpdesk_users u ON tk.assigned_to = u.id
        WHERE tk.assigned_to IS NOT NULL
    """
    params = []
    if org_id:
        sql += " AND tk.org_id = %s"
        params.append(org_id)
    if department:
        sql += " AND LOWER(COALESCE(s.department, u.department)) = LOWER(%s)"
        params.append(department)
        
    sql += """
        GROUP BY ca_id, name, email, department
        HAVING total_assigned > 0
        ORDER BY total_resolved DESC, total_assigned DESC
    """
    with self.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        for r in rows:
            r["avg_resolution_hours"] = float(r["avg_resolution_hours"] or 0.0)
            r["total_assigned"] = int(r["total_assigned"] or 0)
            r["total_resolved"] = int(r["total_resolved"] or 0)
            r["active_tickets"] = int(r["active_tickets"] or 0)
        return rows
```

#### 2. In `db_services.py` (`ticket_trends`):
Implement trends query grouping by month/week/day:
```python
def ticket_trends(self, org_id: str = None, department: str = None, period: str = "monthly") -> list[dict]:
    """Compute creation and resolution trends over time."""
    date_format = "%Y-%m" if period == "monthly" else "%Y-%u" if period == "weekly" else "%Y-%m-%d"
    sql = f"""
        SELECT 
            DATE_FORMAT(created_at, '{date_format}') AS period,
            COUNT(*) AS created,
            SUM(CASE WHEN status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved
        FROM helpdesk_tickets
        WHERE created_at IS NOT NULL
    """
    params = []
    if org_id:
        sql += " AND org_id = %s"
        params.append(org_id)
    if department:
        sql += " AND category_id IN (SELECT id FROM helpdesk_categories WHERE LOWER(department) = LOWER(%s))"
        params.append(department)
        
    sql += f" GROUP BY period ORDER BY period DESC LIMIT 12"
    with self.connection() as conn, conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        return list(reversed(rows))
```

---

## Verification & Testing Guide

Once these modifications are applied, verify them with the following automated and manual test steps:

1. **Automated Unit Tests**:
   ```powershell
   python -m pytest tests
   ```
   All 139 tests should pass with zero regressions.

2. **Category Edit Button Verification**:
   - Navigate to `http://localhost:5001/management/category-assignments`.
   - Click the "Edit" button on "Configuration" or any category with multiple mapped blocks.
   - Verify that the Edit modal opens instantly with name, department, default assignee, active status, and mapped blocks pre-selected.

3. **HOD Ticket Management Reassignment Verification**:
   - Log in as HOD (`hod@sreenidhi.edu.in` or impersonate ICT HOD).
   - Navigate to `/hod/ticket-management`.
   - Verify that assignees with open tickets (such as Jitta Chandra Shekar Reddy) show the accurate count (e.g., 91 open tickets) instead of 0.
   - Check the select box and verify tickets can be selected and reassigned.

4. **User Management Role Update Verification**:
   - Navigate to `/user-management`.
   - Edit an institutional teacher's role to `CA` or `HOD` and submit.
   - Refresh the page and confirm the new role is retained.

5. **SSO Active Status Verification**:
   - Attempt to log in with a `teacher_info` email where `ACTIVE == 0`.
   - Verify that the user is rejected with the flash error: *"Access restricted: Your institutional account is marked inactive in the staff directory."*

6. **Analytics & Metabase Department Filter Verification**:
   - Navigate to `/analytics`.
   - Select a department (e.g. "ICT") from the department filter.
   - Verify both the native fallback charts (Department, Category, Trends, Assignee Leaderboard) and the embedded Metabase dashboard refresh filtered by that department.
