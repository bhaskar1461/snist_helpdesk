-- Migration v9: Database Integrity and Multi-Tenant Scoping
-- Adds org_id to core helpdesk tables and enforces database-level integrity constraints.

-- 1. Multi-tenant org_id columns
ALTER TABLE helpdesk_categories
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(20) NOT NULL DEFAULT '2000';

ALTER TABLE helpdesk_ca_assignments
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(20) NOT NULL DEFAULT '2000';

ALTER TABLE helpdesk_staff_roles
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(20) NOT NULL DEFAULT '2000';

ALTER TABLE helpdesk_problem_types
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(20) NOT NULL DEFAULT '2000';

-- 2. Ticket integrity constraints (positive IDs, timestamp order)
ALTER TABLE helpdesk_tickets
    ADD CONSTRAINT chk_tickets_assigned_created
    CHECK (assigned_to > 0 AND created_by > 0);

ALTER TABLE helpdesk_tickets
    ADD CONSTRAINT chk_tickets_updated_after_created
    CHECK (updated_at >= created_at);

-- 3. Activity integrity constraint
ALTER TABLE helpdesk_ticket_activity
    ADD CONSTRAINT chk_activity_action_by
    CHECK (action_by > 0);

-- 4. Category and Assignment integrity constraints
ALTER TABLE helpdesk_categories
    ADD CONSTRAINT chk_categories_assigned_ca
    CHECK (assigned_ca_id IS NULL OR assigned_ca_id > 0);

ALTER TABLE helpdesk_ca_assignments
    ADD CONSTRAINT chk_ca_assignments_ca_id
    CHECK (ca_id > 0);
