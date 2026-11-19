# Backend Phase 1 integration changelog

Date: 2026-11-01
Target: `fhcppp/Dental_clinic`, `feat/backend-foundation`, existing PR #1
Verified original remote commit: `9586482fa8d9592af6e96b417cf0d4eaa49c97ed`
Verified original remote tree: `0b166153f09f7cc12a9b331f797485f56e4a0dcf`

## Provenance and comparison

Recovered implementation: `/mnt/data/dental_work/Dental_clinic` (locally reconstructed repository).
Its synthetic reconstruction commit `561eb8f` has the **identical Git tree SHA** as the actual remote base. The local commits `ee1ce5f` and `14136ff` represent the recovered changes, but do **not** share real Git ancestry with the upstream base. Integration must therefore use a new commit whose parent is the verified remote head; never graft or force-push the synthetic commits.

The recovery changes comprise **21 paths: 11 additions, 10 modifications, zero deletions**. Existing patient IDs, migrations v1/v2, and pre-existing tests are preserved. Changes are classified below.

## Already implemented remotely — retained

- `.github/workflows/ci.yml`, `.gitignore`, `pyproject.toml`: unchanged. The existing CI workflow remains the only workflow.
- Existing `src/dental_clinic/{services,medical,clinical,finance,auth,attachments,backup,reporting,fdi,models,errors}.py` and their interfaces: retained without unrelated rewrites.
- The existing `PRAGMA user_version` v1→v2 migration, clinical/patient/financial tables, existing FDI functionality, and appointment scheduling tests: preserved.

## New implementation (added paths)

- `src/dental_clinic/security/__init__.py`, `src/dental_clinic/security/keys.py`: separately purposed wrapped data keys, recovery-password envelope, test key provider and Windows DPAPI adapter with mocked verification only.
- `src/dental_clinic/settings.py`: validated clinic timezone/currency and configurable defaults.
- `tests/test_phase1_safety.py`: migration, startup, envelope integrity and settings tests.
- `docs/BACKEND_GAP_ANALYSIS.md`, `docs/BACKEND_ACCEPTANCE_REPORT.md`: phased risk inventory and evidence-based completion statuses.
- `docs/adr/0005-clinic-configuration-and-security-defaults.md`, `docs/adr/0006-key-envelopes-and-production-db-gate.md`, `docs/adr/0007-migration-integrity-and-audit.md`: decisions and explicit limits.
- `docs/windows_verification/README.md`, `docs/windows_verification/verify_windows.py`: Windows checks requiring execution on real Windows.
- `docs/INTEGRATION_CHANGELOG.md`: this comparison and integration record.

## Improvements to existing implementation (modified paths)

- `src/dental_clinic/db.py`: explicit fail-closed default for plaintext SQLite, test-only plaintext opt-in and pre-migration safety snapshot/rollback behavior; **no claim of production database encryption**.
- `tests/test_backend.py`, `tests/test_clinical_expansion.py`, `tests/test_security_recovery.py`: adapt synthetic test database setup to explicit insecure-test flag while retaining original assertions.
- `README.md`, `docs/ARCHITECTURE.md`, `docs/BACKEND_COMPLETION_REPORT.md`, `docs/BACKUP_AND_RESTORE.md`, `docs/DATABASE_DESIGN.md`, `docs/SECURITY.md`: describe the actual Phase 1 boundaries and remaining work.

## Conflicting implementations and resolution

- **No source-file content conflicts** at comparison time: remote tree exactly matches the preserved reconstruction base. Existing migration versions are not replaced; no second migration system is introduced.
- The new fail-closed default changes `ClinicDatabase` initialization behavior by design. Existing synthetic tests and documented examples explicitly opt into insecure SQLite. Production data access remains blocked until an encrypted database implementation is available.
- The recovered Git history is synthetic and must **not** be pushed as unrelated history. The integrated commit's parent must be the actual current remote commit.

## Missing / unrecoverable vs. unfinished

- **Missing or unrecoverable source:** none identified from the prior local Phase 1 implementation. The full local recovered source was present; all 49 pre-integration tracked paths were accessible.
- **Still unfinished requirements (not lost code):** SQLCipher database-at-rest encryption, verified Windows DPAPI, end-to-end session-bound authorization and audit authorship, tamper-evident hash chain, progressive login throttling, encrypted-key rotation, fully automated backups and retention, working-hours schedule, and additional integration/Windows tests. The backend is NOT production-ready.

## Verification provenance

- **Local Linux:** Python 3.13.5; `PYTHONPATH=src python -m unittest discover -s tests -v`: 50 passed; `PYTHONPATH=src python -m pytest -q tests`: 50 passed plus 9 subtests; `python -m compileall -q src tests docs/windows_verification`: passed; `git diff --check`: passed.
- **Not executed locally:** Ruff and mypy (not installed); real Windows x64/DPAPI/SQLCipher; full offline network-blocked test.
- **GitHub CI for the integration:** report the actual result separately once GitHub runs it. Historical CI results do not establish current integration success.

This document compares recoverable implemented source, not promises of future development. See `BACKEND_ACCEPTANCE_REPORT.md` for requirement-by-requirement statuses.
