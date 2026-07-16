# Troubleshooting Guide

This guide covers diagnostic commands, troubleshooting workflows, and resolutions for common issues when running the SNIST Helpdesk System.

---

## 1. Diagnostic Commands

### View Application Logs
If running under Docker:
```bash
docker compose logs -f web
```

### Check Container Health Status
```bash
docker compose ps
```

### Execute Database Command Line inside Container
```bash
docker exec -it snist_helpdesk-web-1 mysql -u demo -pAdmin@321# seg_demo
```

---

## 2. Common Errors and Resolutions

### Error: `SECRET_KEY not set — using a random key.`
- **Cause**: The `SECRET_KEY` environment variable is not defined or is set to default placeholder text.
- **Resolution**: Open your `.env` file, uncomment/add the `SECRET_KEY` variable, and generate a secure key:
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
  Restart the containers.

### Error: `File type not allowed` on valid attachments
- **Cause**: The file's binary magic bytes do not match the expected extensions, or the format contains custom signature headers.
- **Resolution**: Verify that the file header signature falls within standard specs (JPEG, PNG, GIF, PDF, ZIP/DOCX/XLSX, or OLE CF). If using custom documents, save as PDF or modern DOCX format.

### Error: `MySQL is not configured`
- **Cause**: Database connection parameters in `.env` are invalid, or the database host is unreachable.
- **Resolution**: Verify database host, port, user, and password parameters match the credentials. Run `ping` from the application host to test network connectivity.
