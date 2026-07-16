from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import os

from werkzeug.security import check_password_hash, generate_password_hash

try:
    import pymysql
except ImportError:  # pragma: no cover
    pymysql = None


ROLE_MAP = {
    "SUPER_ADMIN": "super_admin",
    "ADMIN": "admin",
    "HOD": "hod",
    "CA": "authority",
    "FACULTY": "faculty",
}

APP_ROLE_TO_DB = {value: key for key, value in ROLE_MAP.items()}


@dataclass
class DbConfig:
    host: str
    port: int
    user: str
    password: str
    database: str


def env_db_config() -> DbConfig | None:
    if pymysql is None:
        return None
    host = os.getenv("MYSQL_HOST", "seg-dev.sreenidhi.edu.in")
    user = os.getenv("MYSQL_USER", "demo")
    password = os.getenv("MYSQL_PASSWORD", "Admin@321#")
    database = os.getenv("MYSQL_DATABASE", "seg_demo")
    if not all([host, user, password, database]):
        return None
    return DbConfig(
        host=host,
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=user,
        password=password,
        database=database,
    )


from queue import Queue, Empty

class PooledConnection:
    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def close(self):
        # Return connection back to the pool
        if self._conn is not None:
            try:
                self._pool.put_nowait(self._conn)
            except Exception:
                try:
                    self._conn.close()
                except Exception:
                    pass
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class BaseMySQLService:
    def __init__(self, config: DbConfig | None):
        self.config = config
        self._pool = Queue(maxsize=10)

    @property
    def enabled(self) -> bool:
        return self.config is not None and pymysql is not None

    def _create_new_connection(self):
        ssl_config = None
        if os.getenv("MYSQL_SSL", "").lower() == "true":
            ssl_config = {"ca": None}  # Use system default CA bundle
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            ssl=ssl_config,
        )

    def connection(self):
        if not self.enabled:
            raise RuntimeError("MySQL is not configured.")
        try:
            conn = self._pool.get_nowait()
            conn.ping(reconnect=True)
        except (Empty, Exception):
            conn = self._create_new_connection()
        return PooledConnection(conn, self._pool)


