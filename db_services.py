from __future__ import annotations

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


class BaseMySQLService:
    def __init__(self, config: DbConfig | None):
        self.config = config

    @property
    def enabled(self) -> bool:
        return self.config is not None and pymysql is not None

    def connection(self):
        if not self.enabled:
            raise RuntimeError("MySQL is not configured.")
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )


class LiveDbService(BaseMySQLService):
    def fetch_departments(self):
        if not self.enabled:
            return []
        sql = """
            SELECT DISTINCT
                b.BRANCH_CODE AS department_code,
                b.BRANCH_NAME AS department_name,
                CAST(b.ORG_ID AS CHAR) AS org_id,
                b.HOD_ID
            FROM branch_detail b
            WHERE COALESCE(b.BRANCH_CODE, '') <> ''
            ORDER BY b.BRANCH_CODE
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

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

    def fetch_reference_users(self, search="", department=None, limit=100):
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
            return "2000"
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
        return "2000"


class DemoDbService(BaseMySQLService):
    def ensure_schema(self, schema_path: Path):
        if not self.enabled:
            return
        sql = schema_path.read_text(encoding="utf-8")
        statements = [statement.strip() for statement in sql.split(";") if statement.strip()]
        with self.connection() as connection, connection.cursor() as cursor:
            for statement in statements:
                cursor.execute(statement)

    def seed_defaults(self, users, categories):
        if not self.enabled:
            return
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM demo_users")
            if cursor.fetchone()["total"] == 0:
                cursor.executemany(
                    """
                    INSERT INTO demo_users (name, email, password, role, department)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    [(u["name"], u["email"], generate_password_hash(u["password"]), u["role"], u["department"]) for u in users],
                )

            cursor.execute("SELECT COUNT(*) AS total FROM demo_categories")
            if cursor.fetchone()["total"] == 0 and categories:
                for category in categories:
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
                raise ValueError("Current password is incorrect.")
            hashed = generate_password_hash(new_password)
            cursor.execute("UPDATE demo_users SET password = %s WHERE id = %s", (hashed, user_id))

    def get_user(self, user_id):
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT id, name, email, role, department, created_at FROM demo_users WHERE id = %s", (user_id,))
            return cursor.fetchone()

    def list_users(self, role=None, department=None, search=""):
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
            sql += " AND department = %s"
            params.append(department)
        if search:
            like = f"%{search}%"
            sql += " AND (name LIKE %s OR email LIKE %s OR department LIKE %s)"
            params.extend([like, like, like])
        sql += " ORDER BY created_at DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

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
        with self.connection() as connection, connection.cursor() as cursor:
            if payload.get("password"):
                hashed = generate_password_hash(payload["password"])
                cursor.execute(
                    """
                    UPDATE demo_users
                    SET name = %s, email = %s, password = %s, role = %s, department = %s
                    WHERE id = %s
                    """,
                    (payload["name"], payload["email"], hashed, payload["role"], payload["department"], user_id),
                )
            else:
                cursor.execute(
                    """
                    UPDATE demo_users
                    SET name = %s, email = %s, role = %s, department = %s
                    WHERE id = %s
                    """,
                    (payload["name"], payload["email"], payload["role"], payload["department"], user_id),
                )

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

    def list_categories(self, department=None, search="", ca_id=None):
        sql = """
            SELECT c.id, c.category_name, c.department, c.assigned_ca_id, c.created_at,
                   u.name AS assigned_ca_name, u.email AS assigned_ca_email
            FROM demo_categories c
            INNER JOIN demo_users u ON u.id = c.assigned_ca_id
            WHERE 1=1
        """
        params = []
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        if ca_id:
            sql += " AND c.assigned_ca_id = %s"
            params.append(ca_id)
        if search:
            like = f"%{search}%"
            sql += " AND (c.category_name LIKE %s OR u.name LIKE %s)"
            params.extend([like, like])
        sql += " ORDER BY c.department, c.category_name"
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
                SELECT c.id, c.category_name, c.department, c.assigned_ca_id, u.name AS assigned_ca_name
                FROM demo_categories c
                INNER JOIN demo_users u ON u.id = c.assigned_ca_id
                WHERE c.id = %s
                """,
                (category_id,),
            )
            return cursor.fetchone()

    def create_ticket(self, title, description, category_id, created_by, org_id, location_id=None):
        category = self.get_category(category_id)
        if not category:
            raise ValueError("Selected category does not exist.")
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO demo_tickets (title, description, category_id, created_by, assigned_to, status, org_id, location_id)
                VALUES (%s, %s, %s, %s, %s, 'PENDING', %s, %s)
                """,
                (title, description, category_id, created_by, category["assigned_ca_id"], org_id, location_id),
            )
            ticket_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO demo_ticket_activity (ticket_id, action_by, from_status, to_status, remarks)
                VALUES (%s, %s, NULL, 'PENDING', %s)
                """,
                (ticket_id, created_by, "Ticket created"),
            )
            return ticket_id

    def ticket_query_base(self):
        return """
            SELECT
                t.id,
                t.title,
                t.description,
                t.status,
                t.org_id,
                t.location_id,
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

    def list_tickets(self, viewer, scope="all", filters=None):
        filters = filters or {}
        sql = self.ticket_query_base()
        params = []

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
        "IN_PROGRESS": {"RESOLVED"},
        "RESOLVED": set(),  # terminal state – no further transitions
    }

    def update_ticket_status(self, ticket_id, actor, status, remarks="", time_taken="", attachment_path=""):
        ticket = self.get_ticket(ticket_id)
        if not ticket:
            raise ValueError("Ticket not found.")

        # Permission: only the assigned CA (or SUPER_ADMIN) can update
        is_assigned_ca = actor["role"] == "CA" and ticket["assigned_to_email"].lower() == actor["email"].lower()
        is_super_admin = actor["role"] == "SUPER_ADMIN"
        if not is_assigned_ca and not is_super_admin:
            raise PermissionError("Only the assigned Concerned Authority can update this ticket.")

        # Enforce valid status transitions
        current_status = ticket["status"]
        allowed = self.ALLOWED_TRANSITIONS.get(current_status, set())
        if status not in allowed:
            raise ValueError(
                f"Cannot transition from {current_status} to {status}. "
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

    # ── Analytics ────────────────────────────────────────

    def ticket_stats_by_category(self, department=None):
        sql = """
            SELECT c.category_name, c.department,
                   COUNT(t.id) AS ticket_count,
                   SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved
            FROM demo_categories c
            LEFT JOIN demo_tickets t ON t.category_id = c.id
            WHERE 1=1
        """
        params = []
        if department:
            sql += " AND c.department = %s"
            params.append(department)
        sql += " GROUP BY c.id, c.category_name, c.department ORDER BY ticket_count DESC"
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def ticket_stats_by_department(self):
        sql = """
            SELECT c.department,
                   COUNT(t.id) AS ticket_count,
                   SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                   SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved
            FROM demo_categories c
            LEFT JOIN demo_tickets t ON t.category_id = c.id
            GROUP BY c.department
            ORDER BY ticket_count DESC
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()

    def dashboard_summary(self, viewer):
        sql = """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN t.status = 'PENDING' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN t.status = 'IN_PROGRESS' THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN t.status = 'RESOLVED' THEN 1 ELSE 0 END) AS resolved
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

        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def hod_overview(self):
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
            GROUP BY u.id, u.name, u.email, u.department
            ORDER BY u.department
        """
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(sql)
            return cursor.fetchall()
