# Changelog

All notable changes to the SNIST Helpdesk project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-07-17

### Added
- Native file magic-bytes/signature verification (`verify_file_signature()`) to reject masqueraded executable/script attachments.
- Passive SLA escalation handling (`add_escalation_status()`) flagging tickets open for >24 hours.
- Submit-button loading spinner inside `ca_assignments.html` to prevent duplicate submissions.
- Multi-mapping transaction integrity wrappers (`DemoDbService.transaction()`) guaranteeing atomic state transitions.
- Environment-level session key persistence (`SECRET_KEY` load from `.env`).
- One-click installer shell script `install.sh`.
- Comprehensive deployment, architecture, security, and developer guides in `docs/`.

### Fixed
- Jinja endpoint build error in `ticket_detail.html` where `view_attachment` was called instead of the correct `download_attachment` route.

## [1.0.0] - 2026-07-16

### Added
- Core multi-category and multi-block CA assignments backend routes.
- Custom dropdown multi-select checklists in `ca_assignments.html`.
- Active mapping grouping lists displaying exactly one row per CA.
- Multi-organization partitioning support (`org_id` parameters).
- Complete automated unit tests covering user/CA mapping boundaries.
