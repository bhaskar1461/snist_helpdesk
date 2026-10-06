import json
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from app import get_demo_db


class TestBugfixRegression(HelpdeskTestCase):
    """
    Comprehensive regression test suite verifying:
    - Issue 1: CA Direct Ticket Closure from Assignment (Assigned -> Closed/Resolved, In Progress, On Hold)
    - Issue 2: User / CA Edit & Safe Soft-Delete / Deactivation (Tested with Ravishankar and standard CAs)
    - Issue 3: Category Management for CAs (Add, Remove, Reassign, Cross-Dept Scoping, Protected Deletion)
    - Explicit API and Data Integrity Test Cases A1-A8, B1-B5, C1-C5, D1-D8, E1-E2, F1-F5.
    """

    def setUp(self):
        super().setUp()
        self.demo_db = get_demo_db()

        # Seed initial test ticket for CA 4 (Chandini CA: ca@gmail.com)
        self.test_ticket_id = 101
        GLOBAL_DB_STATE.tables["helpdesk_tickets"].append({
            "id": self.test_ticket_id,
            "title": "Network Issue in Lab 2",
            "description": "Switch offline",
            "category_id": 1,
            "created_by": 7,
            "created_by_email": "faculty@gmail.com",
            "assigned_to": 4,
            "assigned_to_email": "ca@gmail.com",
            "status": "PENDING",
            "department": "CSE",
            "org_id": "2000",
            "location_id": 1,
        })

    # =========================================================================
    # A. TICKET STATUS API TESTS
    # =========================================================================

    def test_A1_assigned_to_closed_direct(self):
        """A1: CA directly transitions Assigned (PENDING) ticket to Closed (RESOLVED)."""
        self.login_as("ca@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "closed", "remarks": "Resolved without delay"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "RESOLVED")

        # Database verification
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "RESOLVED")

        # Status history verification
        activity = self.demo_db.list_ticket_activity(self.test_ticket_id)
        self.assertTrue(any(a["from_status"] == "PENDING" and a["to_status"] == "RESOLVED" for a in activity))

    def test_A2_assigned_to_in_progress(self):
        """A2: CA transitions Assigned ticket to In Progress."""
        self.login_as("ca@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "in_progress", "remarks": "Started investigating"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "IN_PROGRESS")

    def test_A3_assigned_to_on_hold(self):
        """A3: CA transitions Assigned ticket directly to On Hold."""
        self.login_as("ca@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "on_hold", "remarks": "Awaiting parts"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "ON_HOLD")

    def test_A4_in_progress_to_closed(self):
        """A4: CA transitions ticket from In Progress to Closed."""
        self.login_as("ca@gmail.com")
        # First move to IN_PROGRESS
        self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "in_progress"}),
            content_type="application/json",
        )
        # Then move to CLOSED
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "closed", "remarks": "Fixed the switch"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "RESOLVED")

    def test_A5_unauthorized_user_cannot_close_ticket(self):
        """A5: Authenticate as user not authorized to close ticket (FACULTY) -> 403 rejected."""
        self.login_as("faculty@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "closed"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)
        # Database status remains unchanged
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "PENDING")

    def test_A6_ca_cannot_close_another_cas_unauthorized_ticket(self):
        """A6: CA B cannot close a ticket assigned to CA A -> rejected with 403."""
        # User 5 (Sravan CA) attempts to close ticket assigned to User 4 (Chandini CA)
        self.login_as("sravan.ca@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "closed"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "PENDING")

    def test_A7_invalid_status_rejected(self):
        """A7: Send invalid status -> rejected with 400 validation error."""
        self.login_as("ca@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "random_status"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "PENDING")

    def test_A8_missing_status_rejected(self):
        """A8: Send empty payload -> rejected with 400."""
        self.login_as("ca@gmail.com")
        res = self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertEqual(ticket["status"], "PENDING")

    # =========================================================================
    # B. USER/CA API TESTS (Working CA and Previously Failing CA Ravishankar)
    # =========================================================================

    def test_B1_get_user_affected_ca(self):
        """B1: Request affected CA Ravishankar (id=2823) -> correct metadata returned."""
        self.login_as("admin@gmail.com")
        res = self.client.get("/api/users/2823")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        user = data["user"]
        self.assertEqual(user["id"], 2823)
        self.assertEqual(user["role"], "CA")
        self.assertEqual(user["department"], "ECE")
        self.assertEqual(user["is_active"], 1)

    def test_B2_edit_affected_ca(self):
        """B2: Edit affected CA Ravishankar -> success, updated value persisted."""
        self.login_as("admin@gmail.com")
        res = self.client.put(
            "/api/users/2823",
            data=json.dumps({"name": "Dr. C. Ravishankar Reddy Updated"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        # Fetch user again to verify persistence
        res2 = self.client.get("/api/users/2823")
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.get_json()["user"]["name"], "Dr. C. Ravishankar Reddy Updated")

    def test_B3_edit_ca_without_changing_relationships(self):
        """B3: Update basic field only -> categories, department, role remain intact."""
        self.login_as("admin@gmail.com")
        initial_cats = self.demo_db.list_ca_categories(2823)

        res = self.client.put(
            "/api/users/2823",
            data=json.dumps({"name": "Dr. Ravishankar R."}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        user_after = self.demo_db.get_user(2823)
        self.assertEqual(user_after["role"], "CA")
        self.assertEqual(user_after["department"], "ECE")
        after_cats = self.demo_db.list_ca_categories(2823)
        self.assertEqual(len(initial_cats), len(after_cats))

    def test_B4_invalid_user_id_returns_404(self):
        """B4: Attempt to update nonexistent user ID -> 404."""
        self.login_as("admin@gmail.com")
        res = self.client.put(
            "/api/users/999999",
            data=json.dumps({"name": "Nonexistent"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

    def test_B5_unauthorized_user_edit_rejected(self):
        """B5: Faculty user attempts to edit CA -> rejected with 403."""
        self.login_as("faculty@gmail.com")
        res = self.client.put(
            "/api/users/2823",
            data=json.dumps({"name": "Hacked Name"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 403)
        user = self.demo_db.get_user(2823)
        self.assertNotEqual(user["name"], "Hacked Name")

    # =========================================================================
    # C. USER DELETE / DEACTIVATION API TESTS
    # =========================================================================

    def test_C1_delete_deactivate_affected_ca(self):
        """C1: Soft-deactivate affected CA Ravishankar who has category mappings."""
        self.login_as("admin@gmail.com")
        res = self.client.delete("/api/users/2823")
        self.assertEqual(res.status_code, 200)

        # User remains in DB but is_active = 0
        user = self.demo_db.get_user(2823)
        self.assertIsNotNone(user)
        self.assertEqual(user["is_active"], 0)

    def test_C2_ca_with_existing_tickets_preserves_history(self):
        """C2 & C3: CA with existing tickets is soft-deactivated and historical tickets remain intact."""
        self.login_as("admin@gmail.com")
        # User 4 (Chandini CA) has test_ticket_id
        res = self.client.delete("/api/users/4")
        self.assertEqual(res.status_code, 200)

        # Verify soft deletion
        user = self.demo_db.get_user(4)
        self.assertIsNotNone(user)
        self.assertEqual(user["is_active"], 0)

        # C3: Verify Historical Ticket Integrity
        ticket = self.demo_db.get_ticket(self.test_ticket_id)
        self.assertIsNotNone(ticket)
        self.assertEqual(ticket["assigned_to"], 4)
        self.assertEqual(ticket["status"], "PENDING")

    def test_C4_delete_nonexistent_user_returns_404(self):
        """C4: Delete invalid user ID -> 404."""
        self.login_as("admin@gmail.com")
        res = self.client.delete("/api/users/999999")
        self.assertEqual(res.status_code, 404)

    def test_C5_unauthorized_delete_rejected(self):
        """C5: Faculty attempts to delete CA -> 403, user unaffected."""
        self.login_as("faculty@gmail.com")
        res = self.client.delete("/api/users/2823")
        self.assertEqual(res.status_code, 403)
        user = self.demo_db.get_user(2823)
        self.assertEqual(user["is_active"], 1)

    # =========================================================================
    # D. CATEGORY ASSIGNMENT API TESTS
    # =========================================================================

    def test_D1_get_categories_for_affected_ca(self):
        """D1: Get categories for affected CA Ravishankar."""
        self.login_as("admin@gmail.com")
        res = self.client.get("/api/users/2823/categories")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("categories", data)
        cat_ids = [c["category_id"] for c in data["categories"]]
        self.assertIn(5, cat_ids)

    def test_D2_add_category_assignment(self):
        """D2: Add category to CA within same department."""
        self.login_as("admin@gmail.com")
        # Add another ECE category (id=6)
        GLOBAL_DB_STATE.tables["helpdesk_categories"].append({
            "id": 6,
            "category_name": "Antenna Lab",
            "department": "ECE",
            "assigned_ca_id": 2823,
            "is_active": 1,
            "org_id": "2000",
        })
        res = self.client.post(
            "/api/users/2823/categories",
            data=json.dumps({"category_id": 6, "block": "Block-IV"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        # Verify persisted assignment
        cats = self.demo_db.list_ca_categories(2823)
        cat_ids = [c["category_id"] for c in cats]
        self.assertIn(6, cat_ids)

    def test_D3_remove_category_assignment(self):
        """D3: Remove category assignment from CA."""
        self.login_as("admin@gmail.com")
        res = self.client.delete("/api/users/2823/categories/5")
        self.assertEqual(res.status_code, 200)

        cats = self.demo_db.list_ca_categories(2823)
        cat_ids = [c["category_id"] for c in cats]
        self.assertNotIn(5, cat_ids)

    def test_D4_reassign_category(self):
        """D4: Reassign CA category assignment."""
        self.login_as("admin@gmail.com")
        GLOBAL_DB_STATE.tables["helpdesk_categories"].append({
            "id": 7,
            "category_name": "VLSI Lab",
            "department": "ECE",
            "assigned_ca_id": 2823,
            "is_active": 1,
            "org_id": "2000",
        })
        res = self.client.put(
            "/api/users/2823/categories",
            data=json.dumps({"old_category_id": 5, "new_category_id": 7, "block": "All Blocks"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)

        cats = self.demo_db.list_ca_categories(2823)
        cat_ids = [c["category_id"] for c in cats]
        self.assertIn(7, cat_ids)
        self.assertNotIn(5, cat_ids)

    def test_D5_duplicate_category_assignment_prevention(self):
        """D5: Duplicate assignment is handled idempotently without duplicate rows."""
        self.login_as("admin@gmail.com")
        count_before = len([a for a in GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] if a["ca_id"] == 2823 and a["category_id"] == 5])
        res = self.client.post(
            "/api/users/2823/categories",
            data=json.dumps({"category_id": 5, "block": "All Blocks"}),
            content_type="application/json",
        )
        self.assertIn(res.status_code, (200, 400))
        count_after = len([a for a in GLOBAL_DB_STATE.tables["helpdesk_ca_assignments"] if a["ca_id"] == 2823 and a["category_id"] == 5])
        self.assertEqual(count_before, count_after)

    def test_D6_invalid_category_id(self):
        """D6: Assign nonexistent category -> rejected 404."""
        self.login_as("admin@gmail.com")
        res = self.client.post(
            "/api/users/2823/categories",
            data=json.dumps({"category_id": 99999}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

    def test_D7_invalid_ca_id(self):
        """D7: Assign category to nonexistent CA -> rejected 404."""
        self.login_as("admin@gmail.com")
        res = self.client.post(
            "/api/users/99999/categories",
            data=json.dumps({"category_id": 5}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 404)

    def test_D8_cross_department_category_assignment_rejected(self):
        """D8: Attempting to assign Category (CSE) to CA (ECE Ravishankar) -> rejected with 400."""
        self.login_as("admin@gmail.com")
        res = self.client.post(
            "/api/users/2823/categories",
            data=json.dumps({"category_id": 1, "block": "All Blocks"}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("mismatch", res.get_json()["error"].lower())

    # =========================================================================
    # E. CATEGORY DELETE API TESTS
    # =========================================================================

    def test_E1_remove_category_assignment(self):
        """E1: Remove category assignment from CA; category itself remains active."""
        self.login_as("admin@gmail.com")
        res = self.client.delete("/api/users/2823/categories/5")
        self.assertEqual(res.status_code, 200)

        cat = self.demo_db.get_category(5)
        self.assertIsNotNone(cat)
        self.assertEqual(cat["is_active"], 1)

    def test_E2_delete_category_referenced_by_tickets_blocked(self):
        """E2: Category referenced by existing tickets cannot be deleted -> returns 400 error."""
        self.login_as("admin@gmail.com")
        res = self.client.delete("/api/categories/1")
        self.assertEqual(res.status_code, 400)
        self.assertIn("referenced by existing tickets", res.get_json()["error"])
        cat = self.demo_db.get_category(1)
        self.assertIsNotNone(cat)

    # =========================================================================
    # F. DATABASE & DATA INTEGRITY TESTS
    # =========================================================================

    def test_F1_no_orphaned_user_category_relationships(self):
        """F1: Ensure no category assignments reference non-existent users."""
        with self.demo_db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT ca_id FROM helpdesk_ca_assignments")
            assignments = cur.fetchall()
        user_ids = {u["id"] for u in GLOBAL_DB_STATE.tables["helpdesk_users"]} | {u["teacher_id"] for u in GLOBAL_DB_STATE.tables["helpdesk_staff_roles"] if "teacher_id" in u} | {t["TEACHER_ID"] for t in GLOBAL_DB_STATE.tables["teacher_info"]}
        orphans = [a for a in assignments if a["ca_id"] not in user_ids]
        self.assertEqual(len(orphans), 0, "Found orphaned CA assignments!")

    def test_F2_no_orphaned_ticket_assignments(self):
        """F2: Ensure ticket assignments reference valid users."""
        with self.demo_db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT assigned_to FROM helpdesk_tickets WHERE assigned_to IS NOT NULL")
            tickets = cur.fetchall()
        user_ids = {u["id"] for u in GLOBAL_DB_STATE.tables["helpdesk_users"]}
        orphans = [t for t in tickets if t["assigned_to"] not in user_ids]
        self.assertEqual(len(orphans), 0, "Found orphaned ticket assignments!")

    def test_F3_no_duplicate_ca_category_relationships(self):
        """F3: Verify no duplicate (ca_id, category_id, block) assignments."""
        with self.demo_db.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT ca_id, category_id, block FROM helpdesk_ca_assignments")
            assignments = cur.fetchall()
        seen = set()
        duplicates = []
        for a in assignments:
            key = (a["ca_id"], a["category_id"], str(a.get("block", "")).lower())
            if key in seen:
                duplicates.append(key)
            seen.add(key)
        self.assertEqual(len(duplicates), 0, f"Found duplicate assignments: {duplicates}")

    def test_F4_existing_data_preservation(self):
        """F4: Operations on one CA do not corrupt unrelated records."""
        ca4_before = self.demo_db.get_user(4)
        cat1_before = self.demo_db.get_category(1)

        self.demo_db.update_user(2823, {"name": "Dr. R. S. Reddy"})

        ca4_after = self.demo_db.get_user(4)
        cat1_after = self.demo_db.get_category(1)
        self.assertEqual(ca4_before["name"], ca4_after["name"])
        self.assertEqual(cat1_before["category_name"], cat1_after["category_name"])

    def test_F5_status_history_integrity(self):
        """F5: Verify status history audit records are accurately captured."""
        self.login_as("ca@gmail.com")
        self.client.post(
            f"/api/tickets/{self.test_ticket_id}/status",
            data=json.dumps({"status": "closed", "remarks": "Status Audit Test"}),
            content_type="application/json",
        )
        raw_acts = [a for a in GLOBAL_DB_STATE.tables["helpdesk_ticket_activity"] if a["ticket_id"] == self.test_ticket_id]
        latest = raw_acts[-1]
        self.assertEqual(latest["from_status"], "PENDING")
        self.assertEqual(latest["to_status"], "RESOLVED")
        self.assertEqual(latest["action_by"], 4)
        self.assertEqual(latest["remarks"], "Status Audit Test")
