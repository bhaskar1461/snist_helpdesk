-- =============================================================================
-- Migration: 0999_test_migration.sql
-- Description: Isolated test migration for Phase 7 rollback, locking, and verification.
-- Impact: Creates temporary probe table _test_helpdesk_migration_probe.
-- Non-transactional DDL Note: Implicit commit on execution.
-- Failure mode: If statement fails, table is not created and migration is not tracked.
-- =============================================================================

CREATE TABLE IF NOT EXISTS _test_helpdesk_migration_probe (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  probe_name VARCHAR(100) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- DOWN
DROP TABLE IF EXISTS _test_helpdesk_migration_probe;
