"""Normalize numeric department values in helpdesk_users to standard department codes."""

BRANCH_ID_TO_DEPT = {
    "1": "EEE",
    "2": "ME",
    "3": "ECE",
    "4": "CSE",
    "5": "IT",
    "6": "Bio-Tech",
    "7": "S&H",
    "8": "MCA",
    "9": "ECM",
    "10": "S&H",
    "11": "MBA",
    "12": "S&H",
    "13": "CDC",
    "14": "EPE",
    "15": "EPE",
    "16": "DSCE",
    "17": "VLSI",
    "18": "Administration",
    "19": "Software Engineering",
    "20": "CAD/CAM",
    "21": "Bio-Tech",
    "22": "MCA",
    "23": "Thermal Engineering",
    "24": "Computer Science",
    "25": "Administration",
    "26": "Marketing",
    "27": "Administration",
    "28": "Administration",
    "29": "Administration",
    "30": "Library",
    "31": "EDC",
    "32": "TDTC",
    "33": "Accounts",
    "34": "CDC",
    "35": "Facilities",
    "36": "Administration",
    "37": "Nano Tech",
    "38": "CNIS",
    "39": "ICT",
    "40": "Accounts",
    "41": "Exam",
    "42": "CSE",
    "43": "Health Center",
    "44": "Electrical",
    "45": "HR",
    "46": "Estate",
    "47": "Stores",
    "48": "CDC",
    "49": "Training",
    "50": "Marketing",
    "51": "Stores",
    "52": "1Sports",
    "53": "SAP",
    "54": "Security",
    "55": "Administration",
    "56": "Administration",
    "57": "Electrical",
    "58": "CSE-AIML",
    "59": "IOT",
    "60": "Cyber Security",
    "61": "Administration",
    "62": "1Sports",
    "63": "Library",
    "64": "Training",
    "65": "Civil Engineering",
    "66": "Civil Engineering",
    "67": "AIML",
    "68": "Data Science",
    "69": "Security",
    "70": "Estate",
    "71": "Operations",
    "72": "1Sports",
    "73": "Admissions",
    "74": "Physical Education",
    "75": "Administration",
    "700": "Facilities",
    "701": "SAP",
}

def normalize_user_departments(demo_db):
    total_updated = 0
    with demo_db.connection() as conn, conn.cursor() as cur:
        for branch_id, dept_code in BRANCH_ID_TO_DEPT.items():
            cur.execute(
                "UPDATE helpdesk_users SET department = %s WHERE department = %s",
                (dept_code, branch_id)
            )
            if cur.rowcount > 0:
                print(f"Updated {cur.rowcount} users from department '{branch_id}' -> '{dept_code}'")
                total_updated += cur.rowcount
    print(f"Total normalized users: {total_updated}")
    return total_updated

if __name__ == "__main__":
    from app import create_app, get_demo_db
    app = create_app()
    db = get_demo_db()
    normalize_user_departments(db)
