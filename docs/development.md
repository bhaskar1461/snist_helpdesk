# Local Development Guide

This guide describes how to configure, develop, test, and run the SNIST Helpdesk System in a local development environment.

---

## 1. Local Python Environment Setup

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/your-org/snist_helpdesk.git
   cd snist_helpdesk
   ```
2. **Create and Activate Virtual Environment**:
   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Unix/macOS
   source .venv/bin/activate
   ```
3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Setup Environment Configurations**:
   ```bash
   cp .env.example .env
   # Edit .env variables, including SECRET_KEY and SMTP configurations
   ```
5. **Run the Development Server**:
   ```bash
   python app.py
   ```
   Open `http://localhost:5000` in your web browser.

---

## 2. Running Automated Tests

We use Python's built-in `unittest` library alongside custom database mock objects.

To run the complete test suite (49 tests):
```bash
python -m unittest discover -s tests/
```

To run a specific test file:
```bash
python -m unittest tests/test_tickets.py
```

---

## 3. Directory and Code Standards
- **Style**: Standard PEP 8 formatting rules for Python scripts.
- **Form Actions**: Always redirect after handling a POST request (PRG: Post/Redirect/Get pattern) to prevent double-submit events.
- **Database Modifiers**: Wrap write operations in `with db.transaction():` context blocks to guarantee atomicity.
