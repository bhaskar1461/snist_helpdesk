# 🏛️ SNIST Campus Help Desk — 1-Command Offline Demo Guide

Welcome! This package allows you to run and explore the **SNIST Campus Help Desk** web application with **zero external connections or database setup**. 

Everything runs self-contained out of the box — no MySQL, no internet/VPN, no mail servers, and no SMS gateways needed.

---

## 🚀 1-Step Quick Start

### Option A: Windows (Double-Click)
Simply double-click:
```bat
run_demo.bat
```

### Option B: Terminal / Command Prompt (Cross-Platform)
Run:
```bash
python run_demo.py
```
*(On macOS / Linux, you can also run `./run_demo.sh`)*

The launcher will:
1. Verify required Python packages (and auto-install from `requirements.txt` if needed).
2. Boot the standalone demo engine and load sample campus data.
3. Automatically open your default web browser to:
   👉 **`http://127.0.0.1:5000`**

---

## 🔑 One-Click Demo Accounts

On the sign-in page, you can **click any role button** to instantly autofill credentials, or use the table below:

| Role | Name & Department | Email | Password | What You Can Explore |
| :--- | :--- | :--- | :---: | :--- |
| 👑 **Super Admin** | System Administrator | `admin@gmail.com` | `123` | Full system control: Category management, user roles, location hierarchies, and campus-wide tickets. |
| 🏛️ **Campus Admin** | Facilities & Operations | `campus.admin@gmail.com` | `123` | Institutional ticket triage, analytics, and operational management. |
| 🎓 **HOD** | Dr. Kakarla Shirisha *(CSE Dept)* | `shirisha.k@sreenidhi.edu.in` | `123` | Department ticket queue, Assignee (CA) workload distribution, and category assignments. |
| 🛠️ **Assignee** | ICT Manager *(ICT Dept)* | `managerict@sreenidhi.edu.in` | `123` | Assigned technical complaints, ticket resolution lifecycle, work logs, and status transitions. |
| 👨‍🏫 **Faculty** | Varanasi Aruna *(CSE Faculty)* | `aruna.v@sreenidhi.edu.in` | `123` | Create new tickets, track real-time resolution progress, and reopen resolved tickets. |

---

## 🎯 Recommended 5-Minute Tour

### 1. Create a Ticket as Faculty
1. Click **Faculty (CSE)** on the login screen (`aruna.v@sreenidhi.edu.in`).
2. Go to **Create Ticket**.
3. Select Department: **ICT**, Category: **Internet & Wi-Fi**, Block: **Block A**, Room: **101**.
4. Submit the ticket. 
5. Notice that it is **automatically routed and assigned** to the ICT Manager based on category and location!

### 2. Resolve the Ticket as Assignee
1. Sign out and click **Assignee (ICT)** (`managerict@sreenidhi.edu.in`).
2. Go to **Assigned Tickets** to find your newly created ticket along with pre-seeded campus tickets.
3. Open the ticket and update the status to **In Progress** or **Resolved**.
4. Add a technician remark and time taken.
5. In your terminal console, watch the **live simulated SMS notification** print in real-time!

### 3. Review Department Health as HOD
1. Sign out and click **HOD (CSE)** (`shirisha.k@sreenidhi.edu.in`).
2. Explore the departmental KPIs, active ticket queue, and Assignee workloads.
3. Visit **Assignee Allocation** to see how multiple CAs are assigned across campus blocks.

### 4. System Administration as Super Admin
1. Sign out and click **Super Admin** (`admin@gmail.com`).
2. Explore **Category Management** to create or deactivate categories.
3. Explore **Campus Locations** to view blocks, floors, and room configurations.

---

## 💾 State Persistence & Resetting Data

- **Automatic Persistence**: All actions you perform (new tickets, status updates, notes) are saved locally to `demo_state.json`. You can stop and restart the server without losing changes.
- **Fresh Reset**: To wipe your test actions and revert back to clean sample data at any time, run:
  ```bash
  python run_demo.py --reset
  ```

---

## ⚙️ Advanced CLI Options

```bash
# Run on a custom port
python run_demo.py --port 8080

# Run without automatically opening a browser window
python run_demo.py --no-browser

# Wipe state and start fresh
python run_demo.py --reset
```