class LiveDbService(BaseMySQLService):
    def fetch_departments(self, include_archived=True):
        if not self.enabled:
            return []
        sql = """
            SELECT DISTINCT
                b.BRANCH_ID,
                b.BRANCH_CODE AS department_code,
                b.BRANCH_NAME AS department_name,
                CAST(b.ORG_ID AS CHAR) AS org_id,
                b.HOD_ID
        """
        # Check if is_archived column exists and include it
        try:
            with self.connection() as conn, conn.cursor() as cur:
                cur.execute("SHOW COLUMNS FROM branch_detail LIKE 'is_archived'")
                has_archived = cur.fetchone() is not None
        except Exception:
            has_archived = False

        if has_archived:
            sql += ", COALESCE(b.is_archived, 0) AS is_archived"

        sql += """
            FROM branch_detail b
            WHERE COALESCE(b.BRANCH_CODE, '') <> ''
        """
        if has_archived and not include_archived:
            sql += " AND COALESCE(b.is_archived, 0) = 0"
        sql += " ORDER BY b.BRANCH_CODE"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def update_location(self, location_id, block, floor, room_no, name):
        """Update a location row."""
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE location SET block = %s, floor = %s, room_no = %s, name = %s WHERE id = %s",
                (block, floor, room_no, name, location_id),
            )

    def delete_location(self, location_id):
        """Delete a location if no tickets reference it."""
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM demo_tickets WHERE location_id = %s", (location_id,))
            row = cursor.fetchone()
            if row and row["cnt"] > 0:
                raise ValueError("Cannot delete a location that is referenced by existing tickets.")
            cursor.execute("DELETE FROM location WHERE id = %s", (location_id,))

    def get_location(self, location_id):
        """Get a single location by ID."""
        if not self.enabled:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, block, floor, room_no, name FROM location WHERE id = %s", (location_id,))
            return cursor.fetchone()

    def fetch_locations(self):
        """Return all location rows (block, floor, room_no, name)."""
        if not self.enabled:
            return []
        sql = """
            SELECT id, block, floor, room_no, name
            FROM location
            ORDER BY block, floor, room_no
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def fetch_reference_users(self, search="", department=None, limit=100, org_id=None):
        if not self.enabled:
            return []
        sql = """
            SELECT
                t.TEACHER_NAME,
                t.EMAIL_ID,
                t.SAP_ID,
                t.TEACHER_CODE,
                t.DESIGNATION,
                t.MOBILE_PHONE,
                CAST(t.ORG_ID AS CHAR) AS org_id,
                b.BRANCH_CODE AS department_code,
                b.BRANCH_NAME AS department_name,
                b.HOD_ID
            FROM teacher_info t
            LEFT JOIN branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
            WHERE COALESCE(t.ACTIVE, 1) = 1
        """
        params = []
        if department:
            sql += " AND (b.BRANCH_CODE = %s OR b.BRANCH_NAME = %s)"
            params.extend([department, department])
        if org_id:
            sql += " AND CAST(t.ORG_ID AS CHAR) = %s"
            params.append(org_id)
        if search:
            sql += " AND (t.TEACHER_NAME LIKE %s OR t.EMAIL_ID LIKE %s OR t.SAP_ID LIKE %s OR t.TEACHER_CODE LIKE %s)"
            like = f"%{search}%"
            params.extend([like, like, like, like])
        sql += " ORDER BY t.TEACHER_NAME LIMIT %s"
        params.append(limit)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def lookup_teacher_by_email(self, email):
        """Look up a teacher from teacher_info by email. Returns dict with name, sap_id, department, org_id or None."""
        if not self.enabled:
            return None
        sql = """
            SELECT
                t.TEACHER_NAME AS name,
                t.SAP_ID AS sap_id,
                t.EMAIL_ID AS email,
                CAST(t.ORG_ID AS CHAR) AS org_id,
                b.BRANCH_CODE AS department
            FROM teacher_info t
            LEFT JOIN branch_detail b ON b.BRANCH_ID = t.BRANCH_ID
            WHERE LOWER(COALESCE(t.EMAIL_ID, '')) = LOWER(%s)
              AND COALESCE(t.ACTIVE, 1) = 1
            LIMIT 1
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, (email,))
            return cursor.fetchone()

    def resolve_org_id(self, email="", department=""):
        if not self.enabled:
            return None
        with self.connection() as connection, connection.cursor() as cursor:
            if email:
                cursor.execute(
                    """
                    SELECT CAST(ORG_ID AS CHAR) AS org_id
                    FROM teacher_info
                    WHERE LOWER(COALESCE(EMAIL_ID, '')) = LOWER(%s)
                    LIMIT 1
                    """,
                    (email,),
                )
                row = cursor.fetchone()
                if row and row.get("org_id"):
                    return row["org_id"]
            if department:
                cursor.execute(
                    """
                    SELECT CAST(ORG_ID AS CHAR) AS org_id
                    FROM branch_detail
                    WHERE BRANCH_CODE = %s OR BRANCH_NAME = %s
                    LIMIT 1
                    """,
                    (department, department),
                )
                row = cursor.fetchone()
                if row and row.get("org_id"):
                    return row["org_id"]
        return None


