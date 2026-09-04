"""
reseed_from_dumps.py
====================
Parse the two legacy SQL dump files, clean data, and properly insert/update
users in the helpdesk database with correct CA/HOD mappings and phone numbers.

Source files:
  - New Project 20260716 1511.sql  →  sys_administrators (20 CAs/admins) + sys_complaint (762 tickets)
  - New Project 20260803 1346.sql  →  teacher_info       (2,240 faculty/staff records)

Run inside Docker:
  docker exec -it snist_helpdesk-web-1 python scripts/reseed_from_dumps.py
"""

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from werkzeug.security import generate_password_hash
from db_services import DemoDbService, env_db_config

# ---------------------------------------------------------------------------
# BRANCH_ID → Department mapping (from app/helpers.py)
# ---------------------------------------------------------------------------
BRANCH_ID_TO_DEPT = {
    "1": "EEE", "2": "ME", "3": "ECE", "4": "CSE", "5": "IT", "6": "Bio-Tech",
    "7": "S&H", "8": "MCA", "9": "ECM", "10": "S&H", "11": "MBA", "12": "S&H",
    "13": "CDC", "14": "EPE", "15": "EPE", "16": "DSCE", "17": "VLSI", "18": "Administration",
    "19": "Software Engineering", "20": "CAD/CAM", "21": "Bio-Tech", "22": "MCA",
    "23": "Thermal Engineering", "24": "Computer Science", "25": "Administration",
    "26": "Marketing", "27": "Administration", "28": "Administration", "29": "Administration",
    "30": "Library", "31": "EDC", "32": "TDTC", "33": "Accounts", "34": "CDC",
    "35": "Facilities", "36": "Administration", "37": "Nano Tech", "38": "CNIS",
    "39": "ICT", "40": "Accounts", "41": "Exam", "42": "CSE", "43": "Health Center",
    "44": "Electrical", "45": "HR", "46": "Estate", "47": "Stores", "48": "CDC",
    "49": "Training", "50": "Marketing", "51": "Stores", "52": "1Sports", "53": "SAP",
    "54": "Security", "55": "Administration", "56": "Administration", "57": "Electrical",
    "58": "CSE-AIML", "59": "IOT", "60": "Cyber Security", "61": "Administration",
    "62": "1Sports", "63": "Library", "64": "Training", "65": "Civil Engineering",
    "66": "Civil Engineering", "67": "AIML", "68": "Data Science", "69": "Security",
    "70": "Estate", "71": "Operations", "72": "1Sports", "73": "Admissions",
    "74": "Physical Education", "75": "Administration", "700": "Facilities", "701": "SAP",
}

# Department normalization — fix common typos and aliases
DEPT_NORMALIZE = {
    "fecilities": "Facilities",
    "facilites": "Facilities",
}

# HOD designation patterns (case-insensitive matching)
HOD_DESIGNATIONS = {
    "professor & hod",
    "associate professor & hod",
    "associate professor & in charge hod",
    "assoc. professor in charge hod",
    "professor and hod",
    "professor in charge hod",
    "professor,  dirctor of soe  & incharge hod",
}

# sys_administrators ADMIN_ROLE → helpdesk role mapping
ADMIN_ROLE_MAP = {
    "super admin": "SUPER_ADMIN",
    "ict": "CA",
    "hcm": "CA",
    "mm": "CA",
    "pm": "CA",
    "fecilities": "CA",
}

# sys_administrators DEPARTMENT → helpdesk department mapping
ADMIN_DEPT_MAP = {
    "sap": "SAP",
    "ict": "ICT",
    "cto": "Administration",
    "hcm executive": "HCM",
    "mm executive": "MM",
    "transport incharge": "PM",
    "fecilities": "Facilities",
}


def clean_phone(raw) -> str | None:
    """Extract a valid 10-digit Indian mobile number from raw input."""
    if raw is None:
        return None
    # Convert float/int to string
    s = str(raw).strip()
    # Remove decimal points (from SQL double type)
    if "." in s:
        s = s.split(".")[0]
    # Remove non-digit chars
    digits = re.sub(r"\D", "", s)
    # Handle leading 91 country code
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    # Must be exactly 10 digits starting with 6-9
    if len(digits) == 10 and digits[0] in "6789":
        return digits
    return None


def normalize_dept(dept: str) -> str:
    """Normalize department name, fixing common typos."""
    if not dept:
        return "Administration"
    key = dept.strip().lower()
    return DEPT_NORMALIZE.get(key, dept.strip())


