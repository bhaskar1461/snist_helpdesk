-- Performance Indexing Migration (v7) for SNIST Helpdesk
-- Optimizes ticket listing, category lookups, department filters, and RBAC auth queries

-- 1. Index helpdesk_tickets for fast dashboard queries and status filters
ALTER TABLE helpdesk_tickets ADD INDEX idx_tickets_dept_status (org_id, category_id, status, created_at);
ALTER TABLE helpdesk_tickets ADD INDEX idx_tickets_assignee (assigned_to, status);
ALTER TABLE helpdesk_tickets ADD INDEX idx_tickets_creator (created_by, status);

-- 2. Index helpdesk_categories for active department filtering
ALTER TABLE helpdesk_categories ADD INDEX idx_categories_dept_active (department, is_active);

-- 3. Index helpdesk_ca_assignments for category-block mapping
ALTER TABLE helpdesk_ca_assignments ADD INDEX idx_ca_assignments_cat_block (category_id, block, ca_id);

-- 4. Index helpdesk_users for role and department filtering
ALTER TABLE helpdesk_users ADD INDEX idx_users_dept_role_active (department, role, is_active);
