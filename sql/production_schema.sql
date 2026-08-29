-- =============================================================================
-- SNIST Helpdesk System — Production Database Schema
-- Table Prefix: helpdesk_*
-- Database Engine: MySQL / InnoDB (utf8mb4)
-- =============================================================================

SET FOREIGN_KEY_CHECKS = 0;

-- -----------------------------------------------------------------------------
-- 1. Users Table
-- Stores helpdesk user credentials, roles, and department assignments.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_users (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name VARCHAR(120) NOT NULL,
  email VARCHAR(190) NOT NULL,
  password VARCHAR(255) NOT NULL,
  role ENUM('SUPER_ADMIN', 'ADMIN', 'HOD', 'ASSIGNEE', 'CA', 'FACULTY') NOT NULL,
  department VARCHAR(255) NOT NULL,
  phone VARCHAR(32) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_helpdesk_users_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 2. Categories Table
-- Ticket categories mapped to departments and default Concerned Authorities.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_categories (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_name VARCHAR(120) NOT NULL,
  department VARCHAR(80) NOT NULL,
  assigned_ca_id INT UNSIGNED NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_helpdesk_categories_name_dept (category_name, department),
  KEY idx_helpdesk_categories_ca (assigned_ca_id),
  KEY idx_categories_dept_active (department, is_active),
  CONSTRAINT fk_helpdesk_categories_ca FOREIGN KEY (assigned_ca_id) REFERENCES helpdesk_users (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 3. Problem Types Table
-- Granular problem types sub-categorized under main categories.
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
  CONSTRAINT fk_helpdesk_problem_types_cat FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id) ON DELETE CASCADE
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
  created_by INT UNSIGNED NOT NULL,
  assigned_to INT UNSIGNED NOT NULL,
  status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NOT NULL DEFAULT 'PENDING',
  org_id VARCHAR(20) NOT NULL,
  location_id INT UNSIGNED NULL COMMENT 'FK to location table',
  submission_key CHAR(36) NULL COMMENT 'UUID to prevent double submission',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_tickets_submission_key (submission_key),
  KEY idx_helpdesk_tickets_status (status),
  KEY idx_helpdesk_tickets_assigned_to (assigned_to),
  KEY idx_helpdesk_tickets_created_by (created_by),
  KEY idx_helpdesk_tickets_category (category_id),
  KEY idx_tickets_org_status (org_id, status),
  KEY idx_tickets_org_created (org_id, created_at),
  CONSTRAINT fk_helpdesk_tickets_category FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id),
  CONSTRAINT fk_helpdesk_tickets_created_by FOREIGN KEY (created_by) REFERENCES helpdesk_users (id),
  CONSTRAINT fk_helpdesk_tickets_assigned_to FOREIGN KEY (assigned_to) REFERENCES helpdesk_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 5. Ticket Activity Log Table
-- Audit log for status changes, remarks, attachments, and resolution times.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ticket_activity (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ticket_id INT UNSIGNED NOT NULL,
  action_by INT UNSIGNED NOT NULL,
  from_status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NULL,
  to_status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NOT NULL,
  remarks TEXT NULL,
  time_taken VARCHAR(120) NULL,
  attachment_path VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_activity_dedup (ticket_id, action_by, from_status, to_status, created_at),
  KEY idx_helpdesk_ticket_activity_ticket (ticket_id),
  KEY idx_helpdesk_ticket_activity_user (action_by),
  CONSTRAINT fk_helpdesk_ticket_activity_ticket FOREIGN KEY (ticket_id) REFERENCES helpdesk_tickets (id) ON DELETE CASCADE,
  CONSTRAINT fk_helpdesk_ticket_activity_user FOREIGN KEY (action_by) REFERENCES helpdesk_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 6. Ticket Internal Notes Table
-- Private notes added to tickets by CAs, Admins, or HODs.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ticket_notes (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ticket_id INT UNSIGNED NOT NULL,
  author_id INT UNSIGNED NOT NULL,
  note TEXT NOT NULL,
  is_internal TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_notes_dedup (ticket_id, author_id, created_at),
  KEY idx_ticket_notes_ticket (ticket_id),
  KEY idx_ticket_notes_author (author_id),
  CONSTRAINT fk_helpdesk_ticket_notes_ticket FOREIGN KEY (ticket_id) REFERENCES helpdesk_tickets (id) ON DELETE CASCADE,
  CONSTRAINT fk_helpdesk_ticket_notes_author FOREIGN KEY (author_id) REFERENCES helpdesk_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 7. CA Category/Block Assignments Table
-- Maps Concerned Authorities (CA) to specific categories and campus blocks.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ca_assignments (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_id INT UNSIGNED NOT NULL,
  ca_id INT UNSIGNED NOT NULL,
  block VARCHAR(120) NOT NULL DEFAULT '',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ca_category_block (category_id, ca_id, block),
  KEY idx_ca_assignments_ca (ca_id),
  KEY idx_ca_assignments_category (category_id),
  CONSTRAINT fk_helpdesk_ca_assign_cat FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id) ON DELETE CASCADE,
  CONSTRAINT fk_helpdesk_ca_assign_user FOREIGN KEY (ca_id) REFERENCES helpdesk_users (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 8. CA Location Mappings Table
-- Maps CAs directly to physical campus locations.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_ca_locations (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ca_id INT UNSIGNED NOT NULL,
  location_id INT UNSIGNED NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ca_location (ca_id, location_id),
  KEY idx_ca_locations_ca (ca_id),
  KEY idx_ca_locations_location (location_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------
-- 9. System Audit Events Table
-- Security audit trail for admin actions, login attempts, and impersonation.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS helpdesk_audit_events (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  event_type VARCHAR(60) NOT NULL,
  actor_id INT UNSIGNED NOT NULL,
  target_type VARCHAR(40) NULL,
  target_id INT UNSIGNED NULL,
  org_id VARCHAR(20) NOT NULL,
  details TEXT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_audit_event_type (event_type),
  KEY idx_audit_actor (actor_id),
  KEY idx_audit_org (org_id),
  KEY idx_audit_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
