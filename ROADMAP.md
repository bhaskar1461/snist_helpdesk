# SNIST Helpdesk System Roadmap

This document outlines the milestones and roadmap for the SNIST Helpdesk development.

## Milestone 1: Core System Hardening (Completed)
- [x] Database connection pooling (`Queue`-based pool).
- [x] Thread-local database transactions wrapper (`DemoDbService.transaction()`).
- [x] Persistent session store integration using static environment keys.
- [x] Asynchronous background thread pools for email/SMS notifications.
- [x] Strict mime-type signature checks validating magical bytes of uploads.
- [x] Duplicate submit lockouts inside form action pages.
- [x] Passive SLA escalation detection and unit test verification.

## Milestone 2: Enterprise Integration (Upcoming)
- [ ] Migrate database interfaces from raw SQL strings to SQLAlchemy ORM.
- [ ] Configure external queue workers using Celery and Redis to handle email retry schedules.
- [ ] Implement SAML/OAuth Single Sign-On (SSO) integration with Sreenidhi college portal credentials.
- [ ] Build a visual drag-and-drop SLA escalation rules builder.

## Milestone 3: Monitoring & Logging Analytics
- [ ] Integrate Prometheus and Grafana metrics collection.
- [ ] Build interactive department SLA violation charts.
- [ ] Set up ELK Stack (Elasticsearch, Logstash, Kibana) central logging.
