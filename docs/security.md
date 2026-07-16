# Security Implementation Guide

The SNIST Helpdesk System incorporates robust security protections corresponding to OWASP Top 10 guidelines to defend database layers, authorization domains, sessions, and files against exploit vectors.

---

## 1. Input Validation and File Security

- **Binary Signature Verification**: Masquerading scripts or executables under fake image extensions (e.g. `malicious.exe` renamed to `image.png`) is prevented using the `verify_file_signature()` helper. This function reads the first 4 bytes of uploaded files to verify they match true binary headers (PNG, JPG/JPEG, PDF, GIF, and ZIP/DOCX/XLSX) before saving.
- **Path Traversal Guards**: Filenames are sanitized via `secure_filename()` to remove directory traversal indicators (e.g. `../../etc/passwd`).
- **File Upload Limits**: Large upload payload sizes are restricted on the server via `MAX_UPLOAD_SIZE = 10 * 1024 * 1024` (10MB limit).

---

## 2. Session and Authentication Protections

- **CSRF Token Security**: Globally enforced across all HTML forms and AJAX controller routes using the `Flask-WTF` `CSRFProtect` middleware.
- **Brute-Force Rate Limiting**: Features IP-based lockout logging:
  - Max limits set to 5 failed attempts per minute.
  - Lockout windows enforce a 1-minute timeout period.
- **Cookie Security Parameters**: Flask sessions are configured with:
  - `SESSION_COOKIE_HTTPONLY=True` (Defends against XSS document cookie leakage).
  - `SESSION_COOKIE_SAMESITE='Lax'` (Defends against CSRF cross-origin state changes).
  - `SESSION_COOKIE_SECURE=True` (Optional configuration enabling HTTPS delivery parameters).

---

## 3. SQL Injection Defense

- **Parameterized Statements**: Database operations utilize parameterized SQL queries (binding query variables to `%s` tokens). Raw interpolation is strictly avoided, preventing attackers from injecting arbitrary database commands.
