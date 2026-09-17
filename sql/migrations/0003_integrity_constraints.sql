-- =============================================================================
-- Migration: 0003_integrity_constraints.sql
-- Description: Business integrity CHECK constraints on tickets, activity, categories.
-- Non-transactional DDL Note: Implicit commit on execution.
-- =============================================================================

-- Ticket integrity constraints (positive IDs, timestamp order)
SET @cnt = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'chk_tickets_assigned_created');
SET @sql = IF(@cnt = 0, "ALTER TABLE helpdesk_tickets ADD CONSTRAINT chk_tickets_assigned_created CHECK (assigned_to > 0 AND created_by > 0)", "SELECT 'Constraint chk_tickets_assigned_created exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @cnt = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'chk_tickets_updated_after_created');
SET @sql = IF(@cnt = 0, "ALTER TABLE helpdesk_tickets ADD CONSTRAINT chk_tickets_updated_after_created CHECK (updated_at >= created_at)", "SELECT 'Constraint chk_tickets_updated_after_created exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Activity integrity constraint
SET @cnt = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'chk_activity_action_by');
SET @sql = IF(@cnt = 0, "ALTER TABLE helpdesk_ticket_activity ADD CONSTRAINT chk_activity_action_by CHECK (action_by > 0)", "SELECT 'Constraint chk_activity_action_by exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Category integrity constraint
SET @cnt = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'chk_categories_assigned_ca');
SET @sql = IF(@cnt = 0, "ALTER TABLE helpdesk_categories ADD CONSTRAINT chk_categories_assigned_ca CHECK (assigned_ca_id IS NULL OR assigned_ca_id > 0)", "SELECT 'Constraint chk_categories_assigned_ca exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- CA Assignment integrity constraint
SET @cnt = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'chk_ca_assignments_ca_id');
SET @sql = IF(@cnt = 0, "ALTER TABLE helpdesk_ca_assignments ADD CONSTRAINT chk_ca_assignments_ca_id CHECK (ca_id > 0)", "SELECT 'Constraint chk_ca_assignments_ca_id exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Composite indexes for query performance
SET @idx = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'helpdesk_tickets' AND INDEX_NAME = 'idx_tickets_org_status');
SET @sql = IF(@idx = 0, "ALTER TABLE helpdesk_tickets ADD INDEX idx_tickets_org_status (org_id, status)", "SELECT 'Index idx_tickets_org_status exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'helpdesk_tickets' AND INDEX_NAME = 'idx_tickets_org_created');
SET @sql = IF(@idx = 0, "ALTER TABLE helpdesk_tickets ADD INDEX idx_tickets_org_created (org_id, created_at)", "SELECT 'Index idx_tickets_org_created exists'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- DOWN
-- ALTER TABLE helpdesk_tickets DROP CHECK chk_tickets_assigned_created;
-- ALTER TABLE helpdesk_tickets DROP CHECK chk_tickets_updated_after_created;
-- ALTER TABLE helpdesk_ticket_activity DROP CHECK chk_activity_action_by;
-- ALTER TABLE helpdesk_categories DROP CHECK chk_categories_assigned_ca;
-- ALTER TABLE helpdesk_ca_assignments DROP CHECK chk_ca_assignments_ca_id;
-- ALTER TABLE helpdesk_tickets DROP INDEX idx_tickets_org_status;
-- ALTER TABLE helpdesk_tickets DROP INDEX idx_tickets_org_created;
