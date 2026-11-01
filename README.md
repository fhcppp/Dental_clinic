# Dental Clinic — offline Python backend (development)

**Backend progress milestone v0.2.0 + Phase 1 security clarifications, not production-ready.** Single-workstation dental clinic service library, designed for a future Windows PySide6 interface. **Do not use with real patient records.** The underlying SQLite database remains unencrypted and authorization is not integrated end to end.

## Implemented

- SQLite schema versions 1→2, additive migration preserving existing records, foreign keys and transaction rollback.
- Patient directory, archival, structured demographics, date-of-birth/approximate-age support, profile revisions and duplicate candidates.
- Append-only medical conditions, allergies, medications and alerts.
- FDI codes, validated individual tooth surfaces, append-only dental observations and tooth history.
- Dentist records, treatment catalogue, clinical visits, restorative details, staged endodontic details, completed/amended treatment history and planned-versus-actual separation.
- Timezone-aware appointment booking, practitioner/patient/room overlap protection.
- Decimal-safe invoices, invoice line items, partial payments, refunds, outstanding balances and basic CSV reporting.
- **Development security primitives only:** Argon2id credential hashing, local sessions and roles, AES-256-GCM encrypted attachments and passphrase-encrypted backup/verify/restore-to-new-location.

## Technology / layout

Python 3.11+, standard-library SQLite (`sqlite3`), argon2-cffi and cryptography. Services are under `src/dental_clinic/`; synthetic unit/integration/security tests are under `tests/`. No HTTP server, cloud database, online authentication, telemetry or frontend.

The mission requests SQLAlchemy 2.x and a fully layered architecture; these are **not yet implemented**. The existing raw SQLite persistence layer was retained to avoid unsafe schema replacement. See `docs/BACKEND_COMPLETION_REPORT.md` for the precise list of implemented and unfinished work.

## Development

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover -s tests -v
python -m pytest -q
ruff check .
mypy src/dental_clinic --ignore-missing-imports
```

The backend itself runs without the internet after required dependencies are installed locally. For a completely offline installation, prepackage trusted dependencies in a wheelhouse.

## Minimal synthetic example

```python
from datetime import UTC, datetime, timedelta
from dental_clinic import ClinicDatabase, PatientService, AppointmentService

db = ClinicDatabase('synthetic.sqlite3', allow_insecure_plaintext_for_tests=True)
db.initialize()
patient = PatientService(db).create('Synthetic Example')
start = datetime(2026, 11, 3, 10, tzinfo=UTC)
AppointmentService(db).schedule(patient.id, 'dentist-1', start, start + timedelta(minutes=30))
```

Never commit generated SQLite databases, logs, attachments, backups, credentials or real patient information. The source repository is for code and development history only. License: not selected yet; do not assume redistribution rights.

## Updated protection requirements

Plaintext SQLite is now rejected on normal startup; explicit `allow_insecure_plaintext_for_tests=True` must only be used for synthetic tests. The live database is **NOT ENCRYPTED**. No real patients can be stored safely. `settings.ClinicSettings(timezone='Europe/Berlin', currency='EUR')` is an *example of explicit choices*, not a permanent region default. The clinic must choose its own timezone and currency; first-time setup persistence is not yet implemented.

Versioned AES-256-GCM envelope keyrings provide separate random `database`, `attachments` and `backups` data keys; a portable scrypt-based recovery envelope can recover the master key using a user-supplied password. Windows DPAPI and SQLCipher compatibility remain unverified. Runtime integration, key rotation, and full authenticated authorization are still blockers. See `docs/adr/0005-*` through `0007-*`, `docs/windows_verification/`, and `docs/BACKEND_ACCEPTANCE_REPORT.md`.
