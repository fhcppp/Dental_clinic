# Backend production acceptance report — NO-GO

Date: 2026-11-01. Development snapshot, not a production release.

## Evidence provenance and commands

- **Existing remote baseline, read-only GitHub connector inspection:**
  `feat/backend-foundation` at `db9d41d2739d7f4b0139c2d955e4642990735aff`,
  existing PR #1 open/draft/unmerged. The preserved 50-file integrated ZIP
  produced Git tree `15624dbb49c562780bbb3bc14882b6b85512e26e`,
  exactly matching the remote commit's complete tree SHA.
- **Local Linux:** Python 3.13.5; code extracted from the preserved published
  source ZIP and changed in a separate disposable workspace.
- `PYTHONPATH=src python -m unittest discover -s tests -q`: **65 passed**.
- `PYTHONPATH=src python -m pytest -q`: **65 passed, 14 subtests passed**.
- `python -m compileall -q src tests`: **passed**.
- `python -m pip wheel --no-deps --no-build-isolation -w ... .`:
  **passed**, development wheel `dental_clinic-0.2.0-py3-none-any.whl` built locally;
  this is NOT a Windows/clinical release candidate.
- `ruff check .` and `mypy src/dental_clinic`: **NOT EXECUTED**. Ruff and mypy
  were not installed; pip install failed with DNS resolution failures.
- **GitHub CI for these new changes: NOT EXECUTED**. No new remote push or
  workflows have been triggered for this partial milestone.
- **Actual Windows verification:** NONE. DPAPI was mock-tested previously on
  Linux; this is not evidence of Windows behavior.
- All tests use synthetic data under an explicit insecure SQLite test flag.

## Acceptance matrix

Status is one of DONE, PARTIAL, NOT DONE, UNVERIFIED. DONE means the specifically
scoped behavior was actually verified, not merely that a file exists.

| Requirement | Status | Evidence / remaining work |
|---|---|---|
| Preserve existing source and records | DONE | New schema v3 is additive; baseline 50 tests preserved and passing, v1/v2 migration tests; local unittest 65/65 |
| Offline Python backend without frontend | DONE | All modules are local Python/SQLite; `python -m unittest` 65/65; no server or UI introduced |
| Fresh schema initialization | DONE | `tests/test_backend.py`, local unittest 65/65, schema version 3 |
| v1→v2→v3 migration and backup in synthetic mode | DONE | `tests/test_phase1_safety.py`, `tests/test_audit_auth_hardening.py`, explicit failure rollback and existing-record tests; local unittest 65/65 |
| Production migration backup encryption | NOT DONE | Current snapshot method writes plaintext `.sqlite3` in TEST mode only; no production SQLCipher provider |
| Production database encryption / wrong-key rejection | NOT DONE | `src/dental_clinic/db.py` fails closed; SQLCipher unavailable, not installed or tested |
| Windows SQLCipher, DPAPI and packaging | UNVERIFIED | No Windows host/runner validation in this session; `docs/windows_verification/` instructions only |
| Master-key recovery envelope | PARTIAL | `src/dental_clinic/security/keys.py`; local synthetic recovery tests; no clean Windows recovery |
| Purpose-specific audit key derivation | DONE | `derive_audit_key` HKDF domain separation test in `test_audit_auth_hardening.py`; local unittest 65/65 |
| Key rotation / external checkpoint | NOT DONE | No rotation workflow, trusted anti-truncation anchor or independent historical key management |
| Login and password hashing | PARTIAL | Argon2id, hashed sessions, 12-character password check; `test_security_recovery.py`; incomplete admin recovery |
| Five failures and progressive delay | DONE | `test_fifth_failure_triggers_delay_without_permanent_lockout` and unknown-account error test; local unittest 65/65 |
| Idle and absolute session expiration | PARTIAL | Existing 15-minute/8-hour checks; local synthetic tests, broader session lifecycle tests pending |
| Trusted actor / RBAC on all service methods | NOT DONE | Legacy `actor_id` bypasses remain in services; UI-only permissions unacceptable |
| HMAC audit canonical serialization / concurrency | PARTIAL | `src/dental_clinic/audit.py`, v3 insert trigger, concurrency/tamper/atomicity tests; public test key and no anti-truncation checkpoint |
| Patient profile, medical history | PARTIAL | Existing `medical.py`, baseline tests; unauthorized read/write paths remain |
| Dental visits, FDI, tooth observations, plans | PARTIAL | Existing `clinical.py` + tests; authorization/lifecycle gaps remain |
| Restoration and endodontic treatment | PARTIAL | Existing `clinical.py` + tests; not fully secured or operationally validated |
| Appointments, room conflicts, DST | PARTIAL | Existing scheduling tests; dentist working-hours/availability missing |
| Clinic timezone selection and persistence | PARTIAL | `settings.py` validates IANA zone but does not store authoritative clinic settings in database |
| Currency minor-unit precision and invoices | PARTIAL | `FinanceService` now requires settings, tests JPY/KWD/EUR; legacy clinical two-decimal helper and complete payment authorization remain |
| Refund and overpayment validation | PARTIAL | Existing `finance.py`, synthetic integration tests; full threat and transition tests pending |
| Configurable 25 MiB attachment bound | DONE | `src/dental_clinic/attachments.py`, `test_attachment_size_limit_can_be_set_and_fails_closed`; local unittest 65/65 |
| Attachment content validation and encryption | PARTIAL | Existing AES-GCM, magic checks; no deep format parser, full access control or DICOM support |
| Consistent encrypted backup archive | PARTIAL | Existing `backup.py`, synthetic backup tests, version 3; not production SQLCipher-integrated |
| Full atomic restore activation and retention | NOT DONE | Current `restore_to` uses two filesystem moves; retention not implemented |
| Reporting, export authorization | PARTIAL | Existing `reporting.py` CSV sanitization; RBAC not enforced |
| Production offline Windows lifecycle | UNVERIFIED | No Windows environment, signed package or clinical acceptance test |
| Ruff and mypy checks for changes | UNVERIFIED | Not installed; pip download failed DNS, no GitHub CI for changes |
| Human clinical, privacy and legal review | UNVERIFIED | No qualified external review was performed |

## Schema and security changes

Schema 2→3 adds `audit_chain` and `auth_login_attempts`. Audit events are
signed by HMAC-SHA256 within the same SQLite transaction using a connection
registered function and an insert trigger. Existing historical event IDs are
retained and signed on migration. Updates/deletes are blocked by triggers;
startup verifies the complete retained chain. Synthetic-only test key is
public and therefore not a production safeguard. Use a protected HKDF-derived
audit key for a future real encrypted database implementation.

Authentication now records bounded username-fingerprint login attempts with
non-permanent progressive delays. Finance is configured with an explicit
currency via `ClinicSettings` and tests 0/2/3 minor-unit currencies; no
implicit EUR currency remains in `FinanceService.create_invoice`.

## Final assessment

**NOT PRODUCTION READY.** Critical security and Windows acceptance criteria
remain unmet. Do not put patient data in this codebase or change the draft PR
to ready-for-review solely because the Linux tests pass.