class DemoDbService(BaseMySQLService):
    def get_user_phone(self, email):
        """Query teacher_info for user's MOBILE_PHONE. Returns phone number or fallback."""
        phone = None
        if self.enabled and email:
            sql = """
                SELECT MOBILE_PHONE
                FROM teacher_info
                WHERE LOWER(COALESCE(EMAIL_ID, '')) = LOWER(%s)
                  AND COALESCE(ACTIVE, 1) = 1
                LIMIT 1
            """
            try:
                with self.connection() as connection, connection.cursor() as cursor:
                    cursor.execute(sql, (email,))
                    row = cursor.fetchone()
                    if row:
                        phone = row.get("MOBILE_PHONE")
            except Exception:
                pass
        return phone if phone else os.getenv("SMS_TEST_NUMBER")

    def ensure_schema(self, schema_path: Path):
        if not self.enabled:
            return
        sql = schema_path.read_text(encoding="utf-8")
        statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
        with self.connection() as connection, connection.cursor() as cursor:
            for statement in statements:
                try:
                    cursor.execute(statement)
                except Exception as e:
                    print(f"Warning executing statement in ensure_schema: {e}")

    def seed_defaults(self, users, categories):
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            # Seed users individually if they do not exist
            for u in users:
                cursor.execute("SELECT id FROM demo_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (u["email"],))
                if not cursor.fetchone():
                    cursor.execute(
                        """
                        INSERT INTO demo_users (name, email, password, role, department)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (u["name"], u["email"], generate_password_hash(u["password"]), u["role"], u["department"]),
                    )

            # Seed categories individually if they do not exist
            if categories:
                for category in categories:
                    cursor.execute(
                        "SELECT id FROM demo_categories WHERE LOWER(category_name) = LOWER(%s) AND department = %s LIMIT 1",
                        (category["category_name"], category["department"])
                    )
                    if not cursor.fetchone():
                        cursor.execute("SELECT id FROM demo_users WHERE email = %s LIMIT 1", (category["authority_email"],))
                        row = cursor.fetchone()
                        if not row:
                            continue
                        cursor.execute(
                            """
                            INSERT INTO demo_categories (category_name, department, assigned_ca_id)
                            VALUES (%s, %s, %s)
                            """,
                            (category["category_name"], category["department"], row["id"]),
                        )

    def authenticate_user(self, email, password):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, name, email, password, role, department
                FROM demo_users
                WHERE LOWER(email) = LOWER(%s)
                LIMIT 1
                """,
                (email,),
            )
            user = cursor.fetchone()
            if not user or not check_password_hash(user["password"], password):
                return None
            # Don't return the password hash to the caller
            del user["password"]
            return user

    def change_password(self, user_id, old_password, new_password):
        """Verify old password and update to new password. Raises ValueError on mismatch."""
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT password FROM demo_users WHERE id = %s", (user_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("User not found.")
            if not check_password_hash(row["password"], old_password):
                return False
            hashed = generate_password_hash(new_password)
            cursor.execute("UPDATE demo_users SET password = %s WHERE id = %s", (hashed, user_id))
            return True

    def get_user(self, user_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, name, email, role, department, created_at FROM demo_users WHERE id = %s", (user_id,))
            return cursor.fetchone()

    def get_user_by_email(self, email):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id, name, email, role, department, created_at FROM demo_users WHERE LOWER(email) = LOWER(%s) LIMIT 1",
                (email,),
            )
            return cursor.fetchone()

    def list_users(self, role=None, department=None, search="", org_id=None, limit=None, offset=None):
        sql = "SELECT id, name, email, role, department, created_at FROM demo_users WHERE 1=1"
        params = []
        if role:
            if isinstance(role, (list, tuple)):
                # Multi-role filter: use IN clause
                placeholders = ", ".join(["%s"] * len(role))
                sql += f" AND role IN ({placeholders})"
                params.extend(role)
            else:
                sql += " AND role = %s"
                params.append(role)
        if department:
            sql += " AND (department = %s OR FIND_IN_SET(%s, department) > 0)"
            params.extend([department, department])
        if search:
            like = f"%{search}%"
            sql += " AND (name LIKE %s OR email LIKE %s OR department LIKE %s)"
            params.extend([like, like, like])
        sql += " ORDER BY created_at DESC"
        
        with self.connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                users = cursor.fetchall()

            if not org_id:
                if limit is not None:
                    offset_val = offset or 0
                    return users[offset_val : offset_val + limit]
                return users

            # Find which branch_codes belong to this org_id
            branch_codes = set()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT BRANCH_CODE FROM branch_detail WHERE CAST(ORG_ID AS CHAR) = %s",
                    (org_id,)
                )
                for r in cursor.fetchall():
                    if r.get("BRANCH_CODE"):
                        branch_codes.add(r["BRANCH_CODE"])

        filtered_users = []
        for u in users:
            u_email = u["email"]
            u_dept = u["department"]
            
            # Determine user's org
            u_org = "3000" if (u_email and "snu" in u_email.lower()) else "2000"
            if u_org == "2000" and u_dept:
                depts = [d.strip() for d in u_dept.split(",")]
                if any(d in branch_codes for d in depts):
                    u_org = org_id

            if u_org == org_id:
                filtered_users.append(u)

        if limit is not None:
            offset_val = offset or 0
            filtered_users = filtered_users[offset_val : offset_val + limit]
        return filtered_users

    def create_user(self, payload):
        hashed = generate_password_hash(payload["password"])
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO demo_users (name, email, password, role, department)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (payload["name"], payload["email"], hashed, payload["role"], payload["department"]),
            )
            return cursor.lastrowid

    def update_user(self, user_id, payload):
        if not self.enabled:
            return
        fields = []
        params = []
        for k in ["name", "email", "role", "department"]:
            if k in payload:
                fields.append(f"{k} = %s")
                params.append(payload[k])
        if "password" in payload and payload["password"]:
            fields.append("password = %s")
            params.append(generate_password_hash(payload["password"]))
            
        if not fields:
            return
            
        sql = f"UPDATE demo_users SET {', '.join(fields)} WHERE id = %s"
        params.append(user_id)
        
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, tuple(params))

    def delete_user(self, user_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM demo_categories WHERE assigned_ca_id = %s) AS category_refs,
                    (SELECT COUNT(*) FROM demo_tickets WHERE created_by = %s OR assigned_to = %s) AS ticket_refs,
                    (SELECT COUNT(*) FROM demo_ticket_activity WHERE action_by = %s) AS activity_refs
                """,
                (user_id, user_id, user_id, user_id),
            )
            refs = cursor.fetchone()
            if any(refs.values()):
                raise ValueError("Cannot delete a user that is referenced by categories, tickets, or activity.")
            cursor.execute("DELETE FROM demo_users WHERE id = %s", (user_id,))

    def list_categories(self, department=None, search="", ca_id=None, org_id=None, active_only=False, limit=None, offset=None):
        sql = """
            SELECT c.id, c.category_name, c.department, c.assigned_ca_id, c.is_active, c.created_at,
                   u.name AS assigned_ca_name, u.email AS assigned_ca_email
            FROM demo_categories c
            LEFT JOIN demo_users u ON u.id = c.assigned_ca_id
            WHERE 1=1
        """
        params = []
        if active_only:
            sql += " AND c.is_active = 1"
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if ca_id:
            sql += " AND c.assigned_ca_id = %s"
            params.append(ca_id)
        if org_id:
            sql += " AND c.department IN (SELECT BRANCH_CODE FROM branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)
        if search:
            like = f"%{search}%"
            sql += " AND (c.category_name LIKE %s OR u.name LIKE %s)"
            params.extend([like, like])
        sql += " ORDER BY c.department, c.category_name"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET %s"
                params.append(offset)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def category_exists(self, category_name, department, exclude_id=None):
        """Check if a category with the same name+department already exists."""
        sql = "SELECT id FROM demo_categories WHERE LOWER(category_name) = LOWER(%s) AND department = %s"
        params = [category_name, department]
        if exclude_id:
            sql += " AND id != %s"
            params.append(exclude_id)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone() is not None

    def create_category(self, payload):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO demo_categories (category_name, department, assigned_ca_id)
                VALUES (%s, %s, %s)
                """,
                (payload["category_name"], payload["department"], payload["assigned_ca_id"]),
            )
            return cursor.lastrowid

    def update_category(self, category_id, payload):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE demo_categories
                SET category_name = %s, department = %s, assigned_ca_id = %s
                WHERE id = %s
                """,
                (payload["category_name"], payload["department"], payload["assigned_ca_id"], category_id),
            )

    def delete_category(self, category_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM demo_tickets WHERE category_id = %s", (category_id,))
            if cursor.fetchone()["total"]:
                raise ValueError("Cannot delete a category that is already used by tickets.")
            cursor.execute("DELETE FROM demo_categories WHERE id = %s", (category_id,))

    def get_category(self, category_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT c.id, c.category_name, c.department, c.assigned_ca_id, c.is_active, u.name AS assigned_ca_name
                FROM demo_categories c
                LEFT JOIN demo_users u ON u.id = c.assigned_ca_id
                WHERE c.id = %s
                """,
                (category_id,),
            )
            return cursor.fetchone()

    def toggle_category_status(self, category_id, is_active):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE demo_categories
                SET is_active = %s
                WHERE id = %s
                """,
                (1 if is_active else 0, category_id),
            )

    def create_ticket(self, title, description, category_id, created_by, org_id, location_id=None):
        category = self.get_category(category_id)
        if not category:
            raise ValueError("Selected category does not exist.")

        # Auto-generate title from category if title is empty
        if not title:
            title = category["category_name"]

        # Retrieve block name if location_id is provided
        block_name = None
        if location_id:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute("SELECT block FROM location WHERE id = %s", (location_id,))
                row = cursor.fetchone()
                if row:
                    block_name = row.get("block")

        # Resolve assigned CA dynamically
        assigned_ca_id = self.resolve_assigned_ca(category_id, block_name) or category["assigned_ca_id"]

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO demo_tickets (title, description, category_id, created_by, assigned_to, status, org_id, location_id)
                VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s)
                """,
                (title, description, category_id, created_by, assigned_ca_id, org_id, location_id),
            )
            ticket_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO demo_ticket_activity (ticket_id, action_by, from_status, to_status, remarks)
                VALUES (%s, %s, NULL, 'PENDING', %s)
                """,
                (ticket_id, created_by, "Ticket created"),
            )
            try:
                from email_services import send_allocation_email
                ca_user = self.get_user(assigned_ca_id)
                if ca_user and ca_user.get("email"):
                    send_allocation_email(ca_user["name"], ca_user["email"], ticket_id, category["category_name"])
            except Exception:
                pass
            try:
                from sms_services import send_allocation_sms
                ca_user = self.get_user(assigned_ca_id)
                if ca_user and ca_user.get("email"):
                    ca_phone = self.get_user_phone(ca_user["email"])
                    if ca_phone:
                        send_allocation_sms(
                            ca_user["name"], ca_phone, ticket_id,
                            category_name=category.get("category_name", "System"),
                            department=category.get("department", "ICT Department"),
                        )
            except Exception:
                pass
            return ticket_id

    def _has_column(self, table, column):
        """Check if a column exists in a table."""
        try:
            with self.connection() as conn, conn.cursor() as cur:
                cur.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
                return cur.fetchone() is not None
        except Exception:
            return False

    def ticket_query_base(self):
        return """
            SELECT
                t.id,
                t.title,
                t.description,
                t.status,
                t.org_id,
                t.location_id,
                t.category_id,
                t.created_by,
                t.assigned_to,
                t.created_at,
                t.updated_at,
                c.category_name,
                c.department,
                creator.name AS created_by_name,
                creator.email AS created_by_email,
                assignee.name AS assigned_to_name,
                assignee.email AS assigned_to_email,
                loc.block AS location_block,
                loc.floor AS location_floor,
                loc.room_no AS location_room_no,
                loc.name AS location_room_name
            FROM demo_tickets t
            INNER JOIN demo_categories c ON c.id = t.category_id
            INNER JOIN demo_users creator ON creator.id = t.created_by
            INNER JOIN demo_users assignee ON assignee.id = t.assigned_to
            LEFT JOIN location loc ON loc.id = t.location_id
            WHERE 1=1
        """

    def list_tickets(self, viewer, scope="all", filters=None, limit=None, offset=None):
        filters = filters or {}
        sql = self.ticket_query_base()
        params = []

        # Enforce org partitioning for all queries
        sql += " AND t.org_id = %s"
        params.append(viewer.get("org_id", "2000"))

        if scope == "own":
            sql += " AND t.created_by = %s"
            params.append(viewer["id"])
        elif scope == "assigned":
            sql += " AND t.assigned_to = %s"
            params.append(viewer["id"])
        elif viewer["role"] == "HOD":
            sql += " AND c.department = %s"
            params.append(viewer["department"])

        if filters.get("status"):
            sql += " AND t.status = %s"
            params.append(filters["status"])
        if filters.get("department"):
            sql += " AND c.department = %s"
            params.append(filters["department"])
        if filters.get("category_id"):
            sql += " AND t.category_id = %s"
            params.append(filters["category_id"])
        if filters.get("org_id"):
            # If viewer is SUPER_ADMIN/ADMIN they might filter by org, but it's already scoped
            # Still, we can append it just in case
            sql += " AND t.org_id = %s"
            params.append(filters["org_id"])
        if filters.get("from_date"):
            sql += " AND DATE(t.created_at) >= %s"
            params.append(filters["from_date"])
        if filters.get("to_date"):
            sql += " AND DATE(t.created_at) <= %s"
            params.append(filters["to_date"])
        if filters.get("q"):
            like = f"%{filters['q']}%"
            sql += " AND (t.title LIKE %s OR t.description LIKE %s OR c.category_name LIKE %s OR creator.name LIKE %s OR assignee.name LIKE %s)"
            params.extend([like, like, like, like, like])

        sql += " ORDER BY t.updated_at DESC"
        if limit is not None:
            sql += " LIMIT %s"
            params.append(limit)
            if offset is not None:
                sql += " OFFSET %s"
                params.append(offset)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def list_ticket_activity(self, ticket_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.id, a.from_status, a.to_status, a.remarks, a.time_taken, a.attachment_path, a.created_at,
                       u.name AS action_by_name
                FROM demo_ticket_activity a
                INNER JOIN demo_users u ON u.id = a.action_by
                WHERE a.ticket_id = %s
                ORDER BY a.created_at DESC
                """,
                (ticket_id,),
            )
            return cursor.fetchall()

    def get_ticket(self, ticket_id):
        sql = self.ticket_query_base() + " AND t.id = %s LIMIT 1"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, (ticket_id,))
            return cursor.fetchone()

    ALLOWED_TRANSITIONS = {
        "PENDING": {"IN_PROGRESS"},
        "IN_PROGRESS": {"ON_HOLD", "RESOLVED"},
        "ON_HOLD": {"IN_PROGRESS"},
        "RESOLVED": {"REOPENED"},
        "REOPENED": {"IN_PROGRESS"},
    }

    def update_ticket_status(self, ticket_id, actor, status, remarks="", time_taken="", attachment_path=""):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket not found.")

        if actor.get("org_id") and ticket.get("org_id") and ticket["org_id"] != actor["org_id"]:
            raise PermissionError("Access denied: Ticket belongs to a different organization.")

        # Permission check:
        # - Assigned CA can update their own assigned tickets
        # - SUPER_ADMIN can update any ticket
        # - Ticket creator can REOPEN a RESOLVED ticket
        is_assigned_ca = (
            actor.get("role") == "CA"
            and (
                (ticket.get("assigned_to_email") and actor.get("email") and ticket["assigned_to_email"].lower() == actor["email"].lower())
                or (ticket.get("assigned_to") == actor.get("id"))
            )
        )
        is_super_admin = actor.get("role") == "SUPER_ADMIN"
        is_creator_reopening = (
            (
                (ticket.get("created_by_email") and actor.get("email") and ticket["created_by_email"].lower() == actor["email"].lower())
                or (ticket.get("created_by") == actor.get("id"))
            )
            and ticket.get("status") == "RESOLVED"
            and status == "REOPENED"
        )
        if not is_assigned_ca and not is_super_admin and not is_creator_reopening:
            raise PermissionError("Only the assigned Concerned Authority can update this ticket.")

        # Enforce valid status transitions
        current_status = ticket["status"]
        allowed = self.ALLOWED_TRANSITIONS.get(current_status, set())
        if status not in allowed:
            raise ValueError(
                f"Invalid status transition: Cannot transition from {current_status} to {status}. "
                f"Allowed: {', '.join(sorted(allowed)) or 'none (terminal state)'}."
            )

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE demo_tickets SET status = %s WHERE id = %s",
                (status, ticket_id),
            )
            cursor.execute(
                """
                INSERT INTO demo_ticket_activity
                    (ticket_id, action_by, from_status, to_status, remarks, time_taken, attachment_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (ticket_id, actor["id"], ticket["status"], status, remarks, time_taken, attachment_path),
            )
            if status == "RESOLVED":
                try:
                    from email_services import send_closure_email
                    if ticket.get("created_by_email"):
                        send_closure_email(ticket["created_by_email"], ticket_id)
                except Exception:
                    pass
                try:
                    from sms_services import send_closure_sms
                    if ticket.get("created_by_email"):
                        creator_phone = self.get_user_phone(ticket["created_by_email"])
                        if creator_phone:
                            send_closure_sms(creator_phone, ticket_id)
                except Exception:
                    pass
        return True

    # ── Analytics ────────────────────────────────────────

    def ticket_stats_by_category(self, department=None, org_id=None):
        on_clause = "ON t.category_id = c.id"
        params = []
        if org_id:
            on_clause += " AND t.org_id = %s"
            params.append(org_id)

        sql = f"""
            SELECT c.category_name, c.department,
                   COUNT(t.id) AS ticket_count,
                   SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                   SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS on_hold,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
                   SUM(CASE WHEN t.status = 'REOPENED' THEN 1 ELSE 0 END) AS reopened
            FROM demo_categories c
            LEFT JOIN demo_tickets t {on_clause}
            WHERE 1=1
        """
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if org_id:
            sql += " AND c.department IN (SELECT BRANCH_CODE FROM branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)

        sql += " GROUP BY c.id, c.category_name, c.department ORDER BY ticket_count DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def ticket_stats_by_department(self, org_id=None):
        on_clause = "ON t.category_id = c.id"
        params = []
        if org_id:
            on_clause += " AND t.org_id = %s"
            params.append(org_id)

        sql = f"""
            SELECT c.department,
                   COUNT(t.id) AS ticket_count,
                   SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                   SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS on_hold,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
                   SUM(CASE WHEN t.status = 'REOPENED' THEN 1 ELSE 0 END) AS reopened
            FROM demo_categories c
            LEFT JOIN demo_tickets t {on_clause}
            WHERE 1=1
        """
        if org_id:
            sql += " AND c.department IN (SELECT BRANCH_CODE FROM branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)

        sql += """
            GROUP BY c.department
            ORDER BY ticket_count DESC
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def dashboard_summary(self, viewer):
        sql = """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN t.status = 'ON_HOLD' THEN 1 ELSE 0 END) AS on_hold,
                SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN t.status = 'REOPENED' THEN 1 ELSE 0 END) AS reopened
            FROM demo_tickets t
            INNER JOIN demo_categories c ON c.id = t.category_id
            WHERE 1=1
        """
        params = []
        if viewer["role"] == "FACULTY":
            sql += " AND t.created_by = %s"
            params.append(viewer["id"])
        elif viewer["role"] == "CA":
            sql += " AND t.assigned_to = %s"
            params.append(viewer["id"])
        elif viewer["role"] == "HOD":
            sql += " AND c.department = %s"
            params.append(viewer["department"])

        if viewer.get("org_id"):
            sql += " AND t.org_id = %s"
            params.append(viewer["org_id"])

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def hod_overview(self, org_id=None):
        sql = """
            SELECT
                u.id,
                u.name,
                u.email,
                u.department,
                COUNT(DISTINCT c.id) AS category_count,
                COUNT(DISTINCT t.id) AS ticket_count
            FROM demo_users u
            LEFT JOIN demo_categories c ON c.department = u.department
            LEFT JOIN demo_tickets t ON t.category_id = c.id
            WHERE u.role = 'HOD'
        """
        params = []
        if org_id:
            sql += " AND u.department IN (SELECT BRANCH_CODE FROM branch_detail WHERE CAST(ORG_ID AS CHAR) = %s)"
            params.append(org_id)

        sql += """
            GROUP BY u.id, u.name, u.email, u.department
            ORDER BY u.department
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def create_location(self, org_id, block, floor, room_no, name):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO location (ORG_ID, block, floor, room_no, name)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (org_id, block, floor, room_no, name),
            )
            return cursor.lastrowid

    def create_department(self, branch_code, branch_name, org_id):
        with self.connection() as connection, connection.cursor() as cursor:
            # Check if department code already exists
            cursor.execute(
                "SELECT BRANCH_ID FROM branch_detail WHERE LOWER(BRANCH_CODE) = LOWER(%s) AND ORG_ID = %s LIMIT 1",
                (branch_code, org_id),
            )
            if cursor.fetchone():
                raise ValueError(f"Department code '{branch_code}' already exists.")
            cursor.execute(
                """
                INSERT INTO branch_detail (BRANCH_CODE, BRANCH_NAME, ORG_ID)
                VALUES (%s, %s, %s)
                """,
                (branch_code, branch_name, org_id),
            )
            return cursor.lastrowid

    def list_ca_assignments(self, department=None, search=""):
        sql = """
            SELECT a.id, a.category_id, a.ca_id, a.block, a.created_at,
                   c.category_name, c.department,
                   u.name AS ca_name, u.email AS ca_email
            FROM demo_ca_assignments a
            INNER JOIN demo_categories c ON c.id = a.category_id
            INNER JOIN demo_users u ON u.id = a.ca_id
            WHERE 1=1
        """
        params = []
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if search:
            like = f"%{search}%"
            sql += " AND (c.category_name LIKE %s OR u.name LIKE %s OR a.block LIKE %s)"
            params.extend([like, like, like])
        sql += " ORDER BY c.category_name, a.block"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def create_ca_assignment(self, category_id, ca_id, block):
        with self.connection() as connection, connection.cursor() as cursor:
            # Check if assignment already exists
            cursor.execute(
                """
                SELECT id FROM demo_ca_assignments
                WHERE category_id = %s AND ca_id = %s AND LOWER(block) = LOWER(%s)
                LIMIT 1
                """,
                (category_id, ca_id, block),
            )
            if cursor.fetchone():
                raise ValueError("This CA is already assigned to this category and block.")
            cursor.execute(
                """
                INSERT INTO demo_ca_assignments (category_id, ca_id, block)
                VALUES (%s, %s, %s)
                """,
                (category_id, ca_id, block),
            )
            return cursor.lastrowid

    def delete_ca_assignment(self, assignment_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("DELETE FROM demo_ca_assignments WHERE id = %s", (assignment_id,))

    def resolve_assigned_ca(self, category_id, block):
        """
        Resolve who to assign the ticket to.
        Multi-CA routing engine (Feature 6):
        1. Find all CAs assigned to this category+block via demo_ca_assignments.
        2. If block match found, select least-loaded CA among matches.
        3. If no block match, find ALL CAs for this category (any block) as secondary pool.
        4. Fall back to category's default assigned_ca_id.
        """
        category = self.get_category(category_id)
        if not category:
            return None

        with self.connection() as connection, connection.cursor() as cursor:
            # Step 1: Exact block match
            if block:
                cursor.execute(
                    "SELECT ca_id FROM demo_ca_assignments WHERE category_id = %s AND LOWER(block) = LOWER(%s)",
                    (category_id, block),
                )
                rows = cursor.fetchall()
                if rows:
                    ca_ids = [r["ca_id"] for r in rows]
                    return self._select_least_loaded_ca(cursor, ca_ids)

            # Step 2: Any block for this category
            cursor.execute(
                "SELECT DISTINCT ca_id FROM demo_ca_assignments WHERE category_id = %s",
                (category_id,),
            )
            rows = cursor.fetchall()
            if rows:
                ca_ids = [r["ca_id"] for r in rows]
                return self._select_least_loaded_ca(cursor, ca_ids)

            # Step 3: Fallback to category's default assigned CA
            return category["assigned_ca_id"]

    def _select_least_loaded_ca(self, cursor, ca_ids):
        """Given a list of CA IDs, return the one with the fewest active tickets."""
        if len(ca_ids) == 1:
            return ca_ids[0]
        placeholders = ", ".join(["%s"] * len(ca_ids))
        sql_load = f"""
            SELECT u.id, COUNT(t.id) AS active_count
            FROM demo_users u
            LEFT JOIN demo_tickets t ON t.assigned_to = u.id AND t.status IN ('PENDING', 'IN_PROGRESS', 'REOPENED')
            WHERE u.id IN ({placeholders})
            GROUP BY u.id
            ORDER BY active_count ASC, u.id ASC
        """
        cursor.execute(sql_load, ca_ids)
        load_rows = cursor.fetchall()
        counts = {r["id"]: r["active_count"] for r in load_rows}
        return min(ca_ids, key=lambda cid: counts.get(cid, 0))

    # ── Audit Events (Feature 11) ───────────────────────────

    # ── Audit Events (Feature 11) ───────────────────────────

    def log_audit_event(self, event_type, actor_id, org_id, target_type=None, target_id=None, details=None):
        """Insert an audit event. `details` can be a dict (will be JSON-serialized)."""
        details_str = json.dumps(details) if isinstance(details, dict) else (details or "")
        try:
            with self.connection() as connection, connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO demo_audit_events (event_type, actor_id, target_type, target_id, org_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (event_type, actor_id, target_type, target_id, org_id, details_str),
                )
        except Exception:
            pass  # Audit should never break main flow

    def list_audit_events(self, org_id=None, event_type=None, search="", from_date=None, to_date=None, limit=100):
        sql = """
            SELECT a.id, a.event_type, a.actor_id, a.target_type, a.target_id,
                   a.org_id, a.details, a.created_at,
                   u.name AS actor_name, u.email AS actor_email
            FROM demo_audit_events a
            INNER JOIN demo_users u ON u.id = a.actor_id
            WHERE 1=1
        """
        params = []
        if org_id:
            sql += " AND a.org_id = %s"
            params.append(org_id)
        if event_type:
            sql += " AND a.event_type = %s"
            params.append(event_type)
        if search:
            like = f"%{search}%"
            sql += " AND (a.details LIKE %s OR u.name LIKE %s OR a.event_type LIKE %s)"
            params.extend([like, like, like])
        if from_date:
            sql += " AND DATE(a.created_at) >= %s"
            params.append(from_date)
        if to_date:
            sql += " AND DATE(a.created_at) <= %s"
            params.append(to_date)
        sql += " ORDER BY a.created_at DESC LIMIT %s"
        params.append(limit)
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    # ── Department Management (Feature 4) ───────────────────

    def update_department(self, branch_id, branch_code, branch_name):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE branch_detail SET BRANCH_CODE = %s, BRANCH_NAME = %s WHERE BRANCH_ID = %s",
                (branch_code, branch_name, branch_id),
            )

    def archive_department(self, branch_id, is_archived):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE branch_detail SET is_archived = %s WHERE BRANCH_ID = %s",
                (1 if is_archived else 0, branch_id),
            )

    def get_department(self, branch_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT BRANCH_ID, BRANCH_CODE, BRANCH_NAME, CAST(ORG_ID AS CHAR) AS org_id FROM branch_detail WHERE BRANCH_ID = %s",
                (branch_id,),
            )
            return cursor.fetchone()

    def get_department_by_code(self, branch_code, org_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT BRANCH_ID, BRANCH_CODE, BRANCH_NAME, CAST(ORG_ID AS CHAR) AS org_id FROM branch_detail WHERE LOWER(BRANCH_CODE) = LOWER(%s) AND CAST(ORG_ID AS CHAR) = %s LIMIT 1",
                (branch_code, org_id),
            )
            return cursor.fetchone()

