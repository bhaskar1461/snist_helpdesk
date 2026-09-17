# SNIST Helpdesk — Credential Rotation & Incident Remediation Checklist

**Document Status**: ACTION REQUIRED  
**Target Date**: Immediate  
**Scope**: All production and staging credentials exposed in configuration templates, code comments, or historical git commits.

---

## 1. Executive Summary
During database hardening and security audits, real credentials for MySQL, BulkSMS, WhatsApp Unified Messaging, Metabase, and demo accounts were identified in repository history and configuration examples. These secrets must be treated as **COMPROMISED** and rotated across all upstream providers.

---

## 2. Credentials Inventory & Rotation Procedures

### A. MySQL Database Credentials
- **Exposed Secret**: User `demo`, Password `Admin@321#`
- **Where Used**: `db_services.py`, `.env`, `scripts/init_demo_db.py`
- **Hosts Affected**: `seg.sreenidhi.edu.in:3306`, `seg-dev.sreenidhi.edu.in:3306`
- **Responsible Party**: Database Administrator (DBA) / SNIST IT [OWNER ACTION REQUIRED]
- **Rotation Procedure**:
  1. Generate strong 32-character random password: `python -c "import secrets; print(secrets.token_urlsafe(24))"`
  2. Execute on MySQL server:
     ```sql
     ALTER USER 'demo'@'%' IDENTIFIED BY '<NEW_STRONG_PASSWORD>';
     FLUSH PRIVILEGES;
     ```
  3. Update `MYSQL_PASSWORD=<NEW_STRONG_PASSWORD>` in `/etc/snist_helpdesk/.env` (or VM `.env`).
  4. Restart application service: `sudo systemctl restart snist_helpdesk`.
- **Estimated Downtime**: < 5 seconds.

---

### B. BulkSMS Gateway API Key
- **Exposed Secret**: `c69fc621-e477-43c5-84ea-d9d94108d7cc` (Sender ID `SNISTA`)
- **Where Used**: `app/notifications.py`, `app.py`, `.env.example`
- **Historical Git Commits**: `1e750cf`, `86cca1d`, `08f38e5`, `5838c07`, `ccc6d49`
- **Responsible Party**: BulkSMS Service Provider / SNIST Communications [OWNER ACTION REQUIRED]
- **Rotation Procedure**:
  1. Log in to the BulkSMS portal (`http://bulksmsapps.com`).
  2. Navigate to **API Settings** -> **Generate New API Key**.
  3. Invalidate/revoke key `c69fc621-e477-43c5-84ea-d9d94108d7cc`.
  4. Update `SMS_API_KEY=<NEW_KEY>` in production `.env`.
  5. Restart service: `sudo systemctl restart snist_helpdesk`.
- **Estimated Downtime**: 0 seconds (SMS queuing handles transit).

---

### C. WhatsApp Unified Messaging API Credentials
- **Exposed Secret**:
  - `WHATSAPP_CLIENT_ID=sreenidhiclgbepfs44jy504`
  - `WHATSAPP_CLIENT_PASSWORD=wm84r8yhj9mzp9m1yrm78fqhpmzb8on0`
  - `WHATSAPP_FROM_NUMBER=919133386678`
- **Where Used**: `app/notifications.py`, `app.py`, `.env.example`
- **Historical Git Commits**: `ba0cb24`
- **Responsible Party**: Unified Messaging Platform Administrator [OWNER ACTION REQUIRED]
- **Rotation Procedure**:
  1. Log in to the Unified Messaging portal (`https://103.229.250.150`).
  2. Reset client API password for client ID `sreenidhiclgbepfs44jy504`.
  3. Update `WHATSAPP_CLIENT_PASSWORD=<NEW_PASSWORD>` in production `.env`.
  4. Restart service: `sudo systemctl restart snist_helpdesk`.
- **Estimated Downtime**: 0 seconds.

---

### D. Metabase Admin Password & Secret Key
- **Exposed Secret**:
  - Admin Email: `admin@gmail.com`
  - Admin Password: `Admin@321#`
  - Secret Key: `b6c0144720edd6f7369910c70c66e0519ac0386c2b9d173434c57332a048e685`
- **Where Used**: `.env.example`, `scripts/configure_metabase.py`, `app/analytics.py`
- **Responsible Party**: Metabase Administrator / DevOps [OWNER ACTION REQUIRED]
- **Rotation Procedure**:
  1. Log in to Metabase (`https://metabase.1sports.app`).
  2. Navigate to **Admin Settings** -> **Embedding in other applications**.
  3. Click **Regenerate Secret Key**.
  4. Change admin user password from `Admin@321#` to a unique passkey.
  5. Update `METABASE_SECRET_KEY=<NEW_KEY>` and `MB_ADMIN_PASSWORD=<NEW_PASS>` in `.env`.
  6. Restart service: `sudo systemctl restart snist_helpdesk`.
- **Estimated Downtime**: 0 seconds.

---

### E. Flask Application SECRET_KEY
- **Where Used**: Session signing in `app/__init__.py`.
- **Responsible Party**: DevOps / Deployment Engineer [OWNER ACTION REQUIRED]
- **Rotation Procedure**:
  1. Generate cryptographically secure token:
     ```bash
     python -c "import secrets; print(secrets.token_hex(32))"
     ```
  2. Update `SECRET_KEY=<NEW_TOKEN>` in production `.env`.
  3. Restart application service: `sudo systemctl restart snist_helpdesk`.
- **Impact**: All active user sessions will be logged out and required to sign in again.
- **Estimated Downtime**: < 2 seconds.

---

### F. SMTP Mail Password
- **Where Used**: `SMTP_PASSWORD` for `support.helpdesk@sreenidhi.edu.in`.
- **Responsible Party**: SNIST Mail Admin / IT [OWNER ACTION REQUIRED]
- **Rotation Procedure**:
  1. Reset mailbox password in college email server (`mail.sreenidhi.edu.in`).
  2. Update `SMTP_PASSWORD=<NEW_PASSWORD>` in production `.env`.
  3. Restart application service: `sudo systemctl restart snist_helpdesk`.

---

## 3. Git History Cleansing with `git-filter-repo`

Because secrets reside in historical commits, cloning the git repository exposes them. The repository owner should scrub the historical commits using `git-filter-repo` or BFG Repo-Cleaner.

### Recommended Scrub Command (To be executed by Repository Owner):
```bash
# Install git-filter-repo
pip install git-filter-repo

# Create replace file expressions.txt
cat << 'EOF' > expressions.txt
c69fc621-e477-43c5-84ea-d9d94108d7cc==>REDACTED_SMS_KEY
sreenidhiclgbepfs44jy504==>REDACTED_WA_CLIENT
wm84r8yhj9mzp9m1yrm78fqhpmzb8on0==>REDACTED_WA_SECRET
b6c0144720edd6f7369910c70c66e0519ac0386c2b9d173434c57332a048e685==>REDACTED_METABASE_KEY
Admin@321#==>REDACTED_PASSWORD
EOF

# Run filter-repo on a clean clone
git-filter-repo --replace-text expressions.txt --force
```
*(After history rewriting, coordinate with collaborators to re-clone the repository).*

---

## 4. Pre-Commit Security Policy
All developers must run `scripts/check_secrets.py` prior to pushing commits. The CI pipeline will reject commits containing matched entropy patterns or known provider secrets.
