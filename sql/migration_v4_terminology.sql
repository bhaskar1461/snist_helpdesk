-- Migration v4: Terminology Updates (Concerned Authority -> Assignee)

-- 1. Update demo_users role ENUM to support ASSIGNEE
ALTER TABLE demo_users MODIFY COLUMN role ENUM('SUPER_ADMIN', 'ADMIN', 'HOD', 'ASSIGNEE', 'CA', 'FACULTY') NOT NULL;

-- 2. Update existing CA roles to ASSIGNEE
UPDATE demo_users SET role = 'ASSIGNEE' WHERE role = 'CA';

-- 3. Alias / Rename columns & tables if needed (maintaining backwards-compatibility views or FKs)
-- Note: demo_categories.assigned_ca_id, demo_tickets.assigned_to, demo_ca_assignments.ca_id
