# SNIST Helpdesk Database Migration Framework

## 1. Overview & Core Rules
This directory contains all version-controlled database schema migrations for the SNIST Helpdesk application.
The migration system is driven by `scripts/migrate.py` without third-party ORM dependencies.

### Invariant Rules
1. **Never edit an already-applied migration file**: The migration runner calculates and checks SHA-256 checksums on every run. Any alteration to a historical file triggers a `⚠ DRIFTED` warning and aborts CI/CD pipelines.
2. **Sequential Numbering**: Migrations must be named with a 4-digit zero-padded prefix followed by a snake_case descriptor:
   `NNNN_description.sql` (e.g., `0007_add_sla_priority.sql`).
3. **Advisory Lock Guarantee**: The runner executes all migrations under MySQL advisory lock `GET_LOCK('helpdesk_migration', 0)`. If another deploy process or worker holds the lock, the runner exits cleanly without executing partial DDL.
4. **Non-Transactional MySQL DDL**: In MySQL 8.0, DDL statements (`CREATE`, `ALTER`, `DROP`) trigger an implicit commit. Transactions cannot roll back DDL. Therefore:
   - Each migration file must be idempotent where possible (`CREATE TABLE IF NOT EXISTS`, `CREATE OR REPLACE VIEW`).
   - Every file must document locking behavior and impact.
5. **Rollback (`-- DOWN`) Sections**: Migrations may include a `-- DOWN` marker separating forward statements from rollback statements.

---

## 2. CLI Usage

### View Migration Status
```bash
python scripts/migrate.py status --env=prod
```

### Apply Pending Migrations
```bash
# Preview statements without executing
python scripts/migrate.py up --dry-run --env=prod

# Apply all pending migrations
python scripts/migrate.py up --env=prod
```

### Rollback a Migration
```bash
python scripts/migrate.py down --target=0007 --env=prod
```

### Bootstrap Existing Environment
```bash
# Mark pre-existing tables as applied without re-running DDL
python scripts/migrate.py bootstrap --assume-applied 0001..0006 --env=prod
```

---

## 3. Migration File Structure Example

```sql
-- Migration: 0007_add_sla_priority
-- Impact: Adds priority ENUM column to helpdesk_tickets table.
-- Failure mode: If column already exists, ALTER fails. Manual intervention required.

ALTER TABLE helpdesk_tickets 
  ADD COLUMN priority ENUM('LOW', 'MEDIUM', 'HIGH', 'URGENT') NOT NULL DEFAULT 'MEDIUM';

-- DOWN
ALTER TABLE helpdesk_tickets DROP COLUMN priority;
```