# ---------------------------------------------------------------------------
# 1. Parse sys_administrators from SQL file
# ---------------------------------------------------------------------------
def parse_sys_administrators(sql_path: Path) -> list[dict]:
    """Parse sys_administrators INSERT rows from the SQL dump."""
    content = sql_path.read_text(encoding="utf-8", errors="replace")

    # Find the INSERT INTO sys_administrators block
    pattern = re.compile(
        r"INSERT INTO `sys_administrators`.*?VALUES\s*(.*?);",
        re.DOTALL | re.IGNORECASE,
    )
    match = pattern.search(content)
    if not match:
        print("WARNING: Could not find sys_administrators INSERT block")
        return []

    values_block = match.group(1)
    # Match each row: ('TEACHER_ID','NAME','DEPARTMENT',MOBILE_NO,'ADMIN_ROLE','EMAIL_ID')
    row_pattern = re.compile(
        r"\(\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*'([^']*)'\s*,\s*([\d.]+)\s*,\s*'([^']*)'\s*,\s*(?:'([^']*)'|NULL)\s*\)"
    )

    users = []
    for m in row_pattern.finditer(values_block):
        teacher_id = m.group(1).strip()
        name = m.group(2).strip()
        department = m.group(3).strip()
        mobile_raw = m.group(4).strip()
        admin_role = m.group(5).strip()
        email = m.group(6)  # Can be None if NULL

        phone = clean_phone(mobile_raw)

        # Determine helpdesk role
        role_key = admin_role.lower().strip()
        if role_key in ADMIN_ROLE_MAP:
            role = ADMIN_ROLE_MAP[role_key]
        elif role_key == "" and department.lower() in ("ict",):
            role = "CA"
        elif role_key == "" and department.lower() in ("fecilities",):
            role = "CA"
        else:
            role = "CA"  # Default sys_administrators to CA

        # Determine helpdesk department
        dept_key = department.lower().strip()
        helpdesk_dept = ADMIN_DEPT_MAP.get(dept_key, normalize_dept(department))

        # If admin role is a department name, use it to override
        if role_key in ("ict", "hcm", "mm", "pm"):
            helpdesk_dept = role_key.upper()
        elif role_key == "fecilities":
            helpdesk_dept = "Facilities"

        user = {
            "teacher_id": teacher_id,
            "name": name,
            "email": email,
            "phone": phone,
            "role": role,
            "department": helpdesk_dept,
            "source": "sys_administrators",
        }
        users.append(user)

    return users


# ---------------------------------------------------------------------------
# 1b. Parse sys_complaint from SQL file
# ---------------------------------------------------------------------------

# DEVICE_TYPE normalization — strip trailing \r\n and fix known typos
DEVICE_TYPE_NORMALIZE = {
    "electrical issues (lights, outlets, fans)rn": "Electrical issues (lights, outlets, fans)",
    "electrical issues (lights, outlets, fans)\r\n": "Electrical issues (lights, outlets, fans)",
    "plumbing (leaks, water supply, washrooms)rn": "Plumbing (leaks, water supply, washrooms)",
    "plumbing (leaks, water supply, washrooms)\r\n": "Plumbing (leaks, water supply, washrooms)",
    "lost & found, safety concerns or incidentsrnr": "Lost & Found, Safety Concerns or Incidents",
    "lost & found, safety concerns or incidents\r\n\r": "Lost & Found, Safety Concerns or Incidents",
    "system": "Desktop",  # "System" maps to "Desktop" category
    "desktop instalation": "Desktop instalation",
}


