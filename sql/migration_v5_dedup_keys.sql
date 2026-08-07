-- ============================================================
-- SNIST Helpdesk  –  Migration v5
-- Features: Deduplication keys to prevent double-submissions
-- ============================================================

-- 1. Add submission_key to helpdesk_tickets to prevent duplicate submissions
--    Client generates a UUID per form submit; DB rejects re-submits.
ALTER TABLE helpdesk_tickets
  ADD COLUMN submission_key CHAR(36) NULL DEFAULT NULL AFTER location_id;

CREATE UNIQUE INDEX uq_tickets_submission_key
  ON helpdesk_tickets (submission_key);

-- 2. Prevent duplicate status transitions on the same ticket
--    (same ticket, same actor, same from→to transition, within the same second)
CREATE UNIQUE INDEX uq_activity_dedup
  ON helpdesk_ticket_activity (ticket_id, action_by, from_status, to_status, created_at);

-- 3. Prevent duplicate notes (same author, same ticket, same second)
CREATE UNIQUE INDEX uq_notes_dedup
  ON helpdesk_ticket_notes (ticket_id, author_id, created_at);
