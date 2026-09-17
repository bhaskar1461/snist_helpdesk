-- =============================================================================
-- Phase 1 Verification SQL Script: Institutional Views & Core Helpdesk Tables
-- Target Database: helpdesk (Host: seg.sreenidhi.edu.in)
-- User: demo
-- =============================================================================

-- 1. Verify user permissions and grants
-- Expected: GRANT USAGE on *.*, SELECT, INSERT, UPDATE, etc. on `helpdesk`.*
SHOW GRANTS FOR CURRENT_USER();

-- 2. Verify local DEFINER view access to institutional teacher_info
-- Expected: 2250 rows (institutional faculty & staff records)
SELECT COUNT(*) AS teacher_info_count FROM teacher_info;

-- 3. Verify local DEFINER view access to institutional branch_detail
-- Expected: 72 rows (campus academic and administrative departments)
SELECT COUNT(*) AS branch_detail_count FROM branch_detail;

-- 4. Verify local DEFINER view access to institutional location
-- Expected: 213 rows (campus blocks, floors, and rooms)
SELECT COUNT(*) AS location_count FROM location;

-- 5. Verify helpdesk_tickets table access and row count
-- Expected: 1 on production (or 766 if targeting seeded dev environment)
SELECT COUNT(*) AS ticket_count FROM helpdesk_tickets;

-- 6. Inspect ticket records
-- Expected: id=1, title='Test WiFi Issue', status='PENDING'
SELECT id, title, status FROM helpdesk_tickets;

-- 7. Verify existence of core helpdesk tables and views
-- Expected: helpdesk_audit_events, helpdesk_ca_assignments, helpdesk_categories,
--           helpdesk_problem_types, helpdesk_staff_roles, helpdesk_ticket_activity,
--           helpdesk_ticket_notes, helpdesk_tickets, helpdesk_users (9 matching objects)
SHOW TABLES LIKE 'helpdesk_%';
