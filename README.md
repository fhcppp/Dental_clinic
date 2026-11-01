# Dental Clinic

Offline-first dental practice desktop application **under development**. This
repository currently contains a testable, standard-library Python backend
foundation. It is **not production-ready** and must not be used with real
patients or medical data.

## Implemented features (backend only)

- Versioned, local SQLite schema; foreign keys; transactional writes.
- Create, retrieve, list and deactivate patient directory entries.
- Schedule, reschedule and cancel appointments, preventing overlaps for both
  practitioner and patient; timezone-aware input normalized to UTC.
- Validate FDI tooth numbers for 32 permanent and 20 primary teeth, and record
  basic tooth state.
- Metadata-only audit events associated with write operations (not tamper-proof).
- Automated tests using synthetic fixtures and temporary SQLite databases.

## Technology stack & offline architecture

Python 3.11+, SQLite and the Python standard library. Operations access only
local SQLite files; there are no network calls, cloud services, or telemetry.
A Windows PySide6 UI, packaging and security layers are **planned, not shipped**.
Development/CI uses GitHub, but the running backend requires no GitHub access.

## Development setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

For optional lint/type checks: `python -m pip install -e '.[dev]'`, then
`ruff check .` and `mypy src/dental_clinic --ignore-missing-imports`.
For offline installation, provision Python and the build dependencies from a
trusted local wheelhouse first; package installation is not automatically
network-isolated.

## Minimal API example (synthetic data only)

```python
from datetime import UTC, datetime, timedelta
from dental_clinic import ClinicDatabase, PatientService, AppointmentService

db = ClinicDatabase("demo.sqlite3")
db.initialize()
p = PatientService(db).create("Synthetic Example")
start = datetime(2026, 11, 3, 10, tzinfo=UTC)
AppointmentService(db).schedule(p.id, "doctor-1", start, start + timedelta(minutes=30))
```

SQLite files and their backups are ignored by Git. Do not commit or publish
patient data, secrets, real medical images, or production backups.

## Project structure

- `src/dental_clinic/`: database, models, FDI validation and services.
- `tests/`: synthetic integration tests.
- `docs/`: decisions, safety limitations, development and build roadmap.
- `.github/workflows/`: CI (development-only).

## Current status / next steps

This is **v0.1 backend foundation**, not a released clinic product. Before any
real patient data is accepted, add local authentication and role authorization,
strong encryption at rest with secure local key custody, backup/restore, audit
integrity, clinical validation, retention/erasure policy and threat-model
verification. Remaining feature work includes treatment plans, financial
modules, a PySide6 desktop interface, Windows packaging and installer tests.
See [implementation report](docs/BACKEND_IMPLEMENTATION_REPORT.md).

## License

No open-source license has been selected or granted yet. Treat this repository
as **all rights reserved** until the owner adds an explicit license.
