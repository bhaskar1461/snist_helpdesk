-- =============================================================================
-- SNIST Helpdesk System — Canonical Production Database Schema
-- Table Prefix: helpdesk_*
-- Database Engine: MySQL / InnoDB (utf8mb4)
-- Upstream Institutional Master (Read-Only):
--   - teacher_info (Faculty & Staff Master)
--   - branch_detail (Departments & HOD mappings)
--   - location (Physical campus rooms and blocks)
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------------------------------
-- 1. Help Desk Staff Roles (Administrative Overrides & Emergency Accounts)
-- Holds administrative assignments (SUPER_ADMIN, ADMIN, CA/Assignees).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_staff_roles (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  teacher_id INT UNSIGNED NULL COMMENT 'Matches teacher_info.TEACHER_ID if faculty',
  name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL,
  password_hash VARCHAR(255) NULL COMMENT 'Used for local password authentication',
  role ENUM('SUPER_ADMIN', 'ADMIN', 'HOD', 'ASSIGNEE', 'CA', 'FACULTY') NOT NULL DEFAULT 'ASSIGNEE',
  department VARCHAR(255) NULL,
  phone VARCHAR(32) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_staff_email (email),
  KEY idx_staff_teacher_id (teacher_id),
  KEY idx_staff_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Categories Table
-- Ticket categories mapped to departments and default Assignees (CAs).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_categories (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_name VARCHAR(120) NOT NULL,
  department VARCHAR(80) NOT NULL,
  assigned_ca_id INT UNSIGNED NULL COMMENT 'References teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_categories_name_dept (category_name, department),
  KEY idx_categories_ca (assigned_ca_id),
  KEY idx_categories_dept_active (department, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 3. Problem Types Table
-- Granular problem types classified under main categories.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_problem_types (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_id INT UNSIGNED NOT NULL,
  problem_name VARCHAR(180) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_problem_cat_name (category_id, problem_name),
  KEY idx_problem_category (category_id),
  CONSTRAINT fk_problem_types_cat FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 4. Tickets Table
-- Primary ticket tracking table with submission_key deduplication.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_tickets (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  title VARCHAR(180) NOT NULL,
  description TEXT NOT NULL,
  category_id INT UNSIGNED NOT NULL,
  problem_type_id INT UNSIGNED NULL,
  created_by INT UNSIGNED NOT NULL COMMENT 'References teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  assigned_to INT UNSIGNED NOT NULL COMMENT 'References teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NOT NULL DEFAULT 'PENDING',
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  location_id INT UNSIGNED NULL COMMENT 'References location.id',
  submission_key CHAR(36) NULL COMMENT 'UUID to prevent duplicate submissions',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tickets_submission_key (submission_key),
  KEY idx_tickets_status (status),
  KEY idx_tickets_assigned_to (assigned_to),
  KEY idx_tickets_created_by (created_by),
  KEY idx_tickets_category (category_id),
  KEY idx_tickets_location (location_id),
  KEY idx_tickets_org_status (org_id, status),
  KEY idx_tickets_org_created (org_id, created_at),
  CONSTRAINT fk_tickets_category FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 5. Ticket Activity Log Table
-- Audit log for status transitions, remarks, attachments, and resolution times.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ticket_activity (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ticket_id INT UNSIGNED NOT NULL,
  action_by INT UNSIGNED NOT NULL COMMENT 'References teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  from_status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NULL,
  to_status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NOT NULL,
  remarks TEXT NULL,
  time_taken VARCHAR(120) NULL,
  attachment_path VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_activity_dedup (ticket_id, action_by, from_status, to_status, created_at),
  KEY idx_ticket_activity_ticket (ticket_id),
  KEY idx_ticket_activity_user (action_by),
  CONSTRAINT fk_ticket_activity_ticket FOREIGN KEY (ticket_id) REFERENCES helpdesk_tickets (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 6. Ticket Internal Notes Table
-- Private notes added to tickets by Assignees, Admins, or HODs.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ticket_notes (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ticket_id INT UNSIGNED NOT NULL,
  author_id INT UNSIGNED NOT NULL COMMENT 'References teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  note TEXT NOT NULL,
  is_internal TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_notes_dedup (ticket_id, author_id, created_at),
  KEY idx_ticket_notes_ticket (ticket_id),
  KEY idx_ticket_notes_author (author_id),
  CONSTRAINT fk_ticket_notes_ticket FOREIGN KEY (ticket_id) REFERENCES helpdesk_tickets (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 7. CA Category / Block Assignments Table
-- Maps Assignees to specific categories and physical campus blocks.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ca_assignments (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_id INT UNSIGNED NOT NULL,
  ca_id INT UNSIGNED NOT NULL COMMENT 'References teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  block VARCHAR(120) NOT NULL DEFAULT '',
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ca_category_block (category_id, ca_id, block),
  KEY idx_ca_assignments_ca (ca_id),
  KEY idx_ca_assignments_category (category_id),
  CONSTRAINT fk_ca_assign_cat FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 8. System Audit Events Table
-- Security audit trail for admin actions, login attempts, and role mutations.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_audit_events (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_type VARCHAR(60) NOT NULL,
  actor_id INT UNSIGNED NOT NULL,
  target_type VARCHAR(40) NULL,
  target_id INT UNSIGNED NULL,
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  details TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_audit_event_type (event_type),
  KEY idx_audit_actor (actor_id),
  KEY idx_audit_org (org_id),
  KEY idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 9. Unified User Identity View (helpdesk_users)
-- Virtual identity layer combining helpdesk_staff_roles and teacher_info.
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW helpdesk_users AS
SELECT 
  s.id AS id,
  s.name AS name,
  s.email AS email,
  s.password_hash AS password,
  s.role AS role,
  s.department AS department,
  s.phone AS phone,
  s.is_active AS is_active,
  s.created_at AS created_at
FROM helpdesk_staff_roles s
UNION ALL
SELECT 
  t.TEACHER_ID AS id,
  t.TEACHER_NAME AS name,
  t.EMAIL_ID AS email,
  '' AS password,
  CASE 
    WHEN b.HOD_ID = t.TEACHER_ID OR t.DESIGNATION LIKE '%Head%' THEN 'HOD' 
    ELSE 'FACULTY' 
  END AS role,
  COALESCE(b.BRANCH_CODE, 'General') AS department,
  t.MOBILE_PHONE AS phone,
  1 AS is_active,
  '2026-01-01 00:00:00' AS created_at
FROM teacher_info t
LEFT JOIN branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
WHERE t.EMAIL_ID IS NOT NULL AND t.EMAIL_ID != ''
  AND NOT EXISTS (
    SELECT 1 FROM helpdesk_staff_roles s2 WHERE s2.id = t.TEACHER_ID
  );

SET FOREIGN_KEY_CHECKS = 1;
