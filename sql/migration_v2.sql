-- ============================================================
-- SNIST Helpdesk  –  Migration v2
-- Features: Problem Types, Audit Events, Location CRUD,
--           Department Archive, Ticket problem_type support
-- ============================================================

-- 1. Problem Types (Feature 8, 10)
CREATE TABLE IF NOT EXISTS demo_problem_types (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_id INT UNSIGNED NOT NULL,
  problem_name VARCHAR(180) NOT NULL,
  is_active TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_problem_cat_name (category_id, problem_name),
  KEY idx_problem_category (category_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Audit Events (Feature 3, 4, 5, 11)
CREATE TABLE IF NOT EXISTS demo_audit_events (
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
