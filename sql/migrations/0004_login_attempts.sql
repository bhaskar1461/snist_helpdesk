-- =============================================================================
-- Migration: 0004_login_attempts.sql
-- Description: Distributed rate limiting tracking table for multi-worker protection.
-- Non-transactional DDL Note: Implicit commit on execution.
-- =============================================================================

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

-- DOWN
-- DROP TABLE IF EXISTS helpdesk_login_attempts;
