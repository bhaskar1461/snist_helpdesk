# Deployment Guide

This document describes how to deploy the SNIST Helpdesk System to production on virtual private servers (VPS), cloud platforms (AWS, Azure, GCP, Render, Railway), configure backups, and perform database migrations.

---

## 1. Automated Virtual Private Server (VPS) Deployment

To spin up the SNIST Helpdesk on any clean Ubuntu/Debian instance (DigitalOcean, AWS EC2, Azure, Hetzner), run the automated installer:

```bash
git clone https://github.com/your-org/snist_helpdesk.git
cd snist_helpdesk
bash install.sh
```
This script handles dependency validation, Docker installation, environment configuration copies, database seeding, and container startup.

---

## 2. Docker Compose Deployment

If Docker and Docker Compose are already present on the server, you can deploy manually:

1. **Clone & Setup Environment**:
   ```bash
   git clone https://github.com/your-org/snist_helpdesk.git
   cd snist_helpdesk
   cp .env.example .env
   ```
2. **Edit Configuration**:
   Update `SECRET_KEY`, database credentials, and notification settings (SMTP/SMS/WhatsApp credentials) in `.env`.
3. **Boot Services**:
   ```bash
   docker compose up -d --build
   ```
   This starts the main Web app (`http://localhost:5001`), Metabase (`http://localhost:3002`), and the automated `metabase-init` setup worker.

---

## 3. Reverse Proxy & SSL Configuration (Nginx & Certbot)

To secure the application with Let's Encrypt SSL, configure Nginx as a reverse proxy for both the Helpdesk Web application and embedded Metabase analytics:

1. **Install Nginx & Certbot**:
   ```bash
   sudo apt update
   sudo apt install nginx certbot python3-certbot-nginx -y
   ```
2. **Configure Nginx virtual host** (`/etc/nginx/sites-available/helpdesk.conf`):
   ```nginx
   server {
       listen 80;
       server_name helpdesk.sreenidhi.edu.in;

       location / {
           proxy_pass http://127.0.0.1:5001;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
       }

       # Metabase reverse proxy (optional if accessing embedded iframe directly)
       location /metabase/ {
           proxy_pass http://127.0.0.1:3002/;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
       }
   }
   ```
3. **Enable & Secure**:
   ```bash
   sudo ln -s /etc/nginx/sites-available/helpdesk.conf /etc/nginx/sites-enabled/
   sudo nginx -t && sudo systemctl restart nginx
   sudo certbot --nginx -d helpdesk.sreenidhi.edu.in
   ```

---

## 4. Production Database Setup & Migrations

### Production Schema Application
To initialize a clean production database using the production schema:
```bash
mysql -u <username> -p <database_name> < sql/production_schema.sql
```
This sets up all `helpdesk_*` tables, indexes, foreign keys, and double-submit `submission_key` deduplication constraints.

### Automatic Migrations
The application automatically executes database migrations (`v2` through `v6`) on startup.
- **Migration V5**: Adds `submission_key` to `helpdesk_tickets` and unique indexes on activity/notes for deduplication.
- **Migration V6**: Safely renames existing `demo_*` tables to production `helpdesk_*` names.

### Legacy Database Migration
To migrate historical data from legacy dumps (e.g. `sreenidhi.sys_administrators` and `sreenidhi.sys_complaint`):

1. **Place Dump File**: Ensure `sql/sreenidhi_dump.sql` exists in the codebase root.
2. **Run Migration Pipeline**:
   ```bash
   docker exec snist_helpdesk-web-1 python scripts/migrate_legacy_data.py
   ```
   This automatically:
   - Imports `sys_administrators` -> `helpdesk_users` (mapping teacher roles and accounts).
   - Extracts unique block/room coordinates -> `location`.
   - Maps complaint device categories -> `helpdesk_categories`.
   - Imports all historical tickets into `helpdesk_tickets`.

---

## 5. Backups and Recovery

### Database Backup (MySQL Dump)
To generate an immediate database snapshot backup:
```bash
docker exec -t snist_helpdesk-web-1 mysqldump -u demo -pAdmin@321# seg_demo > backup.sql
```

### Database Restore
To restore a snapshot:
```bash
docker exec -i snist_helpdesk-web-1 mysql -u demo -pAdmin@321# seg_demo < backup.sql
```