def parse_sys_complaint(sql_path: Path) -> list[dict]:
    """Parse sys_complaint INSERT rows from the SQL dump.

    Fields: TICKET_ID, BLOCK, ROOMNO, DEVICE_TYPE, RAISED_BY,
            RAISED_DATATIME, RAISED_DESCRIPTION, PARENT_DEPARTMENT, DEPARTMENT
    """
    content = sql_path.read_text(encoding="utf-8", errors="replace")

    pattern = re.compile(
        r"INSERT INTO `sys_complaint`[^;]*?VALUES\s*(\(.+?\))\s*;",
        re.DOTALL | re.IGNORECASE,
    )
    all_matches = pattern.findall(content)
    if not all_matches:
        print("WARNING: Could not find sys_complaint INSERT block")
        return []

    print(f"    Found {len(all_matches)} INSERT blocks in sys_complaint SQL")

    tickets = []
    all_rows = []
    for block in all_matches:
        rows = re.split(r"\)\s*,\s*\(", block)
        all_rows.extend(rows)

    for raw_row in all_rows:
        raw_row = raw_row.strip().lstrip("(").rstrip(")")
        fields = parse_sql_row(raw_row)

        if len(fields) < 9:
            continue

        ticket_id = fields[0]
        block = (fields[1] or "").strip()
        room_no = (fields[2] or "").strip()
        device_type = (fields[3] or "").strip().rstrip("\r\n")
        raised_by = (fields[4] or "").strip()
        raised_dt = (fields[5] or "").strip()
        description = (fields[6] or "").strip().rstrip("\r\n")
        parent_dept = (fields[7] or "").strip()
        department = (fields[8] or "").strip()

        # Skip empty/invalid rows
        if not block and not raised_by:
            continue
        if raised_dt == "0000-00-00 00:00:00":
            continue

        # Normalize device_type
        dt_key = device_type.lower().strip()
        device_type = DEVICE_TYPE_NORMALIZE.get(dt_key, device_type)

        # Normalize department
        department = normalize_dept(department) if department else "ICT"

        # Clean description
        if description:
            description = description.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not description:
            description = f"{device_type} issue in {block} {room_no}".strip()

        tickets.append({
            "original_id": ticket_id,
            "block": block,
            "room_no": room_no,
            "device_type": device_type,
            "raised_by_code": raised_by.upper(),
            "raised_datetime": raised_dt,
            "description": description,
            "parent_dept_id": parent_dept,
            "department": department,
        })

    return tickets


# ---------------------------------------------------------------------------
# 2. Parse teacher_info from SQL file
# ---------------------------------------------------------------------------
def parse_teacher_info(sql_path: Path) -> list[dict]:
    """Parse teacher_info INSERT rows from the SQL dump.

    Fields order in INSERT:
    TEACHER_ID, TEACHER_NAME, DATE_OF_BIRTH, GENDER, DESIGNATION, EMP_TYPE,
    FROM_DATE, TO_DATE, QUALIFICATION, COLLEGE, EMAIL_ID, ADDRESS, PIN_CODE,
    OFFICE_PHN, RES_PHONE, MOBILE_PHONE, ACTIVE, SALUTATION, TYPE_OF_JOB,
    SAP_ID, TEACHER_CODE, BRANCH_ID, MARITAL_STATUS, ...
    """
    content = sql_path.read_text(encoding="utf-8", errors="replace")

    # The SQL dump contains MULTIPLE INSERT INTO teacher_info blocks (14 total).
    # We must find ALL of them and concatenate the row tuples.
    # Strategy: find each "INSERT INTO `teacher_info` ... VALUES" and capture
    # everything up to the closing ";", then split rows from each block.
    pattern = re.compile(
        r"INSERT INTO `teacher_info`[^;]*?VALUES\s*(\(.+?\))\s*;",
        re.DOTALL | re.IGNORECASE,
    )
    all_matches = pattern.findall(content)
    if not all_matches:
        print("WARNING: Could not find teacher_info INSERT block")
        return []

    print(f"    Found {len(all_matches)} INSERT blocks in teacher_info SQL")

    # Concatenate all VALUES blocks and split into individual rows
    users = []
    rows = []
    for values_block in all_matches:
        block_rows = re.split(r"\)\s*,\s*\(", values_block)
        rows.extend(block_rows)

    for i, row in enumerate(rows):
        # Clean leading/trailing parens
        row = row.strip()
        if row.startswith("("):
            row = row[1:]
        if row.endswith(")"):
            row = row[:-1]

        # Parse fields using a CSV-like approach
        fields = parse_sql_row(row)
        if len(fields) < 22:
            continue

        teacher_id = fields[0]
        teacher_name = fields[1]
        designation = fields[4]
        email = fields[10]
        mobile_phone = fields[15]
        branch_id = fields[21]

        # Clean email
        if email:
            email = email.strip()
            if not email or "@" not in email:
                email = None

        if not email:
            continue

        # Clean phone
        phone = clean_phone(mobile_phone)

        # Determine department from branch_id
        branch_str = str(branch_id).strip() if branch_id else "0"
        department = BRANCH_ID_TO_DEPT.get(branch_str, "Administration")
        department = normalize_dept(department)

        # Determine role — check if HOD
        role = "FACULTY"
        if designation:
            desig_lower = designation.strip().lower()
            for hod_pattern in HOD_DESIGNATIONS:
                if hod_pattern in desig_lower:
                    role = "HOD"
                    break

        user = {
            "teacher_id": teacher_id,
            "name": teacher_name.strip() if teacher_name else "Unknown",
            "email": email,
            "phone": phone,
            "role": role,
            "department": department,
            "designation": designation,
            "branch_id": branch_str,
            "source": "teacher_info",
        }
        users.append(user)

    return users


