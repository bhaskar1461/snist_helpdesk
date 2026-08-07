# SNIST Helpdesk System

A production-grade, secure ticketing and support routing platform developed for the Sreenidhi Institute of Science and Technology (SNIST). This platform partitions user domains, automates ticket distribution to Concerned Authorities (CAs) based on categories and blocks, schedules async email/SMS notifications, and passive SLA overdue warnings.

---

## Features

- **Dynamic Ticket Routing**: Automatic ticket allocation to block-level Concerned Authorities (CAs).
- **Embedded Metabase Analytics**: Full-fledged visual analytics with JWT dashboard embedding (Overview, Trends, CA Performance) and automatic Metabase provisioning.
- **Legacy Sreenidhi Migration**: Built-in migration pipeline to convert legacy MySQL dumps (`sys_administrators` & `sys_complaint`) into unified helpdesk records.
- **Multi-Tenant Partitioning**: Organization-level isolation separating distinct college databases (e.g. SNIST, SNU).
- **Grouped CA Mapping UI**: Interactive admin screen displaying CA assignments with collapsible multiselect dropdowns.
- **SLA Passive Alerts**: Automatic escalation flags on open tickets exceeding a 24-hour response window.
- **File Signatures Validation**: Advanced security check examining file headers to block malicious script masquerading.
- **CSRF & Rate Lockouts**: Built-in protection against brute-force logins and cross-site scripting exploits.
- **Async Notification Dispatches**: Asynchronous background workers offloading email and SMS dispatch threads.

---

## Tech Stack

- **Framework**: Python 3.11, Flask 3.1.0, Flask-WTF
- **Database**: MySQL 8.x / PyMySQL Connection Pool
- **Analytics & BI**: Metabase 0.49+ (Docker containerized with JWT static embedding)
- **Aesthetics & UI**: Modern HTML5, Vanilla CSS (Outfit & Space Grotesk fonts), Lucide Icons, Chart.js fallback
- **Deployment**: Docker, Docker Compose, Gunicorn

---

## Architecture

Detailed architecture blueprints can be found in [docs/architecture.md](docs/architecture.md).

---

## Screenshots

*(Screenshots will display here when deployed)*

---

## Installation

### Option 1: Docker (Recommended)
Build and run all services in a single command:
```bash
docker compose up -d --build
```

### Option 2: Local Development
Refer to [docs/development.md](docs/development.md) for local manual configurations.

### Option 3: Automated Script VPS Build
To deploy instantly on a clean VPS instance:
```bash
bash install.sh
```

---

## Requirements

- **Operating System**: Ubuntu 20.04 LTS / 22.04 LTS (or Windows with Docker Desktop)
- **RAM**: Minimum 2 GB (4 GB recommended)
- **CPU**: Dual-core x86_64
- **Disk**: 10 GB free space
- **Software**: Docker 20.10+, Docker Compose 2.0+

---

## Environment Variables

| Variable | Description | Default / Example |
| :--- | :--- | :--- |
| `MYSQL_HOST` | Database Host Address | `seg-dev.sreenidhi.edu.in` |
| `MYSQL_DATABASE` | Database Name | `seg_demo` |
| `MYSQL_USER` | MySQL Username | `demo` |
| `MYSQL_PASSWORD` | MySQL User Password | `Admin@321#` |
| `SECRET_KEY` | Flask session cookie signing key | `c69fc621e47743c584ea0...` |
| `SMTP_HOST` | SMTP Server Host Address | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP Connection Port | `587` |

*(See `.env.example` for all notification and WhatsApp key variables)*

---

## Database Setup

- **Production Schema**: The production-ready database schema is provided in [`sql/production_schema.sql`](sql/production_schema.sql) with clean `helpdesk_*` table prefixes.
- **Anti-Duplication**: Built-in double-submit protection using UUID `submission_key` constraints on `helpdesk_tickets` and unique deduplication indexes on activities & notes.
- **Automated Bootstrapping & Migrations**: Automatically builds database tables and executes migrations (`v2` to `v6`) on application startup. Can be disabled via `INIT_DEMO_DB=false`.
- **Manual Schema Setup**:
  ```bash
  mysql -u <user> -p <db_name> < sql/production_schema.sql
  ```

---

## API Documentation

- **GET `/api/locations`**: Fetches location block/room tree details.
- **GET `/api/categories`**: Retrieves category names grouped by branches.
- **POST `/authority/update-status/<id>`**: Updates ticket status with file signature validation.

---

## Authentication

- Access is restricted using Role-Based Access Control (`@role_required`).
- Permitted Roles: `SUPER_ADMIN`, `ADMIN`, `HOD`, `CA`, and `FACULTY`.
- Defaults: Promotes teachers to respective HOD/CA profiles based on department references.

---

## Logs
- Standard container out logs:
  ```bash
  docker compose logs -f web
  ```

---

## Monitoring
- Check endpoint status codes:
  - `/` (Redirect status `302` or page load `200`).
  - `/api/locations` (`200` JSON response).

---

## Troubleshooting
Refer to the [Troubleshooting Guide](docs/troubleshooting.md) for diagnostic workflows.

---

## License
Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

## Contributing
We welcome improvements! See [CONTRIBUTING.md](CONTRIBUTING.md) for onboarding guidelines.
