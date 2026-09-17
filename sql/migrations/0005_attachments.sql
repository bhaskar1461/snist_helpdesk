-- =============================================================================
-- Migration: 0005_attachments.sql
-- Description: Structured attachment metadata tracking table for IDOR prevention.
-- Non-transactional DDL Note: Implicit commit on execution.
-- =============================================================================

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

-- DOWN
-- DROP TABLE IF EXISTS helpdesk_attachments;
