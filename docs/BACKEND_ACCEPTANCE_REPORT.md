# Backend acceptance report — security clarification milestone

Date: 2026-11-01. **Overall gate: NOT PASSED. Not safe for actual patient data.**

Evidence provenance: local Linux sandbox, Python 3.13.5, source ZIP verified against the remote branch's `db.py` and `auth.py` blob hashes, remote branch head `9586482fa8d9592af6e96b417cf0d4eaa49c97ed`. `git clone` could not connect because github.com DNS resolution failed. Git operations below are on a reconstructed local source snapshot; **no new remote commit, push, PR update, or CI execution in this session**.

Local command evidence: `PYTHONPATH=src python -m unittest discover -s tests -q` (50 tests, OK), `PYTHONPATH=src python -m pytest -q tests` (50 passed), `python -m compileall -q src tests docs/windows_verification` (passes). Ruff and mypy not installed locally; record as UNVERIFIED rather than claiming success. **Actual Windows verification: NOT RUN.** Prior CI runs cannot verify this milestone.

Statuses below are exhaustive for the requirements relevant to this phased mission. DONE indicates functionality observed in this session with named test evidence, not the mere existence of a module. UNVERIFIED includes the reason/evidence of missing verification.

| Requirement | Status | Evidence or missing requirement |
|---|---|---|
| Existing baseline patient and booking tests | DONE | Local `tests/test_backend.py`, full 50-test suite passes |
| Complete patient profile, record revision and archival | PARTIAL | Existing fields/history present; direct unauthenticated service access |
| Medical conditions, allergies, medications and alerts | PARTIAL | Relational historical entries exist; actor identity is caller-supplied |
| Valid FDI number and tooth-surface domain | PARTIAL | Existing clinical tests pass; DB does not enforce all surface/tooth associations |
| Historical tooth observations | PARTIAL | Append-only rows exist; authorization incomplete |
| Separate observation, execution and plan states | PARTIAL | Separate tables present; not all transition and status rules enforced |
| Treatment catalog, restoration and endodontic canal details | PARTIAL | Existing tests pass; catalog authorization/integrity and clinical details incomplete |
| Clinical visits and matching patient relationships | PARTIAL | Composite FKs present; lifecycle and authorization incomplete |
| Treatment plans and immutable actual history | PARTIAL | Separate model and triggers present; plan transitions and finalized amendments incomplete |
| Scheduling conflicts and working hours | PARTIAL | Existing overlap/concurrency tests pass; working hours and statuses missing |
| Authn/RBAC and trusted actor context | PARTIAL | Argon2id login exists; arbitrary actor_id still accepted in services |
| 12-character password, 15-minute idle, 8-hour lifetime | PARTIAL | Constants exist; no end-to-end authorization enforcement or clock/session security review |
| Login throttling after 5 failures + admin recovery | NOT DONE | No progressive delays and recovery implementation |
| Deny-by-default RBAC and assistant grants | NOT DONE | Existing matrix not applied consistently; no explicit grants |
| Explicit first-setup clinic timezone and currency | PARTIAL | `settings.ClinicSettings` validates required IANA zone and supported currency; no saved first-run setup |
| Currency minor-unit calculations (0, 2, 3 digits) | DONE | Local `test_explicit_timezone_and_currency_precision`, `test_setup_rejects_unselected_and_invalid_values`; settings conversion only, not wired to FinanceService |
| Configurable 25 MiB attachment limit | PARTIAL | Settings default tested; existing vault still uses 16 MiB, not injected |
| Configurable 7-daily / 4-weekly retention | PARTIAL | Settings default tested; scheduler and pruning not implemented |
| Three independent random purpose keys | DONE | Local `test_independent_purpose_keys_and_roundtrip`; keys not yet connected to live services |
| Versioned encrypted keyring and password recovery envelope | DONE | Local `test_tamper_detection_and_key_version`, `test_independent_recovery_password_roundtrip`, `test_recovery_rejects_modified_parameters_before_derive` |
| Real Windows DPAPI key protection | UNVERIFIED | Linux guard tested by `test_provider_production_guards`; no native Windows x64 test or package validation |
| Database at-rest encryption with SQLCipher | NOT DONE | No SQLCipher driver available or integrated; production startup explicitly blocked |
| Plaintext production startup prohibited | DONE | Local `test_plaintext_is_explicit_opt_in` proves rejection before DB file created |
| Automatic pre-migration snapshot and rollback | DONE | Local `test_migration_preserves_v1_patient_and_backup`, `test_failed_migration_rolls_back_original_and_keeps_backup` |
| One migration authority and v1 IDs preserved | DONE | Tests above, v1→v2 `PRAGMA user_version` in transaction; downgrade unsupported |
| Independent recovery on a second real workstation | UNVERIFIED | Portable `recover_master` is tested locally; actual second-device recovery not run |
| Key rotation across stored records | NOT DONE | Versioned keyring exists; operational rotation not implemented |
| Tamper-evident canonical audit chain | NOT DONE | Canonical format specified in ADR 0007; no implementation or concurrency tests |
| Atomic sensitive writes and audit events | PARTIAL | Existing `_audit` inside some transactions; no trusted identity or universal fail-closed audit |
| MIME/magic validation + optional DICOM evaluation | PARTIAL | PDF/JPEG/PNG magic prefixes exist; TIFF/DICOM evaluation not complete |
| Attachment encryption, safe paths and linkage | PARTIAL | Existing vault integration tests pass; key provider and authorization not wired |
| Backup encryption and separate-location restore | PARTIAL | Existing tests pass; versioned keyring integration, schedule, retention and safe activation missing |
| Reporting and safe CSV/PDF export | PARTIAL | Existing CSV/reporting exists; permission and CSV-injection policy incomplete; PDF not implemented |
| Complete end-to-end lifecycle test | NOT DONE | No single complete lifecycle test through all stages |
| Offline network-blocked end-to-end verification | UNVERIFIED | Existing modules are offline-oriented; no network-blocked full suite executed |
| Ruff + mypy for these changes | UNVERIFIED | Neither tool installed in this sandbox; GitHub CI not executed for this milestone |
| Native Windows SQLCipher, DPAPI and packaging | UNVERIFIED | `docs/windows_verification/verify_windows.py` provided; not run on Windows |
| Fully integrated backend / production readiness | NOT DONE | Critical blockers remain, including DB encryption, session authorization and audit chain |
| No frontend started | DONE | Local source file inventory contains no PySide6 frontend modules |

## Resume point

Phase 0 completed. Phase 1 **PARTIAL**: fail-closed startup, pre-migration backups, independent key envelopes, portable recovery envelope and explicit settings model implemented. SQLCipher integration, service SQL isolation and real Windows DPAPI verification remain open. **Continue Phase 1, then Phase 2; do not begin frontend.**