def parse_sql_row(row_str: str) -> list[str | None]:
    """Parse a single SQL INSERT row into a list of field values.
    Handles quoted strings, hex blobs, NULL, and numeric values."""
    fields = []
    i = 0
    s = row_str

    while i < len(s):
        # Skip whitespace and commas
        while i < len(s) and s[i] in (" ", "\t", "\r", "\n"):
            i += 1
        if i >= len(s):
            break

        if s[i] == ",":
            i += 1
            continue

        # NULL
        if s[i:i+4].upper() == "NULL":
            fields.append(None)
            i += 4
            continue

        # Hex blob (0x...)
        if s[i:i+2] == "0x":
            j = i + 2
            while j < len(s) and s[j] in "0123456789abcdefABCDEF":
                j += 1
            hex_str = s[i+2:j]
            try:
                fields.append(bytes.fromhex(hex_str).decode("utf-8", errors="replace"))
            except Exception:
                fields.append("")
            i = j
            continue

        # Quoted string
        if s[i] == "'":
            j = i + 1
            value = []
            while j < len(s):
                if s[j] == "\\" and j + 1 < len(s):
                    value.append(s[j+1])
                    j += 2
                elif s[j] == "'" and j + 1 < len(s) and s[j+1] == "'":
                    value.append("'")
                    j += 2
                elif s[j] == "'":
                    break
                else:
                    value.append(s[j])
                    j += 1
            fields.append("".join(value))
            i = j + 1
            continue

        # Numeric value
        j = i
        while j < len(s) and s[j] not in (",", ")", " "):
            j += 1
        val = s[i:j].strip()
        fields.append(val)
        i = j

    return fields


