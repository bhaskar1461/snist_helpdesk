# System Architecture

The SNIST Helpdesk System is built using a clean, MVC-adjacent pattern on top of Python and the Flask micro-framework. This document outlines the component separation, directory layout, routing system, database pooling model, and transaction management flow.

---

## 1. High-Level Architecture

The application operates as a single-container (or multi-container with database services) web application communicating with a MySQL database.

```
       ┌────────────────────────────────────────────────────────┐
       │                       Client / UI                      │
       └───────────────────────────┬────────────────────────────┘
                                   │ HTTPS / Requests
                                   ▼
       ┌────────────────────────────────────────────────────────┐
       │                Flask Application (app.py)              │
       │  ┌───────────────────────┐   ┌──────────────────────┐  │
       │  │    Route Controllers  │   │ CSRF/Rate-Limit/Auth │  │
       │  └───────────┬───────────┘   └──────────────────────┘  │
       └──────────────┼─────────────────────────────────────────┘
                      │
                      ▼
       ┌────────────────────────────────────────────────────────┐
       │          Database Services Layer (db_services.py)      │
       │  ┌───────────────────────┐   ┌──────────────────────┐  │
       │  │   Live & Demo Services│   │ Connection Pool (Q)  │  │
       │  └───────────┬───────────┘   └──────────┬───────────┘  │
       │              │                          │              │
       │              ▼                          ▼              │
       │  ┌──────────────────────────────────────────────────┐  │
       │  │             Thread-Local Transactions            │  │
       │  └───────────────────────┬──────────────────────────┘  │
       └──────────────────────────┼─────────────────────────────┘
                                  │ SQL Queries
                                  ▼
       ┌────────────────────────────────────────────────────────┐
       │                   MySQL Database Host                  │
       └────────────────────────────────────────────────────────┘
```

---

## 2. Directory Layout

The directory structure is organized as follows:

```
snist_helpdesk/
├── .github/                # GitHub workflows & Templates
├── docs/                   # Architectural & Operational Guides
├── scripts/                # Database initialization and sync utilities
├── sql/                    # SQL schema definitions & migrations
├── static/                 # Static CSS, JS, and image assets
├── templates/              # Jinja2 HTML templates
├── tests/                  # Automated unit & integration tests
├── app.py                  # Core application controllers and startup
├── db_services.py          # Database services & connection pool
├── email_services.py       # Email async dispatch logic
├── sms_services.py         # SMS & WhatsApp alert connectors
├── Dockerfile              # Docker container configuration
└── docker-compose.yml      # Service orchestration specification
```

---

## 3. Database Pooling & Transactions

- **Connection Pool**: Built upon Python's `queue.Queue` object, connections are acquired, validated with `ping(reconnect=True)`, and returned to the pool to prevent connection dropouts.
- **Transaction Engine**: A context manager (`DemoDbService.transaction()`) sets `autocommit(False)` on a raw pymysql connection, binds it to the current thread-local storage (`threading.local()`), and commits or rolls back atomically. This ensures multi-statement transactions (like CA mapping updates) fail or succeed as a single block.
