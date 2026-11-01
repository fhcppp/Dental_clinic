# Architecture (as implemented)

Offline single-workstation Python 3.11+ services with local SQLite (`sqlite3`) and no HTTP API or mandatory online services. `ClinicDatabase` owns per-operation connections with foreign keys, serialized transactional writes and schema migrations. `services.py` retains the original patient, appointment, room and current-tooth-state services; `medical.py`, `clinical.py`, `finance.py`, `reporting.py`, `auth.py`, `attachments.py`, and `backup.py` add specialized operations.

The database is **not encrypted at rest**. Attachment contents and backup archives are independently encrypted with AES-256-GCM; attachment encryption keys are supplied by the caller and must not be hardcoded. No DPAPI or secure key lifecycle yet. Sessions, roles, and Argon2id password hashing are implemented as primitives; every clinical service still needs to be routed through a trusted authenticated application boundary. Do not enter real patient information.

The old SQLite v1 schema upgrades additively to v2 in one atomic migration system. Future schema changes must add new numbered migrations, not silently edit migrations already deployed. The requested SQLAlchemy 2.x layered architecture is **not yet implemented**. Avoid introducing a competing Alembic migration system without a carefully tested conversion plan.

See `BACKEND_COMPLETION_REPORT.md` for details and limitations.

## Phase 1 architecture update

A standalone clinic settings object and `security/keys.py` isolate settings validation and encryption-envelope primitives. Standard sqlite3 services remain mixed with SQL statements; persistence boundary extraction is still outstanding. `ClinicDatabase` disallows production startup instead of opening plaintext data. See ADRs 0005–0007.

### Recovered-code integration provenance

This integration adds no competing migration system or new service rewrite. The verified upstream v1→v2 tree and the reconstructed baseline tree are byte-identical at the Git tree level. The Phase 1 additions and intentional test-only SQLite opt-in are catalogued in [`INTEGRATION_CHANGELOG.md`](INTEGRATION_CHANGELOG.md). Full persistence-layer separation and authenticated service authorization remain unfinished.

## v3 audit/identity milestone (2026-11-01)

Additive v3 schema retains v1/v2 IDs and adds an `audit_chain` row for each
`audit_events` record and `auth_login_attempts`. Audit HMAC is registered
per SQLite connection; the insert trigger is atomic with business writes.
Startup verifies the retained chain. No anti-rollback anchor exists. This
work does not create a production persistence provider or a service-wide
trusted actor boundary. See ADR 0008 and PRODUCTION_READINESS.md.
