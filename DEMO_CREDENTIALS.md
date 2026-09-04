# SNIST Help Desk — Live Demo Guide & Credentials

This guide contains verified credentials, demo roles, portal URLs, and a step-by-step walkthrough to present a live demonstration of the SNIST Help Desk system.

---

## 1. Quick Access URLs

| Service | Local URL | Port Forward / Alternative |
| :--- | :--- | :--- |
| **Help Desk Web App** | [http://localhost:5000](http://localhost:5000) | [http://localhost:5001](http://localhost:5001) |
| **Login Page** | [http://localhost:5000/login](http://localhost:5000/login) | [http://localhost:5001/login](http://localhost:5001/login) |
| **Metabase Visual Analytics** | [http://localhost:3002](http://localhost:3002) | (Admin: `admin@gmail.com` / `Admin@321#`) |

---

## 2. Demo Accounts by Role

### A. Super Admin & Campus Admin (Full System Governance)
Full system configuration, category management, cross-department ticket tracking, audit logs, and Metabase analytics.

| Role | Email | Password | Name | Department | Target Dashboard |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SUPER_ADMIN** | `admin@gmail.com` | `Admin@321#` | Super Admin | Administration | `/super-admin/dashboard` |
| **ADMIN** | `campus.admin@gmail.com` | `Admin@321#` | Campus Admin | Administration | `/admin/dashboard` |
| **SUPER_ADMIN (CTO)** | `cto@sreenidhi.edu.in` | `Admin@321#` | CTO Admin | CTO | `/super-admin/dashboard` |
| **SUPER_ADMIN (SAP)** | `srinivas.n@sreenidhi.edu.in` | `Admin@321#` | Srinivas SAP | SAP | `/super-admin/dashboard` |

---

### B. Concerned Authority / Assignee (CA)
Assigned tickets queue, status mutation (**Pending** $\rightarrow$ **In Progress** $\rightarrow$ **Resolved**), internal resolution notes.

| Role | Email | Password | Name | Department | Target Dashboard |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CA (ICT)** | `managerict@sreenidhi.edu.in` | `Admin@321#` | ICT Manager | ICT | `/authority/tickets` |
| **CA (Facilities)** | `managerfs@sreenidhi.edu.in` | `Admin@321#` | Facilities Manager | Facilities | `/authority/tickets` |
| **CA (HCM)** | `ramkumar.b@sreenidhi.edu.in` | `Admin@321#` | HCM Executive | HCM | `/authority/tickets` |
| **CA (MM)** | `chakradhar.n@sreenidhi.edu.in` | `Admin@321#` | MM Executive | MM | `/authority/tickets` |

---

### C. Head of Department (HOD)
Department ticket oversight, department CA performance, and selective ticket reassignment across department CAs. Authenticates directly against `teacher_info` with dynamically resolved HOD privileges.

| Role | Email | Password | Name | Department | Target Dashboard |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **HOD (CSE)** | `shirisha.k@sreenidhi.edu.in` | `123` *(or SAP ID: `10000108`)* | Dr. Kakarla Shirisha | CSE | `/hod/dashboard` |
| **HOD (IT)** | `sunil.b@sreenidhi.edu.in` | `123` *(or SAP ID: `10000072`)* | Dr. Bhutada Sunil | IT | `/hod/dashboard` |
| **HOD (DS)** | `jaffar.m@sreenidhi.edu.in` | `123` *(or SAP ID: `10000071`)* | Dr. Mohammad Jaffar Sadiq | Data Science | `/hod/dashboard` |
| **HOD (EEE)** | `bhargava.c@sreenidhi.edu.in` | `123` *(or SAP ID: `10000120`)* | Dr. Chitumodhu Bhargava | EEE | `/hod/dashboard` |

---

### D. Faculty / Standard Campus User
User self-service portal, Create Ticket (`/tickets/create`), and personal ticket tracking (`/my-tickets`). Authenticates directly against institutional `teacher_info` master.

| Role | Email | Password | Name | Department | Target Dashboard |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FACULTY (CSE)** | `aruna.v@sreenidhi.edu.in` | `123` *(or SAP ID: `10000084`)* | Varanasi Aruna | CSE | `/user/dashboard` |
| **FACULTY (CSE)** | `damodhar.k@sreenidhi.edu.in` | `123` *(or SAP ID: `10000058`)* | Kandula Damodhar Rao | CSE | `/user/dashboard` |
| **FACULTY (CSE)** | `subbareddy.n@sreenidhi.edu.in` | `123` *(or SAP ID: `10000049`)* | Nallapu Venkata Subba Reddy | CSE | `/user/dashboard` |

---

## 3. Recommended 5-Minute Demo Flow

### Step 1: Faculty User Raises a Ticket (2 minutes)
1. Navigate to `http://localhost:5000/login`.
2. Sign in as CSE Faculty:
   - **Email**: `aruna.v@sreenidhi.edu.in`
   - **Password**: `123`
3. Click **"Create Ticket"**:
   - Choose Department: `ICT`
   - Category: `Internet & Wi-Fi`
   - Location: Select Block and Room
   - Enter Title: *"Lab Switch Port Failure in Room 204"*
   - Click **Submit Ticket**.
4. Show that the ticket appears on the **My Tickets** screen as **Pending**.
5. Click **Logout**.

### Step 2: Concerned Authority (CA) Resolves the Ticket (1 minute)
1. Navigate to `http://localhost:5000/login`.
2. Sign in as ICT CA:
   - **Email**: `managerict@sreenidhi.edu.in`
   - **Password**: `Admin@321#`
3. View the assigned ticket on `/authority/tickets`.
4. Click on the ticket to view details.
5. Change status to **In Progress**, add an internal note: *"Replacing patch cable"*.
6. Change status to **Resolved**, add remarks: *"Replaced cable, switch port active"*.
7. Click **Logout**.

### Step 3: HOD Department Oversight & Reassignment (1 minute)
1. Navigate to `http://localhost:5000/login`.
2. Sign in as CSE HOD:
   - **Email**: `shirisha.k@sreenidhi.edu.in`
   - **Password**: `123`
3. Land on `/hod/dashboard` showing live department ticket metrics and CA workload.
4. Open `/hod/tickets` (HOD Ticket Management).
5. Demonstrate selective ticket reassignment (reassigning pending tickets among departmental CAs).
6. Click **Logout**.

### Step 4: Super Admin Overview & Governance (1 minute)
1. Navigate to `http://localhost:5000/login`.
2. Sign in as Super Admin:
   - **Email**: `admin@gmail.com`
   - **Password**: `Admin@321#`
3. Show:
   - Global dashboard with real-time KPI tiles.
   - **All Tickets** view with department filtering and export.
   - **Category & CA Management** showing category-to-department isolation.
   - **System Audit Log** showing activity history.

### Step 5: Google SSO Strict Whitelist Verification (30 seconds)
1. Click **"Sign in with Google"**.
2. If using a personal or unlisted student account:
   - System automatically denies login with:
     > *"Access restricted: The account (`<email>`) is not registered in the SNIST staff directory."*
3. If using an authorized institutional staff email (`@sreenidhi.edu.in`):
   - System authenticates immediately and loads their role-specific dashboard with zero duplicate database rows.

---

## 4. Key Rules to Remember
* **Admins & Staff**: Password is always `Admin@321#`.
* **Faculty & HODs**: Password is their **SAP ID** (e.g. `10000108`) or the default developer password **`123`**.
* **Zero Duplication**: All faculty authenticate directly from institutional `teacher_info`; no shadow user accounts are ever created in Help Desk tables.
* **Strict Department Matching**: Ticket categories strictly match the assigned CA's department.