# ---------------------------------------------------------------------------
# 3. Main: Merge and insert into the database
# ---------------------------------------------------------------------------
def main():
    config = env_db_config()
    if not config:
        raise SystemExit("MYSQL_* environment variables are required.")

    demo_db = DemoDbService(config)
    if not demo_db.enabled:
        raise SystemExit("Cannot connect to database.")

    # Ensure schema exists
    schema_path = ROOT / "sql" / "demo_schema.sql"
    demo_db.ensure_schema(schema_path)

    # File paths
    sys_admin_sql = ROOT / "New Project 20260716 1511.sql"
    teacher_info_sql = ROOT / "New Project 20260803 1346.sql"

    if not sys_admin_sql.exists():
        raise SystemExit(f"File not found: {sys_admin_sql}")
    if not teacher_info_sql.exists():
        raise SystemExit(f"File not found: {teacher_info_sql}")

    # Parse source files
    print("=" * 70)
    print("PHASE 1: Parsing SQL dump files")
    print("=" * 70)

    admin_users = parse_sys_administrators(sys_admin_sql)
    print(f"  sys_administrators: {len(admin_users)} records parsed")

    teacher_users = parse_teacher_info(teacher_info_sql)
    print(f"  teacher_info:       {len(teacher_users)} records parsed")

    # Merge: admins first (higher priority roles), then teachers
    # Track by email (case-insensitive) to avoid duplicates
    seen_emails: dict[str, dict] = {}
    merged_users: list[dict] = []

    # Insert sys_administrators first (they have CA/ADMIN roles)
    for u in admin_users:
        if not u["email"]:
            print(f"  SKIP (no email): {u['name']} ({u['teacher_id']})")
            continue
        key = u["email"].lower().strip()
        if key not in seen_emails:
            seen_emails[key] = u
            merged_users.append(u)

    # Then teachers — skip if email already exists, but update phone if needed
    for u in teacher_users:
        key = u["email"].lower().strip()
        if key in seen_emails:
            # Update phone if existing record has no phone
            existing = seen_emails[key]
            if not existing.get("phone") and u.get("phone"):
                existing["phone"] = u["phone"]
            # If teacher is HOD but existing is FACULTY, upgrade to HOD
            if u["role"] == "HOD" and existing["role"] == "FACULTY":
                existing["role"] = "HOD"
                existing["department"] = u["department"]
        else:
            seen_emails[key] = u
            merged_users.append(u)

    print(f"\n  Total unique users to seed: {len(merged_users)}")

    # Count by role
    role_counts = {}
    for u in merged_users:
        role_counts[u["role"]] = role_counts.get(u["role"], 0) + 1
    for role, count in sorted(role_counts.items()):
        print(f"    {role}: {count}")

    # Count phone coverage
    with_phone = sum(1 for u in merged_users if u.get("phone"))
    print(f"\n  Users with valid phone: {with_phone}/{len(merged_users)}")

    # HOD records
    hods = [u for u in merged_users if u["role"] == "HOD"]
    print(f"\n  HODs identified: {len(hods)}")
    for h in hods:
        print(f"    {h['name'][:45]:<47} | {h['department']:<20} | {h['email']}")

    # ---------------------------------------------------------------------------
    # PHASE 2: Insert/Update in database
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 2: Inserting/Updating users in helpdesk_users")
    print("=" * 70)

    inserted = 0
    updated = 0
    skipped = 0
    default_password_hash = generate_password_hash("123")

    with demo_db.connection() as conn, conn.cursor() as cur:
        for u in merged_users:
            email = u["email"].strip()
            # Check if user already exists
            cur.execute("SELECT id, role, phone, department FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
            existing = cur.fetchone()

            if existing:
                # Update phone if missing and we have one
                updates = []
                params = []
                if u.get("phone") and not existing.get("phone"):
                    updates.append("phone = %s")
                    params.append(u["phone"])
                # Upgrade role: FACULTY -> HOD, FACULTY -> CA, etc.
                # Only upgrade, never downgrade
                role_priority = {"FACULTY": 0, "HOD": 1, "CA": 2, "ASSIGNEE": 2, "ADMIN": 3, "SUPER_ADMIN": 4}
                existing_priority = role_priority.get(existing["role"], 0)
                new_priority = role_priority.get(u["role"], 0)
                if new_priority > existing_priority:
                    updates.append("role = %s")
                    params.append(u["role"])
                    updates.append("department = %s")
                    params.append(u["department"])

                if updates:
                    params.append(existing["id"])
                    cur.execute(
                        f"UPDATE helpdesk_users SET {', '.join(updates)} WHERE id = %s",
                        tuple(params),
                    )
                    updated += 1
                else:
                    skipped += 1
            else:
                # Insert new user
                cur.execute(
                    """
                    INSERT INTO helpdesk_users (name, email, password, role, department, phone)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (u["name"], email, default_password_hash, u["role"], u["department"], u.get("phone")),
                )
                inserted += 1

    print(f"  Inserted: {inserted}")
    print(f"  Updated:  {updated}")
    print(f"  Skipped:  {skipped}")

    # ---------------------------------------------------------------------------
    # PHASE 3: Ensure departments exist in branch_detail
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 3: Ensuring departments exist in branch_detail")
    print("=" * 70)

    # Collect all unique departments from merged users
    all_depts = sorted(set(u["department"] for u in merged_users if u["department"]))

    with demo_db.connection() as conn, conn.cursor() as cur:
        dept_inserted = 0
        for dept in all_depts:
            cur.execute("SELECT BRANCH_ID FROM branch_detail WHERE BRANCH_CODE = %s LIMIT 1", (dept,))
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO branch_detail (BRANCH_CODE, BRANCH_NAME, ORG_ID) VALUES (%s, %s, %s)",
                    (dept, dept, "2000"),
                )
                dept_inserted += 1
                print(f"  Added department: {dept}")

    print(f"  New departments added: {dept_inserted}")

    # ---------------------------------------------------------------------------
    # PHASE 4: Map HODs to branch_detail
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 4: Mapping HODs to branch_detail.HOD_ID")
    print("=" * 70)

    with demo_db.connection() as conn, conn.cursor() as cur:
        hod_mapped = 0
        for h in hods:
            # Get the user id from helpdesk_users
            cur.execute("SELECT id FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (h["email"],))
            user_row = cur.fetchone()
            if not user_row:
                print(f"  WARNING: HOD user not found: {h['email']}")
                continue

            user_id = user_row["id"]
            dept = h["department"]

            # Find the branch_detail row for this department
            cur.execute("SELECT BRANCH_ID, HOD_ID FROM branch_detail WHERE BRANCH_CODE = %s LIMIT 1", (dept,))
            branch_row = cur.fetchone()
            if not branch_row:
                print(f"  WARNING: Department not found in branch_detail: {dept}")
                continue

            if branch_row.get("HOD_ID") != user_id:
                cur.execute("UPDATE branch_detail SET HOD_ID = %s WHERE BRANCH_ID = %s", (user_id, branch_row["BRANCH_ID"]))
                hod_mapped += 1
                print(f"  Mapped HOD: {h['name'][:40]} -> {dept} (user_id={user_id})")

    print(f"  HODs mapped: {hod_mapped}")

    # ---------------------------------------------------------------------------
    # PHASE 5: Verify & fix CA assignments in helpdesk_categories
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 5: Verifying CA assignments in helpdesk_categories")
    print("=" * 70)

    with demo_db.connection() as conn, conn.cursor() as cur:
        # Get all categories
        cur.execute("SELECT id, category_name, department, assigned_ca_id, is_active FROM helpdesk_categories")
        categories = cur.fetchall()

        fixed_cats = 0
        for cat in categories:
            ca_id = cat.get("assigned_ca_id")
            dept = cat["department"]

            # Check if assigned CA exists and is a CA in the same department
            valid = False
            if ca_id:
                cur.execute(
                    "SELECT id, role, department FROM helpdesk_users WHERE id = %s LIMIT 1",
                    (ca_id,)
                )
                ca_user = cur.fetchone()
                if ca_user and ca_user["role"] in ("CA", "ASSIGNEE") and ca_user["department"].lower() == dept.lower():
                    valid = True

            if not valid:
                # Find a valid CA for this department
                norm_dept = normalize_dept(dept)
                cur.execute(
                    """
                    SELECT id FROM helpdesk_users
                    WHERE role IN ('CA', 'ASSIGNEE')
                      AND (LOWER(department) = LOWER(%s) OR LOWER(department) = LOWER(%s))
                    ORDER BY id ASC LIMIT 1
                    """,
                    (dept, norm_dept),
                )
                new_ca = cur.fetchone()
                if new_ca:
                    cur.execute(
                        "UPDATE helpdesk_categories SET assigned_ca_id = %s WHERE id = %s",
                        (new_ca["id"], cat["id"]),
                    )
                    fixed_cats += 1
                    print(f"  Fixed: '{cat['category_name']}' ({dept}) -> CA user_id={new_ca['id']}")
                else:
                    print(f"  WARNING: No CA found for category '{cat['category_name']}' ({dept})")

    print(f"  Categories fixed: {fixed_cats}")

    # ---------------------------------------------------------------------------
    # PHASE 6: Seed historical tickets from sys_complaint
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 6: Seeding historical tickets from sys_complaint")
    print("=" * 70)

    complaint_tickets = parse_sys_complaint(sys_admin_sql)
    print(f"  Parsed {len(complaint_tickets)} valid tickets from sys_complaint")

    with demo_db.connection() as conn, conn.cursor() as cur:
        # Build teacher_code -> helpdesk_users.id lookup
        # First from teacher_info SQL (TEACHER_CODE field)
        teacher_code_to_user: dict[str, int] = {}

        # Get all users and their teacher codes from helpdesk_users
        # We need to match TEACHER_CODE from teacher_info to emails in helpdesk_users
        # Build from the parsed teacher_info data
        for u in teacher_users:
            tc = u.get("teacher_id")
            if tc and u.get("email"):
                # Also store the TEACHER_CODE (field index 20 in teacher_info)
                # teacher_id in our parsed data is actually TEACHER_ID (auto-increment),
                # but we stored it. We need TEACHER_CODE which we didn't store.
                pass

        # Better approach: look up teacher_code directly from the SQL data
        # Parse teacher_info to get TEACHER_CODE -> EMAIL mapping
        teacher_info_content = teacher_info_sql.read_text(encoding="utf-8", errors="replace")
        ti_pattern = re.compile(
            r"INSERT INTO `teacher_info`[^;]*?VALUES\s*(\(.+?\))\s*;",
            re.DOTALL | re.IGNORECASE,
        )
        ti_matches = ti_pattern.findall(teacher_info_content)
        teacher_code_to_email: dict[str, str] = {}
        for block in ti_matches:
            for raw_row in re.split(r"\)\s*,\s*\(", block):
                raw_row = raw_row.strip().lstrip("(").rstrip(")")
                fields = parse_sql_row(raw_row)
                if len(fields) >= 21:
                    email = (fields[10] or "").strip()
                    teacher_code = (fields[20] or "").strip().upper()
                    if teacher_code and email and "@" in email:
                        teacher_code_to_email[teacher_code] = email

        # Also add sys_administrators teacher_id -> email
        for u in admin_users:
            tc = u.get("teacher_id", "").upper().strip()
            if tc and u.get("email"):
                teacher_code_to_email[tc] = u["email"]

        print(f"  Built teacher_code->email map: {len(teacher_code_to_email)} entries")

        # Now resolve teacher_code -> helpdesk_users.id via email
        for code, email in teacher_code_to_email.items():
            cur.execute("SELECT id FROM helpdesk_users WHERE LOWER(email) = LOWER(%s) LIMIT 1", (email,))
            row = cur.fetchone()
            if row:
                teacher_code_to_user[code] = row["id"]

        print(f"  Resolved teacher_code->user_id: {len(teacher_code_to_user)} entries")

        # Build category lookup: (category_name, department) -> category_id
        cur.execute("SELECT id, category_name, department, assigned_ca_id FROM helpdesk_categories")
        all_cats = cur.fetchall()
        cat_lookup: dict[tuple[str, str], dict] = {}
        for c in all_cats:
            key = (c["category_name"].lower().strip(), c["department"].lower().strip())
            cat_lookup[key] = c
            # Also index by category_name alone for cross-department fallback
            name_key = (c["category_name"].lower().strip(), "")
            if name_key not in cat_lookup:
                cat_lookup[name_key] = c

        # Build location lookup: (block, room_no) -> location_id
        cur.execute("SELECT id, block, room_no FROM location")
        all_locs = cur.fetchall()
        loc_lookup: dict[tuple[str, str], int] = {}
        for loc in all_locs:
            loc_lookup[((loc["block"] or "").lower(), (loc["room_no"] or "").lower())] = loc["id"]

        # Get a fallback user for tickets where raised_by can't be resolved
        cur.execute("SELECT id FROM helpdesk_users WHERE role = 'SUPER_ADMIN' ORDER BY id ASC LIMIT 1")
        fallback_user = cur.fetchone()
        fallback_user_id = fallback_user["id"] if fallback_user else 1

        # Insert tickets
        tickets_inserted = 0
        tickets_skipped = 0
        locations_created = 0
        categories_created = 0
        unresolved_users = set()

        for t in complaint_tickets:
            # Resolve created_by user
            raised_code = t["raised_by_code"]
            created_by_id = teacher_code_to_user.get(raised_code)
            if not created_by_id:
                unresolved_users.add(raised_code)
                created_by_id = fallback_user_id

            # Resolve category
            dept = t["department"]
            device = t["device_type"]
            cat_key = (device.lower().strip(), dept.lower().strip())
            cat_row = cat_lookup.get(cat_key)
            if not cat_row:
                # Try cross-department fallback
                cat_row = cat_lookup.get((device.lower().strip(), ""))
            if not cat_row:
                # Try with "Fecilities" spelling
                cat_row = cat_lookup.get((device.lower().strip(), "fecilities"))
            if not cat_row and device:
                # Create the category
                # Find a CA for this department
                norm_dept = normalize_dept(dept)
                cur.execute(
                    """SELECT id FROM helpdesk_users
                       WHERE role IN ('CA','ASSIGNEE')
                         AND (LOWER(department) = LOWER(%s) OR LOWER(department) = LOWER(%s))
                       ORDER BY id ASC LIMIT 1""",
                    (dept, norm_dept),
                )
                ca_row = cur.fetchone()
                ca_id = ca_row["id"] if ca_row else fallback_user_id
                try:
                    cur.execute(
                        "INSERT INTO helpdesk_categories (category_name, department, assigned_ca_id) VALUES (%s, %s, %s)",
                        (device, dept, ca_id),
                    )
                    new_cat_id = cur.lastrowid
                    cat_row = {"id": new_cat_id, "category_name": device, "department": dept, "assigned_ca_id": ca_id}
                    cat_lookup[cat_key] = cat_row
                    categories_created += 1
                    print(f"  Created category: '{device}' ({dept})")
                except Exception as e:
                    print(f"  WARNING: Could not create category '{device}' ({dept}): {e}")
                    continue

            if not cat_row:
                # Use 'Others' in the same department as fallback
                cat_row = cat_lookup.get(("others", dept.lower().strip()))
            if not cat_row:
                cat_row = cat_lookup.get(("others", "ict"))
            if not cat_row:
                tickets_skipped += 1
                continue

            category_id = cat_row["id"]
            assigned_to = cat_row.get("assigned_ca_id") or fallback_user_id

            # Resolve or create location
            block = t["block"]
            room_no = t["room_no"]
            loc_key = (block.lower(), room_no.lower())
            location_id = loc_lookup.get(loc_key)
            if not location_id and block:
                # Create location
                try:
                    cur.execute(
                        "INSERT INTO location (block, floor, room_no, name, ORG_ID) VALUES (%s, %s, %s, %s, %s)",
                        (block, "Unknown", room_no or "N/A", f"{block} {room_no}".strip(), "2000"),
                    )
                    location_id = cur.lastrowid
                    loc_lookup[loc_key] = location_id
                    locations_created += 1
                except Exception:
                    location_id = None

            # Build title from device_type + block
            title = f"{device} - {block} {room_no}".strip() if device else f"Issue in {block} {room_no}".strip()
            if len(title) > 180:
                title = title[:177] + "..."

            description = t["description"]
            if len(description) > 60000:
                description = description[:60000]

            # Check for duplicate (same original description + created_by + category)
            # Use a submission_key based on original ticket ID
            submission_key = f"legacy-complaint-{t['original_id']}"
            cur.execute("SELECT id FROM helpdesk_tickets WHERE submission_key = %s LIMIT 1", (submission_key,))
            if cur.fetchone():
                tickets_skipped += 1
                continue

            # Insert ticket as RESOLVED (historical)
            try:
                cur.execute(
                    """
                    INSERT INTO helpdesk_tickets
                        (title, description, category_id, created_by, assigned_to,
                         status, org_id, location_id, submission_key, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, 'RESOLVED', '2000', %s, %s, %s, %s)
                    """,
                    (title, description, category_id, created_by_id, assigned_to,
                     location_id, submission_key, t["raised_datetime"], t["raised_datetime"]),
                )
                tickets_inserted += 1
            except Exception as e:
                print(f"  WARNING: Could not insert ticket #{t['original_id']}: {e}")
                tickets_skipped += 1

    print(f"\n  Tickets inserted:    {tickets_inserted}")
    print(f"  Tickets skipped:     {tickets_skipped}")
    print(f"  Locations created:   {locations_created}")
    print(f"  Categories created:  {categories_created}")
    if unresolved_users:
        print(f"  Unresolved teacher codes ({len(unresolved_users)}): {', '.join(sorted(unresolved_users))}")

    # ---------------------------------------------------------------------------
    # PHASE 7: Summary report
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("PHASE 7: Final Summary")
    print("=" * 70)

    with demo_db.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM helpdesk_users")
        total_users = cur.fetchone()["cnt"]

        cur.execute("SELECT role, COUNT(*) AS cnt FROM helpdesk_users GROUP BY role ORDER BY role")
        role_dist = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS cnt FROM helpdesk_users WHERE phone IS NOT NULL AND phone != ''")
        phone_count = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM helpdesk_categories")
        total_cats = cur.fetchone()["cnt"]

        cur.execute("""
            SELECT COUNT(*) AS cnt FROM helpdesk_categories c
            JOIN helpdesk_users u ON c.assigned_ca_id = u.id
            WHERE u.role IN ('CA', 'ASSIGNEE')
        """)
        valid_ca_cats = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM branch_detail WHERE HOD_ID IS NOT NULL")
        hod_depts = cur.fetchone()["cnt"]

        cur.execute("SELECT COUNT(*) AS cnt FROM helpdesk_tickets")
        total_tickets = cur.fetchone()["cnt"]

        cur.execute("SELECT status, COUNT(*) AS cnt FROM helpdesk_tickets GROUP BY status ORDER BY status")
        ticket_dist = cur.fetchall()

        cur.execute("SELECT COUNT(*) AS cnt FROM location")
        total_locs = cur.fetchone()["cnt"]

    print(f"\n  Total users:          {total_users}")
    print(f"  Role distribution:")
    for r in role_dist:
        print(f"    {r['role']}: {r['cnt']}")
    print(f"  Users with phone:     {phone_count}/{total_users}")
    print(f"  Categories (valid CA): {valid_ca_cats}/{total_cats}")
    print(f"  Departments with HOD: {hod_depts}")
    print(f"  Total tickets:        {total_tickets}")
    print(f"  Ticket status distribution:")
    for t in ticket_dist:
        print(f"    {t['status']}: {t['cnt']}")
    print(f"  Total locations:      {total_locs}")
    print(f"\n  Done! Database re-seed complete!")


if __name__ == "__main__":
    main()
