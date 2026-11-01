# Architecture (as implemented)

Offline single-workstation Python 3.11+ services with local SQLite (`sqlite3`) and no HTTP API or mandatory online services. `ClinicDatabase` owns per-operation connections with foreign keys, serialized transactional writes and schema migrations. `services.py` retains the original patient, appointment, room and current-tooth-state services; `medical.py`, `clinical.py`, `finance.py`, `reporting.py`, `auth.py`, `attachments.py`, and `backup.py` add specialized operations.

The database is **not encrypted at rest**. Attachment contents and backup archives are independently encrypted with AES-256-GCM; attachment encryption keys are supplied by the caller and must not be hardcoded. No DPAPI or secure key lifecycle yet. Sessions, roles, and Argon2id password hashing are implemented as primitives; every clinical service still needs to be routed through a trusted authenticated application boundary. Do not enter real patient information.

The old SQLite v1 schema upgrades additively to v2 in one atomic migration system. Future schema changes must add new numbered migrations, not silently edit migrations already deployed. The requested SQLAlchemy 2.x layered architecture is **not yet implemented**. Avoid introducing a competing Alembic migration system without a carefully tested conversion plan.

See `BACKEND_COMPLETION_REPORT.md` for details and limitations.
