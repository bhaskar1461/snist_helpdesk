-- =============================================================================
-- SNIST Help Desk — Dedicated Help Desk Schema (Database: helpdesk)
-- Host: seg.sreenidhi.edu.in
-- Upstream Institutional Authorities (Read-Only):
--   - sreenidhi.teacher_info (Faculty & Staff Master)
--   - sreenidhi.branch_detail (Departments & HOD mappings)
--   - sreenidhi.location (Physical campus rooms and blocks)
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------------------------------
-- 1. Help Desk Staff Roles (Administrative Overrides & Emergency Accounts ONLY)
-- Zero faculty are duplicated here. Only holds administrative assignments
-- (e.g. SUPER_ADMIN, ADMIN, or emergency accounts like admin@gmail.com).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_staff_roles (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  teacher_id INT UNSIGNED NULL COMMENT 'Matches sreenidhi.teacher_info.TEACHER_ID if faculty',
  name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL,
  password_hash VARCHAR(255) NULL COMMENT 'Used only for emergency local login',
  role ENUM('SUPER_ADMIN', 'ADMIN', 'CA') NOT NULL,
  department VARCHAR(255) NULL,
  phone VARCHAR(32) NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_staff_email (email),
  KEY idx_staff_teacher_id (teacher_id),
  KEY idx_staff_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Categories Table
-- Mapped to departments and default Concerned Authorities (Assignees).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_categories (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_name VARCHAR(120) NOT NULL,
  department VARCHAR(80) NOT NULL,
  assigned_ca_id INT UNSIGNED NULL COMMENT 'References sreenidhi.teacher_info.TEACHER_ID or helpdesk_staff_roles.id',
  is_active TINYINT(1) NOT NULL DEFAULT 1,
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
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_problem_cat_name (category_id, problem_name),
  KEY idx_problem_category (category_id),
  CONSTRAINT fk_problem_types_cat FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 4. Tickets Table
-- Primary ticket tracking. References institutional TEACHER_ID for users
-- and sreenidhi.location for physical campus locations.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_tickets (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  title VARCHAR(180) NOT NULL,
  description TEXT NOT NULL,
  category_id INT UNSIGNED NOT NULL,
  problem_type_id INT UNSIGNED NULL,
  created_by INT UNSIGNED NOT NULL COMMENT 'References sreenidhi.teacher_info.TEACHER_ID',
  assigned_to INT UNSIGNED NOT NULL COMMENT 'References sreenidhi.teacher_info.TEACHER_ID',
  status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NOT NULL DEFAULT 'PENDING',
  org_id VARCHAR(20) NOT NULL DEFAULT '2000',
  location_id INT NULL COMMENT 'References sreenidhi.location.id',
  submission_key CHAR(36) NULL COMMENT 'UUID to prevent double submission',
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
-- Audit history for status changes, remarks, attachments, and resolution times.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ticket_activity (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ticket_id INT UNSIGNED NOT NULL,
  action_by INT UNSIGNED NOT NULL COMMENT 'References sreenidhi.teacher_info.TEACHER_ID or staff ID',
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
  author_id INT UNSIGNED NOT NULL COMMENT 'References sreenidhi.teacher_info.TEACHER_ID or staff ID',
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
  ca_id INT UNSIGNED NOT NULL COMMENT 'References sreenidhi.teacher_info.TEACHER_ID or staff ID',
  block VARCHAR(120) NOT NULL DEFAULT '',
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

SET FOREIGN_KEY_CHECKS = 1;
