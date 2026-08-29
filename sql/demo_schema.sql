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
  CONSTRAINT fk_helpdesk_categories_ca FOREIGN KEY (assigned_ca_id) REFERENCES helpdesk_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS helpdesk_tickets (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  title VARCHAR(180) NOT NULL,
  description TEXT NOT NULL,
  category_id INT UNSIGNED NOT NULL,
  created_by INT UNSIGNED NOT NULL,
  assigned_to INT UNSIGNED NOT NULL,
  status ENUM('PENDING', 'IN_PROGRESS', 'ON_HOLD', 'RESOLVED', 'REOPENED') NOT NULL DEFAULT 'PENDING',
  org_id VARCHAR(20) NOT NULL,
  location_id INT UNSIGNED NULL COMMENT 'FK to location table (block/room)',
  submission_key CHAR(36) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_helpdesk_tickets_submission_key (submission_key),
  KEY idx_helpdesk_tickets_status (status),
  KEY idx_helpdesk_tickets_assigned_to (assigned_to),
  KEY idx_helpdesk_tickets_created_by (created_by),
  KEY idx_helpdesk_tickets_category (category_id),
  CONSTRAINT fk_helpdesk_tickets_category FOREIGN KEY (category_id) REFERENCES helpdesk_categories (id),
  CONSTRAINT fk_helpdesk_tickets_created_by FOREIGN KEY (created_by) REFERENCES helpdesk_users (id),
  CONSTRAINT fk_helpdesk_tickets_assigned_to FOREIGN KEY (assigned_to) REFERENCES helpdesk_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
  KEY idx_helpdesk_ticket_activity_ticket (ticket_id),
  KEY idx_helpdesk_ticket_activity_user (action_by),
  CONSTRAINT fk_helpdesk_ticket_activity_ticket FOREIGN KEY (ticket_id) REFERENCES helpdesk_tickets (id) ON DELETE CASCADE,
  CONSTRAINT fk_helpdesk_ticket_activity_user FOREIGN KEY (action_by) REFERENCES helpdesk_users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS branch_detail (
  BRANCH_ID INT UNSIGNED NOT NULL AUTO_INCREMENT,
  BRANCH_CODE VARCHAR(80) NOT NULL,
  BRANCH_NAME VARCHAR(180) NOT NULL,
  ORG_ID VARCHAR(32) NOT NULL DEFAULT '2000',
  HOD_ID INT UNSIGNED NULL,
  is_archived TINYINT(1) NOT NULL DEFAULT 0,
  PRIMARY KEY (BRANCH_ID),
  UNIQUE KEY uq_branch_code_org (BRANCH_CODE, ORG_ID)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS location (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  block VARCHAR(120) NOT NULL,
  floor VARCHAR(40) NOT NULL DEFAULT 'Ground Floor',
  room_no VARCHAR(80) NOT NULL,
  name VARCHAR(180) NOT NULL DEFAULT '',
  ORG_ID VARCHAR(32) NOT NULL DEFAULT '2000',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_location_org (ORG_ID),
  KEY idx_location_block (block)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

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
