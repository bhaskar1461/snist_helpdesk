import unittest
from tests.test_base import HelpdeskTestCase, GLOBAL_DB_STATE
from db_services import LiveDbService, DemoDbService, DbConfig

class TestLiveDbService(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        self.config = DbConfig("host", 3306, "user", "pass", "db")
        self.service = LiveDbService(self.config)

    def test_fetch_departments(self):
        # Fetch all departments
        depts = self.service.fetch_departments(include_archived=True)
        self.assertEqual(len(depts), 6)
        self.assertEqual(depts[0]["department_code"], "CSE")
        self.assertEqual(depts[0]["org_id"], "2000")
        
        # Test archive status filter
        # If we archive a department
        GLOBAL_DB_STATE.tables["branch_detail"][0]["is_archived"] = 1
        active_depts = self.service.fetch_departments(include_archived=False)
        self.assertEqual(len(active_depts), 5)
        self.assertNotIn("Computer Science", [d.get("department_name") for d in active_depts if d.get("is_archived") == 1])

    def test_locations(self):
        # Fetch locations
        locs = self.service.fetch_locations()
        # Verify locations return blocks, floors, rooms
        self.assertTrue(len(locs) > 0)
        self.assertTrue(len(GLOBAL_DB_STATE.tables["location"]) > 0)

        # Get specific location
        loc = self.service.get_location(1)
        self.assertIsNotNone(loc)
        self.assertEqual(loc["id"], 1)
        self.assertEqual(loc["room_no"], "101")

        # Update location
        self.service.update_location(1, "Block A Updated", "1st Floor", "101", "New Lab Name")
        loc_updated = self.service.get_location(1)
        self.assertEqual(loc_updated["name"], "New Lab Name")

        # Delete location
        self.service.delete_location(1)
        self.assertNotIn(1, [r["id"] for r in GLOBAL_DB_STATE.tables["location"]])

    def test_fetch_reference_users(self):
        users = self.service.fetch_reference_users(search="Seeded")
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["TEACHER_NAME"], "Seeded Teacher")

    def test_lookup_teacher_by_email(self):
        teacher = self.service.lookup_teacher_by_email("seeded@sreenidhi.edu.in")
        self.assertIsNotNone(teacher)
        self.assertEqual(teacher["SAP_ID"], "10001")

        none_teacher = self.service.lookup_teacher_by_email("nonexistent@gmail.com")
        self.assertIsNone(none_teacher)

    def test_resolve_org_id(self):
        org = self.service.resolve_org_id(email="snuteacher@snu.edu.in")
        self.assertEqual(org, "3000")

        org2 = self.service.resolve_org_id(email="seeded@sreenidhi.edu.in")
        self.assertEqual(org2, "2000")


