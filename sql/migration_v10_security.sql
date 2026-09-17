-- ============================================================
-- SNIST Helpdesk – Migration v10 (Security & Rate Limiting)
-- Phase 6: Distributed Rate Limiting & Attachment Access Control
-- Target: MySQL 8.0+
-- ============================================================

-- 1. Table for distributed, multi-worker login attempt tracking
CREATE TABLE IF NOT EXISTS helpdesk_login_attempts (
  id BIGINT NOT NULL AUTO_INCREMENT,
  identifier VARCHAR(120) NOT NULL COMMENT 'Target username / email or username+IP',
  ip_address VARCHAR(45) NOT NULL COMMENT 'Client IP address (IPv4 or IPv6)',
  attempted_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  outcome ENUM('SUCCESS', 'FAILURE') NOT NULL DEFAULT 'FAILURE',
  PRIMARY KEY (id),
  INDEX idx_attempt_lookup (identifier, attempted_at),
  INDEX idx_ip_lookup (ip_address, attempted_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Table for structured attachment metadata tracking
CREATE TABLE IF NOT EXISTS helpdesk_attachments (
  id BIGINT NOT NULL AUTO_INCREMENT,
  ticket_id INT NOT NULL,
  stored_filename VARCHAR(255) NOT NULL,
  original_filename VARCHAR(255) NOT NULL,
  uploaded_by INT NULL,
  file_size INT UNSIGNED NOT NULL DEFAULT 0,
  mime_type VARCHAR(100) NULL,
  uploaded_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  INDEX idx_attachment_ticket (ticket_id),
  INDEX idx_attachment_filename (stored_filename)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
