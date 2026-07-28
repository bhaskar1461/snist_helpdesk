-- ============================================================
-- SNIST Helpdesk  –  Migration v3
-- Features: CA Location Assignments, Ticket Notes
-- ============================================================

-- 1. CA Location Assignments
CREATE TABLE IF NOT EXISTS demo_ca_locations (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ca_id INT UNSIGNED NOT NULL,
  location_id INT UNSIGNED NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_ca_location (ca_id, location_id),
  KEY idx_ca_locations_ca (ca_id),
  KEY idx_ca_locations_location (location_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Ticket Internal Notes
CREATE TABLE IF NOT EXISTS demo_ticket_notes (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  ticket_id INT UNSIGNED NOT NULL,
  author_id INT UNSIGNED NOT NULL,
  note TEXT NOT NULL,
  is_internal TINYINT(1) NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ticket_notes_ticket (ticket_id),
  KEY idx_ticket_notes_author (author_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Performance indexes for common filter patterns
CREATE INDEX IF NOT EXISTS idx_tickets_org_status ON demo_tickets (org_id, status);
CREATE INDEX IF NOT EXISTS idx_tickets_org_created ON demo_tickets (org_id, created_at);
CREATE INDEX IF NOT EXISTS idx_categories_dept_active ON demo_categories (department, is_active);
