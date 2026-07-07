import unittest
from unittest.mock import patch, MagicMock
import re
import copy
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from flask import session

# Import the Flask app and DB service classes
from app import app as flask_app, LOGIN_ATTEMPTS
import db_services

class MockDbState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.tables = {
            "demo_users": [],
            "demo_categories": [],
            "demo_tickets": [],
            "demo_ticket_activity": [],
            "demo_ca_assignments": [],
            "demo_problem_types": [],
            "demo_audit_events": [],
            "branch_detail": [],
            "teacher_info": [],
            "location": []
        }
        self.next_ids = {k: 1 for k in self.tables.keys()}
        self.seed_defaults()

    def seed_defaults(self):
        # 1. Seed departments (branch_detail)
        depts = [
            {"BRANCH_ID": 1, "BRANCH_CODE": "CSE", "department_code": "CSE", "BRANCH_NAME": "Computer Science", "department_name": "Computer Science", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": 3},
            {"BRANCH_ID": 2, "BRANCH_CODE": "ECE", "department_code": "ECE", "BRANCH_NAME": "Electronics", "department_name": "Electronics", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 3, "BRANCH_CODE": "Facilities", "department_code": "Facilities", "BRANCH_NAME": "Facilities & Estates", "department_name": "Facilities & Estates", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 4, "BRANCH_CODE": "Maintenance", "department_code": "Maintenance", "BRANCH_NAME": "Maintenance", "department_name": "Maintenance", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 5, "BRANCH_CODE": "Administration", "department_code": "Administration", "BRANCH_NAME": "Administration", "department_name": "Administration", "ORG_ID": "2000", "org_id": "2000", "is_archived": 0, "HOD_ID": None},
            {"BRANCH_ID": 6, "BRANCH_CODE": "CSE_SNU", "department_code": "CSE_SNU", "BRANCH_NAME": "CSE SNU", "department_name": "CSE SNU", "ORG_ID": "3000", "org_id": "3000", "is_archived": 0, "HOD_ID": None},
        ]
        self.tables["branch_detail"] = depts
        self.next_ids["branch_detail"] = 7

        # 2. Seed default users
        users = [
            {"id": 1, "name": "Super Admin", "email": "admin@gmail.com", "password": generate_password_hash("123"), "role": "SUPER_ADMIN", "department": "Administration", "org_id": "2000"},
            {"id": 2, "name": "Campus Admin", "email": "campus.admin@gmail.com", "password": generate_password_hash("123"), "role": "ADMIN", "department": "Administration", "org_id": "2000"},
            {"id": 3, "name": "Dr. Kavya", "email": "hod@gmail.com", "password": generate_password_hash("123"), "role": "HOD", "department": "CSE", "org_id": "2000"},
            {"id": 4, "name": "Chandini CA", "email": "ca@gmail.com", "password": generate_password_hash("123"), "role": "CA", "department": "CSE", "org_id": "2000"},
            {"id": 5, "name": "Sravan CA", "email": "sravan.ca@gmail.com", "password": generate_password_hash("123"), "role": "CA", "department": "Facilities", "org_id": "2000"},
            {"id": 6, "name": "Bhaskar CA", "email": "bhaskar.ca@gmail.com", "password": generate_password_hash("123"), "role": "CA", "department": "Maintenance", "org_id": "2000"},
            {"id": 7, "name": "Demo Faculty", "email": "faculty@gmail.com", "password": generate_password_hash("123"), "role": "FACULTY", "department": "CSE", "org_id": "2000"},
            {"id": 8, "name": "SNU Admin", "email": "snu.admin@gmail.com", "password": generate_password_hash("123"), "role": "SUPER_ADMIN", "department": "Administration", "org_id": "3000"},
        ]
        self.tables["demo_users"] = users
        self.next_ids["demo_users"] = 9

        # 3. Seed default categories
        categories = [
            {"id": 1, "category_name": "Internet", "department": "CSE", "assigned_ca_id": 4, "is_active": 1},
            {"id": 2, "category_name": "Projector", "department": "CSE", "assigned_ca_id": 4, "is_active": 1},
            {"id": 3, "category_name": "Plumbing", "department": "Facilities", "assigned_ca_id": 6, "is_active": 1},
            {"id": 4, "category_name": "Electrical", "department": "Maintenance", "assigned_ca_id": 6, "is_active": 1},
        ]
        self.tables["demo_categories"] = categories
        self.next_ids["demo_categories"] = 5

        # 4. Seed location table
        locations = [
            {"id": 1, "block": "Block A", "floor": "1st Floor", "room_no": "101", "name": "CSE Lab 1", "org_id": "2000"},
            {"id": 2, "block": "Block A", "floor": "1st Floor", "room_no": "102", "name": "Classroom", "org_id": "2000"},
            {"id": 3, "block": "SNU Block 1", "floor": "Ground Floor", "room_no": "001", "name": "Office", "org_id": "3000"},
        ]
        self.tables["location"] = locations
        self.next_ids["location"] = 4

        # 5. Seed teacher_info for auto-provisioning
        teachers = [
            {"sap_id": "10001", "SAP_ID": "10001", "name": "Seeded Teacher", "TEACHER_NAME": "Seeded Teacher", "EMAIL_ID": "seeded@sreenidhi.edu.in", "email_id": "seeded@sreenidhi.edu.in", "MOBILE_PHONE": "9876543210", "ACTIVE": 1, "BRANCH_CODE": "CSE", "BRANCH_ID": 1, "ORG_ID": "2000", "org_id": "2000", "department": "CSE", "TEACHER_CODE": "TC001", "DESIGNATION": "Asst Prof"},
            {"sap_id": "20001", "SAP_ID": "20001", "name": "SNU Teacher", "TEACHER_NAME": "SNU Teacher", "EMAIL_ID": "snuteacher@snu.edu.in", "email_id": "snuteacher@snu.edu.in", "MOBILE_PHONE": "9876543210", "ACTIVE": 1, "BRANCH_CODE": "CSE_SNU", "BRANCH_ID": 6, "ORG_ID": "3000", "org_id": "3000", "department": "CSE_SNU", "TEACHER_CODE": "TC002", "DESIGNATION": "Asst Prof"},
        ]
        self.tables["teacher_info"] = teachers
        self.next_ids["teacher_info"] = 3

        # 6. Seed CA Assignments
        ca_assignments = [
            {"id": 1, "category_id": 1, "ca_id": 4, "block": "Block A"},
        ]
        self.tables["demo_ca_assignments"] = ca_assignments
        self.next_ids["demo_ca_assignments"] = 2

        # 7. Seed problem types
        problem_types = [
            {"id": 1, "category_id": 1, "problem_name": "WiFi Down", "is_active": 1},
            {"id": 2, "category_id": 1, "problem_name": "Slow Speed", "is_active": 1},
        ]
        self.tables["demo_problem_types"] = problem_types
        self.next_ids["demo_problem_types"] = 3

GLOBAL_DB_STATE = MockDbState()

class MockCursor:
    def __init__(self, state):
        self.state = state
        self.lastrowid = None
        self.rowcount = 0
        self._results = []
        self._index = 0

    def execute(self, sql, params=None):
        params = params or ()
        sql_norm = " ".join(sql.split()).strip()
        sql_lower_stripped = sql_norm.lower()

        self._results = []
        self._index = 0
        self.rowcount = 0

        # Helper for column mapping
        def extract_columns_by_split(where_clause_lower):
            segments = where_clause_lower.split("%s")[:-1]
            ignored = {
                "lower", "coalesce", "upper", "and", "or", "not", "in", "is", "null", "like", 
                "select", "from", "where", "limit", "offset", "distinct", "join", "on", 
                "count", "as", "order", "by", "find_in_set", "char", "cast", "date"
            }
            cols = []
            for seg in segments:
                words = re.findall(r"\b[\w_.]+\b", seg)
                found_col = None
                for w in reversed(words):
                    col_name = w.split(".")[-1]
                    if col_name not in ignored and not col_name.isdigit():
                        found_col = col_name
                        break
                cols.append(found_col or "unknown")
            return cols

        def match_row(row, where_clause_lower, where_params):
            for keyw in ["order by", "group by", "limit", "offset"]:
                if keyw in where_clause_lower:
                    where_clause_lower = where_clause_lower[:where_clause_lower.index(keyw)].strip()

            if "is_archived" in where_clause_lower:
                if "is_archived, 0) = 0" in where_clause_lower or "is_archived = 0" in where_clause_lower:
                    is_archived_val = row.get("is_archived")
                    if is_archived_val is None:
                        is_archived_val = row.get("is_archived".upper())
                    if is_archived_val is not None and str(is_archived_val) != "0":
                        return False

            cols = extract_columns_by_split(where_clause_lower)
            mapped = []
            for col, val in zip(cols, where_params):
                if col != "unknown":
                    mapped.append((col, val))
            
            # Group by val to detect OR search conditions
            val_to_cols = {}
            for col, val in mapped:
                val_to_cols.setdefault(val, []).append(col)

            for val, cols_list in val_to_cols.items():
                if len(cols_list) > 1 and " or " in where_clause_lower:
                    any_match = False
                    for col in cols_list:
                        row_val = row.get(col)
                        if row_val is None:
                            row_val = row.get(col.upper())
                        if row_val is None and col == "sap_id":
                            row_val = row.get("SAP_ID")
                        if row_val is None and col == "email_id":
                            row_val = row.get("EMAIL_ID")
                        
                        if row_val is not None:
                            if isinstance(val, str) and "%" in val:
                                pattern = val.strip("%")
                                if not pattern or pattern.lower() in str(row_val).lower():
                                    any_match = True
                                    break
                            elif isinstance(row_val, str) and isinstance(val, str):
                                if row_val.lower().strip() == val.lower().strip():
                                    any_match = True
                                    break
                            elif str(row_val) == str(val):
                                any_match = True
                                break
                    if not any_match:
                        return False
                else:
                    for col in cols_list:
                        row_val = row.get(col)
                        if row_val is None:
                            row_val = row.get(col.upper())
                        if row_val is None and col == "sap_id":
                            row_val = row.get("SAP_ID")
                        if row_val is None and col == "email_id":
                            row_val = row.get("EMAIL_ID")
                        
                        if row_val is not None:
                            if isinstance(val, str) and "%" in val:
                                pattern = val.strip("%")
                                if not pattern:
                                    continue
                                if pattern.lower() not in str(row_val).lower():
                                    return False
                            elif isinstance(row_val, str) and isinstance(val, str):
                                if row_val.lower().strip() != val.lower().strip():
                                    return False
                            elif str(row_val) != str(val):
                                return False
                        else:
                            if isinstance(val, str) and "%" in val:
                                return False
                            return False
            return True

        # Handle INSERT
        if sql_lower_stripped.startswith("insert into"):
            table_match = re.search(r"insert into\s+(\w+)", sql_lower_stripped)
            if table_match:
                table_name = table_match.group(1)
                cols_part = re.search(r"\((.*?)\)", sql_norm)
                if cols_part:
                    columns = [c.strip().strip("`") for c in cols_part.group(1).split(",")]
                    row_data = {}
                    val_part_match = re.search(r"values\s*\((.*)\)", sql_norm, re.IGNORECASE)
                    if val_part_match:
                        exprs = [e.strip() for e in val_part_match.group(1).split(",")]
                        param_idx = 0
                        for col, expr in zip(columns, exprs):
                            if expr == "%s":
                                row_data[col] = params[param_idx]
                                param_idx += 1
                            else:
                                val = expr
                                if (val.startswith("'") and val.endswith("'")) or (val.startswith('"') and val.endswith('"')):
                                    val = val[1:-1]
                                elif val.isdigit():
                                    val = int(val)
                                row_data[col] = val
                    else:
                        for col, val in zip(columns, params):
                            row_data[col] = val

                    # Generate new ID if not present
                    if "id" not in row_data:
                        new_id = self.state.next_ids[table_name]
                        row_data["id"] = new_id
                        self.state.next_ids[table_name] += 1
                        self.lastrowid = new_id
                    else:
                        self.lastrowid = row_data["id"]

                    if table_name == "demo_categories":
                        if "is_active" not in row_data:
                            row_data["is_active"] = 1
                    if "created_at" not in row_data:
                        row_data["created_at"] = "2026-07-07 12:00:00"
                    if "updated_at" not in row_data:
                        row_data["updated_at"] = "2026-07-07 12:00:00"

                    self.state.tables[table_name].append(row_data)
                    self.rowcount = 1
            return

        # Handle UPDATE
        if sql_lower_stripped.startswith("update"):
            table_match = re.search(r"update\s+(\w+)", sql_lower_stripped)
            if table_match:
                table_name = table_match.group(1)
                
                where_clause_lower = ""
                if "where" in sql_lower_stripped:
                    where_clause_lower = sql_lower_stripped[sql_lower_stripped.index("where") + 5:].strip()

                set_part = sql_norm[sql_lower_stripped.index("set") + 3 : (sql_lower_stripped.index("where") if "where" in sql_lower_stripped else len(sql_norm))].strip()
                set_exprs = [s.strip() for s in set_part.split(",")]
                
                num_set_params = set_part.count("%s")
                set_vals = params[:num_set_params]
                where_vals = params[num_set_params:]

                updated_count = 0
                for row in self.state.tables[table_name]:
                    if not where_clause_lower or match_row(row, where_clause_lower, where_vals):
                        param_idx = 0
                        for expr in set_exprs:
                            col_name = expr.split("=")[0].strip().strip("`")
                            row[col_name] = set_vals[param_idx]
                            param_idx += 1
                        updated_count += 1
                self.rowcount = updated_count
            return

        # Handle DELETE
        if sql_lower_stripped.startswith("delete"):
            table_match = re.search(r"from\s+(\w+)", sql_lower_stripped)
            if table_match:
                table_name = table_match.group(1)
                where_clause_lower = ""
                if "where" in sql_lower_stripped:
                    where_clause_lower = sql_lower_stripped[sql_lower_stripped.index("where") + 5:].strip()

                before_len = len(self.state.tables[table_name])
                if where_clause_lower:
                    self.state.tables[table_name] = [
                        r for r in self.state.tables[table_name]
                        if not match_row(r, where_clause_lower, params)
                    ]
                else:
                    self.state.tables[table_name] = []
                self.rowcount = before_len - len(self.state.tables[table_name])
            return

        # Handle SELECT queries
        if "show columns" in sql_lower_stripped:
            col_to_check = params[0] if params else ""
            is_active = ("is_active" in sql_lower_stripped) or ("is_active" in col_to_check)
            status = ("status" in sql_lower_stripped) or ("status" in col_to_check)
            problem_type_id = ("problem_type_id" in sql_lower_stripped) or ("problem_type_id" in col_to_check)
            is_archived = ("is_archived" in sql_lower_stripped) or ("is_archived" in col_to_check)

            if is_active:
                self._results = [{"Field": "is_active", "Type": "tinyint(1)"}]
            elif status:
                self._results = [{"Field": "status", "Type": "enum('PENDING','IN_PROGRESS','ON_HOLD','RESOLVED','REOPENED')"}]
            elif problem_type_id:
                self._results = [{"Field": "problem_type_id", "Type": "int(10) unsigned"}]
            elif is_archived:
                self._results = [{"Field": "is_archived", "Type": "tinyint(1)"}]
            self.rowcount = len(self._results)
            return

        table_name = None
        for t in sorted(self.state.tables.keys(), key=len, reverse=True):
            if f"from {t}" in sql_lower_stripped:
                table_name = t
                break
            
        if "show tables" in sql_lower_stripped:
            self._results = []
            self.rowcount = 0
            return

        rows = self.state.tables[table_name]
        filtered_rows = []

        if "where" in sql_lower_stripped:
            where_clause_lower = sql_lower_stripped[sql_lower_stripped.index("where") + 5:].strip()
            for row in rows:
                if match_row(row, where_clause_lower, params):
                    filtered_rows.append(row)
        else:
            filtered_rows = list(rows)

        # Handle ORDER BY, LIMIT, OFFSET if simple
        if "limit 1" in sql_lower_stripped:
            filtered_rows = filtered_rows[:1]

        # Handle SELECT COUNT(*)
        if "count(" in sql_lower_stripped:
            self._results = [{"total": len(filtered_rows), "count": len(filtered_rows), "cnt": len(filtered_rows)}]
            self.rowcount = 1
            return

        # Simple SELECT alias and projection parsing
        select_cols = []
        select_part = "*"
        if sql_lower_stripped.startswith("select "):
            from_match = re.search(r"\bfrom\b", sql_lower_stripped)
            from_idx = from_match.start() if from_match else -1
            if from_idx != -1:
                select_part = sql_lower_stripped[7:from_idx].strip()
                if select_part.lower().startswith("distinct "):
                    select_part = select_part[9:].strip()
                parts = select_part.split(",")
                for p in parts:
                    p = p.strip()
                    as_match = re.search(r'\s+as\s+(\w+)\s*$', p, re.IGNORECASE)
                    if as_match:
                        alias = as_match.group(1).strip()
                        expr = p[:as_match.start()].strip()
                        select_cols.append((expr, alias))
                    else:
                        name = p.split(".")[-1].strip().strip("`")
                        select_cols.append((p, name))

        # Return copies of dicts to isolate state mutations (like del user["password"])
        results_copies = []
        for row in filtered_rows:
            new_row = {}
            if select_cols and "*" not in select_part:
                for expr, alias in select_cols:
                    words = re.findall(r"\b[a-zA-Z_0-9]+\b", expr)
                    val = None
                    for w in words:
                        for k, v in row.items():
                            if k.lower() == w.lower():
                                val = v
                                break
                        if val is not None:
                            break
                    new_row[alias] = val
            else:
                new_row = copy.deepcopy(row)
            
            # Map both lowercase and uppercase keys for test and app compatibility
            for k, v in list(new_row.items()):
                new_row[k.lower()] = v
                new_row[k.upper()] = v
            results_copies.append(new_row)

        import datetime
        for r in results_copies:
            for k in ["created_at", "updated_at"]:
                if k in r or (table_name and table_name in ["demo_tickets", "demo_ticket_history"]):
                    val = r.get(k)
                    if not val:
                        r[k] = datetime.datetime(2026, 7, 7, 12, 0, 0)
                    elif isinstance(val, str):
                        try:
                            r[k] = datetime.datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            r[k] = datetime.datetime(2026, 7, 7, 12, 0, 0)

        for r in results_copies:
            if table_name == "demo_tickets":
                creator = next((u for u in self.state.tables["demo_users"] if u["id"] == r.get("created_by")), None)
                assignee = next((u for u in self.state.tables["demo_users"] if u["id"] == r.get("assigned_to")), None)
                cat = next((c for c in self.state.tables["demo_categories"] if c["id"] == r.get("category_id")), None)
                loc_room = next((rm for rm in self.state.tables["location"] if rm["id"] == r.get("location_id")), None)
                prob_type = next((p for p in self.state.tables["demo_problem_types"] if p["id"] == r.get("problem_type_id")), None)

                r["created_by_name"] = creator["name"] if creator else "Unknown Faculty"
                r["created_by_email"] = creator["email"] if creator else ""
                r["assigned_to_name"] = assignee["name"] if assignee else "Unassigned CA"
                r["assigned_to_email"] = assignee["email"] if assignee else ""
                r["category_name"] = cat["category_name"] if cat else "Uncategorized"
                r["department"] = cat["department"] if cat else "General"
                r["room_no"] = loc_room["room_no"] if loc_room else ""
                r["block_name"] = loc_room["block"] if loc_room else ""
                r["problem_name"] = prob_type["problem_name"] if prob_type else ""

            elif table_name == "demo_categories":
                assignee = next((u for u in self.state.tables["demo_users"] if u["id"] == r.get("assigned_ca_id")), None)
                r["assigned_ca_name"] = assignee["name"] if assignee else "Unassigned CA"
                r["assigned_ca_email"] = assignee["email"] if assignee else ""

        self._results = results_copies
        self.rowcount = len(self._results)

    def fetchone(self):
        if self._index < len(self._results):
            row = self._results[self._index]
            self._index += 1
            return row
        return None

    def fetchall(self):
        res = self._results[self._index:]
        self._index = len(self._results)
        return res

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class MockConnection:
    def __init__(self, state):
        self.state = state

    def cursor(self, *args, **kwargs):
        return MockCursor(self.state)

    def close(self):
        pass

    def ping(self, reconnect=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

class HelpdeskTestCase(unittest.TestCase):
    def setUp(self):
        # 1. Reset database state before each test
        GLOBAL_DB_STATE.reset()
        LOGIN_ATTEMPTS.clear()
        
        # 2. Patch database connection pools to use mock connections
        self.conn_patcher = patch.object(db_services.BaseMySQLService, "connection", return_value=MockConnection(GLOBAL_DB_STATE))
        self.mock_conn = self.conn_patcher.start()

        # 3. Configure the Flask test client
        self.app = flask_app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False  # Disable CSRF token validation during testing
        self.app.config["SECRET_KEY"] = "test-secret"
        self.client = self.app.test_client()

        # Also patch notifications to avoid actual SMTP/SMS network calls
        self.sms_alloc_patcher = patch("sms_services.send_allocation_sms", return_value=(True, "Mock SMS success"))
        self.sms_close_patcher = patch("sms_services.send_closure_sms", return_value=(True, "Mock SMS success"))
        self.email_alloc_patcher = patch("email_services.send_allocation_email", return_value=True)
        self.email_close_patcher = patch("email_services.send_closure_email", return_value=True)

        self.mock_sms_alloc = self.sms_alloc_patcher.start()
        self.mock_sms_close = self.sms_close_patcher.start()
        self.mock_email_alloc = self.email_alloc_patcher.start()
        self.mock_email_close = self.email_close_patcher.start()

    def tearDown(self):
        self.conn_patcher.stop()
        self.sms_alloc_patcher.stop()
        self.sms_close_patcher.stop()
        self.email_alloc_patcher.stop()
        self.email_close_patcher.stop()

    def login_as(self, email, password="123", follow_redirects=False):
        """Helper to log in a user and set their session parameters."""
        response = self.client.post("/", data={"email": email, "password": password}, follow_redirects=follow_redirects)
        return response

    def logout(self):
        """Helper to clear current user sessions."""
        return self.client.get("/logout", follow_redirects=True)