class TestDemoDbService(HelpdeskTestCase):
    def setUp(self):
        super().setUp()
        self.config = DbConfig("host", 3306, "user", "pass", "db")
        self.service = DemoDbService(self.config)

    def test_get_user_phone(self):
        phone = self.service.get_user_phone("seeded@sreenidhi.edu.in")
        self.assertEqual(phone, "9876543210")

        fallback = self.service.get_user_phone("unknown@gmail.com")
        # Should return fallback test phone from env or default None/test num
        self.assertIsNotNone(fallback)

    def test_authenticate_user(self):
        # Correct password
        user = self.service.authenticate_user("admin@gmail.com", "123")
        self.assertIsNotNone(user)
        self.assertEqual(user["role"], "SUPER_ADMIN")

        # Incorrect password
        invalid_user = self.service.authenticate_user("admin@gmail.com", "wrong")
        self.assertIsNone(invalid_user)

        # Non-existent user
        missing_user = self.service.authenticate_user("missing@gmail.com", "123")
        self.assertIsNone(missing_user)

    def test_change_password(self):
        # Correct old password
        success = self.service.change_password(3, "123", "newpassword")
        self.assertTrue(success)
        
        # Verify password updated
        auth_ok = self.service.authenticate_user("hod@gmail.com", "newpassword")
        self.assertIsNotNone(auth_ok)

        # Incorrect old password
        fail = self.service.change_password(3, "wrong-old", "newpass")
        self.assertFalse(fail)

    def test_user_crud(self):
        # Create user
        payload = {
            "name": "New Person",
            "email": "newperson@gmail.com",
            "password": "pwd",
            "role": "FACULTY",
            "department": "ECE",
            "org_id": "2000"
        }
        new_id = self.service.create_user(payload)
        self.assertIsNotNone(new_id)

        # Get user
        user = self.service.get_user(new_id)
        self.assertEqual(user["name"], "New Person")
        self.assertEqual(user["role"], "FACULTY")

        # Get by email
        user_email = self.service.get_user_by_email("newperson@gmail.com")
        self.assertEqual(user_email["id"], new_id)

        # List users
        users_list = self.service.list_users(role="FACULTY", department="ECE")
        self.assertTrue(len(users_list) >= 1)

        # Update user
        self.service.update_user(new_id, {"name": "New Person Updated", "role": "CA"})
        user_updated = self.service.get_user(new_id)
        self.assertEqual(user_updated["name"], "New Person Updated")
        self.assertEqual(user_updated["role"], "CA")

        # Delete user
        self.service.delete_user(new_id)
        self.assertIsNone(self.service.get_user(new_id))

    def test_category_crud(self):
        # Create category
        payload = {
            "category_name": "Facilities Support",
            "department": "Facilities",
            "assigned_ca_id": 5,
            "is_active": 1
        }
        self.assertFalse(self.service.category_exists("Facilities Support", "Facilities"))
        cat_id = self.service.create_category(payload)
        self.assertIsNotNone(cat_id)
        self.assertTrue(self.service.category_exists("Facilities Support", "Facilities"))

        # Get category
        cat = self.service.get_category(cat_id)
        self.assertEqual(cat["category_name"], "Facilities Support")
        self.assertEqual(cat["assigned_ca_id"], 5)

        # List categories
        cats = self.service.list_categories(department="Facilities")
        self.assertEqual(len(cats), 2)  # Plumbing + Facilities Support

        # Toggle status
        self.service.toggle_category_status(cat_id, 0)
        cat_inactive = self.service.get_category(cat_id)
        self.assertEqual(cat_inactive["is_active"], 0)

        # Update category
        self.service.update_category(cat_id, {"category_name": "Facilities Help", "department": "Facilities", "assigned_ca_id": 6})
        cat_updated = self.service.get_category(cat_id)
        self.assertEqual(cat_updated["category_name"], "Facilities Help")
        self.assertEqual(cat_updated["assigned_ca_id"], 6)

        # Delete category
        self.service.delete_category(cat_id)
        self.assertIsNone(self.service.get_category(cat_id))

    def test_ticket_lifecycle(self):
        # Create ticket
        ticket_id = self.service.create_ticket(
            title="Projector issue",
            description="Lenses are dirty",
            category_id=2,
            created_by=7,
            org_id="2000",
            location_id=2
        )
        self.assertIsNotNone(ticket_id)

        # Get ticket
        ticket = self.service.get_ticket(ticket_id)
        self.assertEqual(ticket["title"], "Projector issue")
        self.assertEqual(ticket["status"], "PENDING")
        self.assertEqual(ticket["assigned_to"], 4) # Assigned to CA of CSE category

        # List tickets
        viewer = {"id": 7, "role": "FACULTY", "org_id": "2000", "department": "CSE"}
        tickets = self.service.list_tickets(viewer)
        self.assertEqual(len(tickets), 1)

        # Update status
        actor = {"id": 4, "name": "Chandini CA", "role": "CA"}
        success = self.service.update_ticket_status(ticket_id, actor, "IN_PROGRESS", remarks="Working on it")
        self.assertTrue(success)

        # Check status updated
        ticket_progress = self.service.get_ticket(ticket_id)
        self.assertEqual(ticket_progress["status"], "IN_PROGRESS")

        # List activity
        activities = self.service.list_ticket_activity(ticket_id)
        self.assertTrue(len(activities) >= 1)
        self.assertEqual(activities[-1]["to_status"], "IN_PROGRESS")
        self.assertEqual(activities[-1]["remarks"], "Working on it")

    def test_dashboard_summaries_and_stats(self):
        # Add a couple of dummy tickets
        self.service.create_ticket("Title 1", "Desc 1", 1, 7, "2000")
        self.service.create_ticket("Title 2", "Desc 2", 3, 7, "2000")

        # Category stats
        cat_stats = self.service.ticket_stats_by_category()
        self.assertTrue(len(cat_stats) >= 1)

        # Dept stats
        dept_stats = self.service.ticket_stats_by_department()
        self.assertTrue(len(dept_stats) >= 1)

        # Dashboard summary for Faculty
        fac_summary = self.service.dashboard_summary({"id": 7, "role": "FACULTY", "org_id": "2000", "department": "CSE"})
        self.assertEqual(fac_summary["total"], 2)

        # HOD overview returns a list of HOD rows (not a dict with total_tickets)
        overview = self.service.hod_overview(org_id="2000")
        self.assertIsInstance(overview, list)

    def test_dynamic_helpers(self):
        # Create CA Assignment
        assign_id = self.service.create_ca_assignment(1, 4, "Block B")
        self.assertIsNotNone(assign_id)

        # Verify assignment was created in the mock state
        assignments = GLOBAL_DB_STATE.tables["demo_ca_assignments"]
        self.assertTrue(any(a.get("block") == "Block B" for a in assignments))

        # Delete CA Assignment by id
        self.service.delete_ca_assignment(assign_id)
        assignments_after = GLOBAL_DB_STATE.tables["demo_ca_assignments"]
        self.assertFalse(any(a.get("block") == "Block B" for a in assignments_after))

        # Create Location
        loc_id = self.service.create_location("2000", "Block C", "3rd Floor", "301", "Lab C")
        self.assertIsNotNone(loc_id)

        # Create Department
        dept_id = self.service.create_department("MECH", "Mechanical Engineering", "2000")
        self.assertIsNotNone(dept_id)
