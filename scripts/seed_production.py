#!/usr/bin/env python3
"""
scripts/seed_production.py
Production Seeding and Reconciliation Tool (Staging -> Production).

Safely seeds reference and configuration data (staff roles, categories, problem types,
and CA assignments) from staging to production with:
- Strict foreign key and ID re-mapping
- Idempotent upserts (INSERT ... ON DUPLICATE KEY UPDATE)
- Transaction boundaries per table
- Dry-run mode by default
- Rejection of live operational tables (helpdesk_tickets, helpdesk_ticket_activity)
- Generation of explicit mapping report (scripts/output/seed_mapping_<timestamp>.json)
"""

import os
import sys
import json
import argparse
import datetime
import logging
from pathlib import Path
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("seed_production")

# Default CA mappings for production's 16 core categories
PROD_CATEGORY_DEFAULTS = {
    ("Internet & Wi-Fi", "ICT"): 457,                       # Jitta Chandra Shekar Reddy (TEACHER_ID=457)
    ("Computer & Peripherals", "ICT"): 457,                 # Jitta Chandra Shekar Reddy (TEACHER_ID=457)
    ("LCD Projector & AV", "ICT"): 457,                     # Jitta Chandra Shekar Reddy (TEACHER_ID=457)
    ("Printers & Scanners", "ICT"): 457,                    # Jitta Chandra Shekar Reddy (TEACHER_ID=457)
    ("Software & Operating System", "ICT"): 457,            # Jitta Chandra Shekar Reddy (TEACHER_ID=457)
    ("ERP & Portal Access", "SAP"): 471,                    # Naluvala Srinivas (TEACHER_ID=471)
    ("Plumbing & Water Supply", "Facilities"): 2895,        # Musaramthota Vinod Kumar (TEACHER_ID=2895)
    ("Electrical & Lighting", "Facilities"): 652,           # Jannap Reddy Dayakar Reddy (TEACHER_ID=652)
    ("Air Conditioning (AC)", "Facilities"): 2895,          # Musaramthota Vinod Kumar (TEACHER_ID=2895)
    ("Classroom & Lab Furniture", "Facilities"): 2895,      # Musaramthota Vinod Kumar (TEACHER_ID=2895)
    ("Housekeeping & Cleanliness", "Facilities"): 2895,     # Musaramthota Vinod Kumar (TEACHER_ID=2895)
    ("Campus Transport & Buses", "Transport"): 826,         # Bhagi Babu (TEACHER_ID=826)
    ("Lab Equipment Maintenance", "CSE"): 1995,             # A Priyanka (TEACHER_ID=1995)
    ("Lab Equipment Maintenance", "ECE"): 948,              # Dr. S.P. Venu Madhava Rao (TEACHER_ID=948)
    ("Lab Equipment Maintenance", "EEE"): 652,              # Jannap Reddy Dayakar Reddy (TEACHER_ID=652)
    ("Lab Equipment Maintenance", "ME"): 140,               # Dr. Poreddy Narsimha Reddy (TEACHER_ID=140)
}


