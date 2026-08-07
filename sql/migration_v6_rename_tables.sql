-- Migration V6: Rename demo_* tables to production helpdesk_* names
-- This script renames existing demo tables safely if they exist.

DROP PROCEDURE IF EXISTS rename_if_exists;
DELIMITER //
CREATE PROCEDURE rename_if_exists(IN old_tbl VARCHAR(64), IN new_tbl VARCHAR(64))
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = DATABASE() AND table_name = old_tbl
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = DATABASE() AND table_name = new_tbl
    ) THEN
        SET @query = CONCAT('RENAME TABLE `', old_tbl, '` TO `', new_tbl, '`');
        PREPARE stmt FROM @query;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
    END IF;
END //
DELIMITER ;

CALL rename_if_exists('demo_users', 'helpdesk_users');
CALL rename_if_exists('demo_categories', 'helpdesk_categories');
CALL rename_if_exists('demo_tickets', 'helpdesk_tickets');
CALL rename_if_exists('demo_ticket_activity', 'helpdesk_ticket_activity');
CALL rename_if_exists('demo_ticket_notes', 'helpdesk_ticket_notes');
CALL rename_if_exists('demo_problem_types', 'helpdesk_problem_types');
CALL rename_if_exists('demo_ca_assignments', 'helpdesk_ca_assignments');
CALL rename_if_exists('demo_ca_locations', 'helpdesk_ca_locations');
CALL rename_if_exists('demo_audit_events', 'helpdesk_audit_events');
CALL rename_if_exists('demo_locations', 'helpdesk_locations');

DROP PROCEDURE IF EXISTS rename_if_exists;
