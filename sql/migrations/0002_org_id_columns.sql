-- =============================================================================
-- Migration: 0002_org_id_columns.sql
-- Description: Multi-tenant organization scoping (org_id) across all core helpdesk tables.
-- Non-transactional DDL Note: Implicit commit on execution.
-- =============================================================================

-- Add org_id to helpdesk_categories if not present
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'helpdesk_categories' AND COLUMN_NAME = 'org_id');
SET @sql = IF(@col_exists = 0, "ALTER TABLE helpdesk_categories ADD COLUMN org_id VARCHAR(20) NOT NULL DEFAULT '2000'", "SELECT 'Column org_id already exists on helpdesk_categories'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add org_id to helpdesk_ca_assignments if not present
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'helpdesk_ca_assignments' AND COLUMN_NAME = 'org_id');
SET @sql = IF(@col_exists = 0, "ALTER TABLE helpdesk_ca_assignments ADD COLUMN org_id VARCHAR(20) NOT NULL DEFAULT '2000'", "SELECT 'Column org_id already exists on helpdesk_ca_assignments'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add org_id to helpdesk_problem_types if not present
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'helpdesk_problem_types' AND COLUMN_NAME = 'org_id');
SET @sql = IF(@col_exists = 0, "ALTER TABLE helpdesk_problem_types ADD COLUMN org_id VARCHAR(20) NOT NULL DEFAULT '2000'", "SELECT 'Column org_id already exists on helpdesk_problem_types'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add org_id to helpdesk_staff_roles if not present
SET @col_exists = (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'helpdesk_staff_roles' AND COLUMN_NAME = 'org_id');
SET @sql = IF(@col_exists = 0, "ALTER TABLE helpdesk_staff_roles ADD COLUMN org_id VARCHAR(20) NOT NULL DEFAULT '2000'", "SELECT 'Column org_id already exists on helpdesk_staff_roles'");
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- DOWN
-- ALTER TABLE helpdesk_categories DROP COLUMN org_id;
-- ALTER TABLE helpdesk_ca_assignments DROP COLUMN org_id;
-- ALTER TABLE helpdesk_problem_types DROP COLUMN org_id;
-- ALTER TABLE helpdesk_staff_roles DROP COLUMN org_id;