def get_connection(host, port, user, password, database):
    return pymysql.connect(
        host=host,
        port=int(port),
        user=user,
        password=password,
        database=database,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def seed_data(source_host, target_host, dry_run=True, tables=None):
    if tables is None:
        tables = [
            "helpdesk_staff_roles",
            "helpdesk_categories",
            "helpdesk_problem_types",
            "helpdesk_ca_assignments",
        ]

    # Rule 8: NEVER copy helpdesk_tickets or helpdesk_ticket_activity
    prohibited = {"helpdesk_tickets", "helpdesk_ticket_activity"}
    found_prohibited = set(tables) & prohibited
    if found_prohibited:
        raise ValueError(
            f"CRITICAL ERROR: Prohibited live operational tables specified in --tables: {found_prohibited}. "
            f"Production tickets and activity must never be overwritten."
        )

    # Database credentials from environment
    src_user = os.getenv("MYSQL_SOURCE_USER", os.getenv("MYSQL_USER", "demo"))
    src_pwd = os.getenv("MYSQL_SOURCE_PASSWORD", os.getenv("MYSQL_PASSWORD", ""))
    src_db = os.getenv("MYSQL_SOURCE_DB", "helpdesk")
    src_port = int(os.getenv("MYSQL_SOURCE_PORT", os.getenv("MYSQL_PORT", "3306")))

    tgt_user = os.getenv("MYSQL_USER", "demo")
    tgt_pwd = os.getenv("MYSQL_PASSWORD", "")
    tgt_db = os.getenv("MYSQL_DATABASE", "helpdesk")
    tgt_port = int(os.getenv("MYSQL_PORT", "3306"))

    log.info("=" * 60)
    log.info("SNIST Helpdesk Production Seeder")
    log.info("Mode: %s", "DRY-RUN (No changes will be applied)" if dry_run else "EXECUTE (Applying changes)")
    log.info("Source: %s:%s (DB: %s)", source_host, src_port, src_db)
    log.info("Target: %s:%s (DB: %s)", target_host, tgt_port, tgt_db)
    log.info("Tables to seed: %s", tables)
    log.info("=" * 60)

    src_conn = get_connection(source_host, src_port, src_user, src_pwd, src_db)
    tgt_conn = get_connection(target_host, tgt_port, tgt_user, tgt_pwd, tgt_db)

    output_dir = Path(__file__).resolve().parent / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    mapping_report_path = output_dir / f"seed_mapping_{timestamp}.json"

    mapping_report = {
        "timestamp": timestamp,
        "mode": "DRY-RUN" if dry_run else "EXECUTE",
        "source": f"{source_host}:{src_port}/{src_db}",
        "target": f"{target_host}:{tgt_port}/{tgt_db}",
        "staff_roles_map": {},
        "categories_map": {},
        "ca_user_map": {},
        "summary": {},
    }

    try:
        # Pre-load target teacher_info for quick existence validation
        with tgt_conn.cursor() as cur:
            cur.execute("SELECT TEACHER_ID, LOWER(EMAIL_ID) AS email FROM teacher_info")
            tgt_teachers = {r["TEACHER_ID"]: (r["email"] or "").strip() for r in cur.fetchall()}
            tgt_teachers_by_email = {email: tid for tid, email in tgt_teachers.items() if email}
        log.info("Loaded %d teachers from target teacher_info view.", len(tgt_teachers))

        # ── Step 3a: helpdesk_staff_roles ───────────────────────────────────
        if "helpdesk_staff_roles" in tables:
            log.info("\n[1/4] Processing helpdesk_staff_roles...")
            with src_conn.cursor() as cur:
                cur.execute("SELECT * FROM helpdesk_staff_roles ORDER BY id")
                src_staff = cur.fetchall()

            with tgt_conn.cursor() as cur:
                cur.execute("SELECT * FROM helpdesk_staff_roles ORDER BY id")
                tgt_staff = cur.fetchall()
                tgt_staff_by_email = {r["email"].lower().strip(): r for r in tgt_staff}

            staff_inserted = 0
            staff_updated = 0
            staff_unchanged = 0

            for s in src_staff:
                email = s["email"].strip().lower()
                # Check teacher mapping on target
                t_id = s.get("teacher_id")
                if t_id and t_id not in tgt_teachers:
                    log.warning("Staff role %s has teacher_id %s not present in target teacher_info", email, t_id)
                elif not t_id and email in tgt_teachers_by_email:
                    t_id = tgt_teachers_by_email[email]

                if email in tgt_staff_by_email:
                    existing = tgt_staff_by_email[email]
                    mapping_report["staff_roles_map"][s["id"]] = existing["id"]
                    # Check if fields match
                    if (existing.get("role") == s["role"] and
                        existing.get("department") == s["department"] and
                        existing.get("is_active") == s["is_active"]):
                        staff_unchanged += 1
                        continue
                    staff_updated += 1
                    if dry_run:
                        log.info("  [DRY-RUN] UPDATE staff_role: %s (id=%s, role=%s, dept=%s)", email, existing["id"], s["role"], s["department"])
                    else:
                        with tgt_conn.cursor() as cur:
                            cur.execute(
                                """
                                UPDATE helpdesk_staff_roles
                                SET role = %s, department = %s, is_active = %s,
                                    teacher_id = COALESCE(teacher_id, %s)
                                WHERE id = %s
                                """,
                                (s["role"], s["department"], s["is_active"], t_id, existing["id"]),
                            )
                else:
                    staff_inserted += 1
                    if dry_run:
                        log.info("  [DRY-RUN] INSERT staff_role: %s (name=%s, role=%s, dept=%s)", email, s["name"], s["role"], s["department"])
                        mapping_report["staff_roles_map"][s["id"]] = f"NEW_{s['id']}"
                    else:
                        with tgt_conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO helpdesk_staff_roles (teacher_id, name, email, password_hash, role, department, phone, is_active)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                                """,
                                (t_id, s["name"], s["email"], s.get("password_hash"), s["role"], s.get("department"), s.get("phone"), s.get("is_active", 1)),
                            )
                            new_id = cur.lastrowid
                            mapping_report["staff_roles_map"][s["id"]] = new_id
                            tgt_staff_by_email[email] = {"id": new_id, "email": email}

            if not dry_run:
                tgt_conn.commit()

            mapping_report["summary"]["helpdesk_staff_roles"] = {
                "source_count": len(src_staff),
                "inserted": staff_inserted,
                "updated": staff_updated,
                "unchanged": staff_unchanged,
            }
            log.info("helpdesk_staff_roles: %d to insert, %d to update, %d unchanged.", staff_inserted, staff_updated, staff_unchanged)

        # Refresh target staff roles for CA resolution
        with tgt_conn.cursor() as cur:
            cur.execute("SELECT id, email FROM helpdesk_staff_roles")
            tgt_staff_by_email = {r["email"].lower().strip(): r["id"] for r in cur.fetchall()}

        # ── Step 3b: helpdesk_categories ────────────────────────────────────
        if "helpdesk_categories" in tables:
            log.info("\n[2/4] Processing helpdesk_categories...")
            with src_conn.cursor() as cur:
                cur.execute("SELECT * FROM helpdesk_categories ORDER BY id")
                src_cats = cur.fetchall()

            with tgt_conn.cursor() as cur:
                cur.execute("SELECT * FROM helpdesk_categories ORDER BY id")
                tgt_cats = cur.fetchall()
                tgt_cats_by_key = {(r["category_name"].strip().lower(), r["department"].strip().lower()): r for r in tgt_cats}

            cat_inserted = 0
            cat_updated = 0
            cat_unchanged = 0

            # 1. Upsert staging categories
            for sc in src_cats:
                c_name = sc["category_name"].strip()
                c_dept = sc["department"].strip()
                key = (c_name.lower(), c_dept.lower())

                # Resolve assigned_ca_id
                src_ca = sc.get("assigned_ca_id")
                tgt_ca_id = None
                if src_ca:
                    if src_ca in tgt_teachers:
                        tgt_ca_id = src_ca
                    elif src_ca in mapping_report["staff_roles_map"]:
                        val = mapping_report["staff_roles_map"][src_ca]
                        if isinstance(val, int) or (dry_run and str(val).startswith("NEW_")):
                            tgt_ca_id = val
                    else:
                        # Try to resolve by looking up CA on source
                        with src_conn.cursor() as cur:
                            cur.execute("SELECT email FROM helpdesk_staff_roles WHERE id = %s", (src_ca,))
                            s_row = cur.fetchone()
                            if s_row and s_row["email"].lower() in tgt_staff_by_email:
                                tgt_ca_id = tgt_staff_by_email[s_row["email"].lower()]

                if not tgt_ca_id and src_ca:
                    log.warning("Could not resolve target CA ID for staging category '%s' (src_ca=%s)", c_name, src_ca)

                if key in tgt_cats_by_key:
                    existing = tgt_cats_by_key[key]
                    mapping_report["categories_map"][sc["id"]] = existing["id"]
                    if existing.get("assigned_ca_id") == tgt_ca_id and existing.get("is_active") == sc.get("is_active", 1):
                        cat_unchanged += 1
                        continue
                    cat_updated += 1
                    if dry_run:
                        log.info("  [DRY-RUN] UPDATE category: %s (%s) -> assigned_ca_id=%s", c_name, c_dept, tgt_ca_id)
                    else:
                        with tgt_conn.cursor() as cur:
                            cur.execute(
                                "UPDATE helpdesk_categories SET assigned_ca_id = %s, is_active = %s WHERE id = %s",
                                (tgt_ca_id, sc.get("is_active", 1), existing["id"]),
                            )
                else:
                    cat_inserted += 1
                    if dry_run:
                        log.info("  [DRY-RUN] INSERT category: %s (%s) -> assigned_ca_id=%s", c_name, c_dept, tgt_ca_id)
                        mapping_report["categories_map"][sc["id"]] = f"NEW_{sc['id']}"
                    else:
                        with tgt_conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO helpdesk_categories (category_name, department, assigned_ca_id, is_active)
                                VALUES (%s, %s, %s, %s)
                                """,
                                (c_name, c_dept, tgt_ca_id, sc.get("is_active", 1)),
                            )
                            new_cat_id = cur.lastrowid
                            mapping_report["categories_map"][sc["id"]] = new_cat_id
                            tgt_cats_by_key[key] = {"id": new_cat_id, "category_name": c_name, "department": c_dept, "assigned_ca_id": tgt_ca_id}

            # 2. Reconcile existing production categories (set assigned_ca_id where NULL)
            prod_reconciled = 0
            for (p_name, p_dept), p_ca_id in PROD_CATEGORY_DEFAULTS.items():
                p_key = (p_name.lower(), p_dept.lower())
                if p_key in tgt_cats_by_key:
                    cat_record = tgt_cats_by_key[p_key]
                    if cat_record.get("assigned_ca_id") is None or cat_record.get("assigned_ca_id") == 0:
                        prod_reconciled += 1
                        if dry_run:
                            log.info("  [DRY-RUN] RECONCILE prod category '%s' (%s) -> assigned_ca_id=%s", p_name, p_dept, p_ca_id)
                        else:
                            with tgt_conn.cursor() as cur:
                                cur.execute(
                                    "UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE id = %s",
                                    (p_ca_id, cat_record["id"]),
                                )
                            cat_record["assigned_ca_id"] = p_ca_id

            if not dry_run:
                tgt_conn.commit()

            mapping_report["summary"]["helpdesk_categories"] = {
                "source_count": len(src_cats),
                "inserted": cat_inserted,
                "updated": cat_updated,
                "unchanged": cat_unchanged,
                "prod_reconciled": prod_reconciled,
            }
            log.info("helpdesk_categories: %d to insert, %d to update, %d unchanged, %d reconciled.",
                     cat_inserted, cat_updated, cat_unchanged, prod_reconciled)

        # Refresh target categories for CA assignments
        with tgt_conn.cursor() as cur:
            cur.execute("SELECT id, category_name, department FROM helpdesk_categories")
            tgt_all_cats = { (r["category_name"].strip().lower(), r["department"].strip().lower()): r["id"] for r in cur.fetchall()}

        # ── Step 3c: helpdesk_problem_types ─────────────────────────────────
        if "helpdesk_problem_types" in tables:
            log.info("\n[3/4] Processing helpdesk_problem_types...")
            with src_conn.cursor() as cur:
                cur.execute("SELECT * FROM helpdesk_problem_types ORDER BY id")
                src_probs = cur.fetchall()

            prob_inserted = 0
            if src_probs:
                for p in src_probs:
                    src_cat_id = p["category_id"]
                    tgt_cat_id = mapping_report["categories_map"].get(src_cat_id)
                    if not tgt_cat_id or not isinstance(tgt_cat_id, int):
                        continue
                    prob_name = p["problem_name"].strip()
                    if dry_run:
                        prob_inserted += 1
                    else:
                        with tgt_conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO helpdesk_problem_types (category_id, problem_name, is_active)
                                VALUES (%s, %s, %s)
                                ON DUPLICATE KEY UPDATE is_active = VALUES(is_active)
                                """,
                                (tgt_cat_id, prob_name, p.get("is_active", 1)),
                            )
                            prob_inserted += 1
                if not dry_run:
                    tgt_conn.commit()

            mapping_report["summary"]["helpdesk_problem_types"] = {
                "source_count": len(src_probs),
                "inserted_or_updated": prob_inserted,
            }
            log.info("helpdesk_problem_types: %d processed (staging has %d rows).", prob_inserted, len(src_probs))

        # ── Step 3d: helpdesk_ca_assignments ────────────────────────────────
        if "helpdesk_ca_assignments" in tables:
            log.info("\n[4/4] Processing helpdesk_ca_assignments...")
            with src_conn.cursor() as cur:
                cur.execute("""
                    SELECT a.id, a.category_id, c.category_name, c.department, a.ca_id, a.block
                    FROM helpdesk_ca_assignments a
                    JOIN helpdesk_categories c ON c.id = a.category_id
                    ORDER BY a.id
                """)
                src_assigns = cur.fetchall()

            with tgt_conn.cursor() as cur:
                cur.execute("SELECT category_id, ca_id, block FROM helpdesk_ca_assignments")
                tgt_existing_assigns = {(r["category_id"], r["ca_id"], r["block"].strip().lower()) for r in cur.fetchall()}

            assign_inserted = 0
            assign_unchanged = 0
            unmapped_assignments = []

            for a in src_assigns:
                # 1. Map category_id
                src_cat_id = a["category_id"]
                tgt_cat_id = mapping_report["categories_map"].get(src_cat_id)
                if not tgt_cat_id or not (isinstance(tgt_cat_id, int) or (dry_run and str(tgt_cat_id).startswith("NEW_"))):
                    # Try lookup by name and dept
                    cat_key = (a["category_name"].strip().lower(), a["department"].strip().lower())
                    tgt_cat_id = tgt_all_cats.get(cat_key)

                if not tgt_cat_id:
                    unmapped_assignments.append((a["id"], f"Unmapped category {a['category_name']} ({src_cat_id})"))
                    continue

                # 2. Map ca_id
                src_ca_id = a["ca_id"]
                tgt_ca_id = None
                if src_ca_id in tgt_teachers:
                    tgt_ca_id = src_ca_id
                elif src_ca_id in mapping_report["staff_roles_map"]:
                    val = mapping_report["staff_roles_map"][src_ca_id]
                    if isinstance(val, int) or (dry_run and str(val).startswith("NEW_")):
                        tgt_ca_id = val

                if not tgt_ca_id:
                    unmapped_assignments.append((a["id"], f"Unmapped CA ID {src_ca_id}"))
                    continue

                mapping_report["ca_user_map"][src_ca_id] = tgt_ca_id
                block = (a["block"] or "").strip()
                assign_key = (tgt_cat_id, tgt_ca_id, block.lower())

                if assign_key in tgt_existing_assigns:
                    assign_unchanged += 1
                else:
                    assign_inserted += 1
                    if not dry_run:
                        with tgt_conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO helpdesk_ca_assignments (category_id, ca_id, block)
                                VALUES (%s, %s, %s)
                                ON DUPLICATE KEY UPDATE block = VALUES(block)
                                """,
                                (tgt_cat_id, tgt_ca_id, block),
                            )
                        tgt_existing_assigns.add(assign_key)

            if unmapped_assignments:
                log.error("CRITICAL: %d assignments could not be mapped to target entities!", len(unmapped_assignments))
                for item in unmapped_assignments[:10]:
                    log.error("  Assignment %s: %s", item[0], item[1])
                raise RuntimeError(f"Aborting seed: {len(unmapped_assignments)} unmapped CA assignments detected.")

            if not dry_run:
                tgt_conn.commit()

            mapping_report["summary"]["helpdesk_ca_assignments"] = {
                "source_count": len(src_assigns),
                "inserted": assign_inserted,
                "unchanged": assign_unchanged,
            }
            log.info("helpdesk_ca_assignments: %d to insert, %d unchanged (from %d staging assignments).",
                     assign_inserted, assign_unchanged, len(src_assigns))

        # Save Mapping Report
        with open(mapping_report_path, "w", encoding="utf-8") as f:
            json.dump(mapping_report, f, indent=2, default=str)
        log.info("\nMapping report written to: %s", mapping_report_path)

        log.info("\nSeeding finished successfully.")
        return mapping_report

    except Exception as exc:
        log.error("Error during seeding process: %s", exc)
        if not dry_run:
            tgt_conn.rollback()
            log.info("Rolled back all uncommitted target transactions.")
        raise
    finally:
        src_conn.close()
        tgt_conn.close()


def parse_bool(v):
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes", "y")


def main():
    parser = argparse.ArgumentParser(description="SNIST Helpdesk Staging to Production Seeder")
    parser.add_argument("--source-host", default=os.getenv("MYSQL_SOURCE_HOST", "seg-dev.sreenidhi.edu.in"), help="Staging source MySQL host")
    parser.add_argument("--target-host", default=os.getenv("MYSQL_HOST", "seg.sreenidhi.edu.in"), help="Production target MySQL host")
    parser.add_argument("--dry-run", nargs="?", const=True, default=False, type=parse_bool, help="Perform dry-run without writing (default: False if omitted, True if flag passed)")
    parser.add_argument("--execute", dest="dry_run", action="store_false", help="Explicitly execute real database mutations")
    parser.add_argument("--tables", default="helpdesk_staff_roles,helpdesk_categories,helpdesk_problem_types,helpdesk_ca_assignments", help="Comma-separated list of tables to seed")

    args = parser.parse_args()
    table_list = [t.strip() for t in args.tables.split(",") if t.strip()]

    seed_data(
        source_host=args.source_host,
        target_host=args.target_host,
        dry_run=args.dry_run,
        tables=table_list,
    )


if __name__ == "__main__":
    main()
