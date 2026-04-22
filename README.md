# 🎫 SNIST Helpdesk Platform

A role-based helpdesk ticketing system built with **Flask** and **MySQL**, designed for Sreenidhi Institute of Science and Technology. Faculty can raise tickets, Concerned Authorities resolve them, and HODs / Admins manage the workflow.

---

## 📋 Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Project](#running-the-project)
- [Demo Accounts](#demo-accounts)
- [Project Structure](#project-structure)

---

## ✨ Features

- **Role-Based Access Control** — Super Admin, Admin, HOD, Concerned Authority (CA), Faculty
- **Ticket Lifecycle** — Create → Pending → In Progress → Resolved
- **Auto-Assignment** — Tickets auto-assigned to the mapped CA based on category
- **CA Reports** — Resolution time tracking for Concerned Authorities
- **User & Category Management** — Full CRUD for users and category-to-CA mappings
- **CSV / Excel Export** — Download filtered ticket data
- **File Attachments** — Upload supporting documents during ticket updates
- **Search & Filters** — Filter by status, department, organization, and date range

---

## 🛠 Tech Stack

| Layer     | Technology       |
|-----------|------------------|
| Backend   | Python 3.10+, Flask 3.1 |
| Database  | MySQL (via PyMySQL) |
| Frontend  | Jinja2 Templates, Vanilla CSS |
| Auth      | Session-based (Flask sessions) |

---

## ✅ Prerequisites

Make sure you have the following installed:

- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **MySQL 8.0+** — [Download](https://dev.mysql.com/downloads/)
- **Git** — [Download](https://git-scm.com/downloads)

---

## 🚀 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/bhaskar1461/snist_helpdesk.git
cd snist_helpdesk
```

### 2. Create a Virtual Environment

```bash
python3 -m venv .venv
```

### 3. Activate the Virtual Environment

**Linux / macOS:**

```bash
source .venv/bin/activate
```

**Windows:**

```bash
.venv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

### 5. Create the Environment File

Copy the example file and edit it with your MySQL credentials:

```bash
cp .env.example .env
```

Open `.env` and update the values:

```env
# MySQL Database Configuration
MYSQL_HOST=localhost
MYSQL_USER=your_mysql_user
MYSQL_PASSWORD=your_mysql_password
MYSQL_DATABASE=snist_helpdesk
MYSQL_PORT=3306

# Flask Secret Key (change this in production!)
SECRET_KEY=your-secret-key-here

# Set to 'false' to skip demo schema initialization on startup
INIT_DEMO_DB=true
```

### 6. Create the MySQL Database

Log in to MySQL and create the database:

```bash
mysql -u root -p
```

```sql
CREATE DATABASE snist_helpdesk CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
EXIT;
```

> **Note:** When `INIT_DEMO_DB=true`, the app will automatically create all required tables and seed demo data on first run.

---

## ▶️ Running the Project

### 7. Start the Application

```bash
python app.py
```

The server will start at:

```
http://127.0.0.1:5000
```

Open this URL in your browser to access the login page.

---

## 👤 Demo Accounts

When `INIT_DEMO_DB=true`, the following demo accounts are created automatically:

| Role         | Email                      | Password | Department     |
|--------------|----------------------------|----------|----------------|
| Super Admin  | admin@gmail.com            | 123      | Administration |
| Admin        | campus.admin@gmail.com     | 123      | Administration |
| HOD (CSE)    | hod@gmail.com              | 123      | CSE            |
| HOD (ECE)    | hod.ece@gmail.com          | 123      | ECE            |
| CA           | ca@gmail.com               | 123      | CSE            |
| CA           | sravan.ca@gmail.com        | 123      | Facilities     |
| CA           | bhaskar.ca@gmail.com       | 123      | Maintenance    |
| Faculty      | faculty@gmail.com          | 123      | CSE            |

---

## 📁 Project Structure

```
snist_helpdesk/
├── app.py                  # Main Flask application
├── db_services.py          # Database service layer
├── requirements.txt        # Python dependencies
├── .env.example            # Environment variable template
├── .gitignore              # Git ignore rules
├── management_data.json    # Management config data
├── tickets.json            # Sample ticket data
├── sql/
│   └── demo_schema.sql     # Database schema (auto-applied)
├── scripts/
│   └── init_demo_db.py     # Standalone DB initialization script
├── static/
│   ├── css/                # Stylesheets
│   └── images/             # Static images
├── templates/              # Jinja2 HTML templates
│   ├── login.html
│   ├── faculty_dashboard.html
│   ├── management_dashboard.html
│   ├── authority_tickets.html
│   ├── ticket_detail.html
│   ├── create_ticket.html
│   ├── user_management.html
│   ├── category_management.html
│   └── ...
└── uploads/                # User-uploaded attachments (gitignored)
```

---

## 📝 License

This project is developed for academic purposes at SNIST.
