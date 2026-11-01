> **Update 2026-11-01:** Phase 0 completed; Phase 1 partially implemented. The latest acceptance statuses and evidence are in [`BACKEND_ACCEPTANCE_REPORT.md`](BACKEND_ACCEPTANCE_REPORT.md). Local `unittest` and `pytest` each pass **50 tests** after the fail-closed database gate, pre-migration backup and key envelope work. No fresh GitHub CI run or real Windows check is claimed. Backend remains **NOT PRODUCTION-READY**.

# Backend progress and completion gate (2026-11-01)

**Status: PARTIAL, NOT PRODUCTION-READY.** This document reports a real backend milestone, not a completion certificate. The uploaded backend-completion mission has stricter requirements than the current code meets.

## Preserved and expanded architecture

The existing v1 `sqlite3` services, legacy API and tests were preserved. The same `PRAGMA user_version` migration mechanism installs a transactionally applied v2 schema; no database rebuild or destructive migration is performed. The implementation remains a single-workstation, offline Python service library. SQLAlchemy 2.x and Alembic are **not yet used**; changing persistence implementations safely remains separate work.

`ClinicDatabase` creates SQLite connections with foreign keys enabled, IMMEDIATE write transactions and rollback on failure. Domain validation resides in specialized modules, but the present architecture is not yet the final fully separated domain/application/infrastructure architecture.

## Implemented modules

- Patients: existing registration, archive, appointments, plus editable structured demographic data, calculated birth-date age, marked approximate age with reference date, candidate duplicate detection and before-image revision history.
- Medical history: append-only typed entries for conditions, allergies, medications and alerts, with linked amendments, staff-supplied identity metadata and current/history queries.
- Dentistry: FDI permanent/primary codes, validated relational tooth surfaces, chronological observations, dentist records, configurable procedure catalog, independent clinical visits, treatment plans and items, treatment history, immutable completed treatment rows, relational restoration details and endodontic stages/canals.
- Financial: invoice line items, finalized-invoice protections, exact integer minor-unit accounting, partial payments, refund events and balances. Amount conversion starts from `Decimal` or decimal strings (not float).
- Scheduling: existing concurrent overlap protection, timezone normalization and DST tests; optional room directory and room collision checking.
- Security *primitives*: Argon2id user passwords, login with hashed random session tokens, expiry/idle timeout, role permission primitives, AES-256-GCM attachment vault, integrity checking, manifest-verified passphrase-encrypted full backups.
- Reporting: date-filtered registration, appointment, procedure and payment summaries; outstanding invoices and CSV export.

## Key relationships and constraints

- `patients` 1→N `medical_entries`, `patient_profile_revisions`, `clinical_visits`, `tooth_observations`, `treatments` and `invoices`.
- `clinical_visits` 1→N `treatments`; composite `(visit_id, patient_id)` foreign keys prevent cross-patient treatment linkage.
- `treatment_plans` 1→N `treatment_plan_items`; a plan item is not a performed treatment. A completed treatment may reference the planned item.
- `treatments` 1→N `treatment_surfaces` and `endodontic_stages`; `endodontic_stages` 1→N `endodontic_canals`.
- `invoices` 1→N `invoice_items` and `payments`; refunds are new payment rows referencing originals.
- Clinical and medical history uses append-only entries. SQLite triggers block selected finalized-row changes and protected line-item deletion. Current tooth-state setters now also append tooth-state history.

## Executed checks

Run locally from the repository root:

```bash
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -q
python -m pytest -q
python -m compileall -q src tests
ruff check .
mypy src/dental_clinic --ignore-missing-imports
```

On the authoring environment, `PYTHONPATH=src python -m unittest discover -s tests -q` passed **37/37 tests** before report generation. Lint and type checking were not executed because Ruff and mypy were unavailable in the local environment; they must pass in CI before merge. The suite includes legacy timezone/concurrency tests, synthetic clinical/financial history and encrypted backup/attachment tests. GitHub CI results for this milestone must be checked separately after publishing; previous run results do not establish results for new code.

## Production blockers and unfinished features

1. **Unsafe for real patients.** Standard SQLite data is unencrypted at rest; SQLCipher on Windows and DPAPI-managed keys have not been implemented/tested.
2. **Authorization not end-to-end.** Legacy service functions still accept arbitrary `actor_id`. The new auth service is a primitive, not a guard automatically applied to every clinical/financial service.
3. **Audit limitations.** Audit records are metadata-only, but stored in modifiable local SQLite tables without tamper-evident signing; durable authenticated authorship is not established.
4. **Incomplete workflow and integrity gates.** No full room/working-hours availability calendar, no robust plan-item transition history, no centralized amendment approval, and no full cross-entity authorization policy. Some domain invariants are enforced in Python rather than SQLite triggers.
5. **Clinical details.** Endodontic stages and restoration details do not yet cover every specified field and longitudinal treatment case, and visit notes are not separately versioned.
6. **Backup scheduling and recovery.** Manual encrypted backup and restore-to-new-path are implemented. Automatic backup scheduling, safe live database switchover, retention policy and recovery from partial directory moves are not implemented.
7. **Windows deliverables.** No PySide6 interface, installer, Windows binary, DPAPI integration or SQLCipher portability verification. Windows packaging remains out of scope for this backend phase.
8. **Code quality.** Current data access uses `sqlite3`, not requested SQLAlchemy 2.x; no dedicated DTO layer; type checks and complete security penetration tests remain outstanding.

The backend-completion gate must remain **not passed** until these blockers and the complete mission test matrix are resolved.

## Remote integration provenance — 2026-11-01

The recovered Phase 1 changes were compared with the actual upstream source using Git tree identity, not presumed Git ancestry. See [`INTEGRATION_CHANGELOG.md`](INTEGRATION_CHANGELOG.md). Local integration verification: Python 3.13.5; 50 unittest tests passing, 50 pytest tests passing (plus 9 subtests), compilation and Git whitespace checks passing. Local Ruff/mypy and real Windows/DPAPI/SQLCipher checks were not performed. Backend completion remains **NOT PASSED**.
