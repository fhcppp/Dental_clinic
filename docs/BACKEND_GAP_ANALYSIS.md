# Backend gap analysis and phased resume checklist

Verified against `feat/backend-foundation` HEAD `9586482fa8d9592af6e96b417cf0d4eaa49c97ed` (2026-11-01). This checkout was reconstructed from a previous source ZIP; `git clone` failed because DNS resolution of github.com is disabled in this container. The ZIP's db.py and auth.py Git blob hashes matched the remote branch. The local reconstructed Git root is **not** the original remote Git history. Do not push its synthetic baseline commit.

## Phase 0 – baseline inspection: DONE

- Existing SQLite `PRAGMA user_version` v1→v2; ~25 relational tables and 37 tests; no SQLAlchemy or PySide6.
- Local baseline checks: `PYTHONPATH=src python -m unittest discover -s tests -q` => 37 OK, and `PYTHONPATH=src python -m pytest -q tests` => 37 passed.
- Ruff/mypy executable tools are not installed in this sandbox. Neither was locally executed for baseline. No current GitHub CI invocation has been made for this task; prior CI results do not verify newly changed files.
- Existing PR #1 is open/draft; do not merge. Remote HEAD verified as above.

## Implementation assessment

| Area | State | Shortfall |
|---|---|---|
| Patients / medical history | PARTIAL | caller-controlled actors, incomplete authorization and identity linkage |
| Teeth / visits / procedures / plans | PARTIAL | some checks live in application code only; no per-action service authorization |
| Scheduling | PARTIAL | lacks working-hours calendar and lifecycle transitions |
| Finance | PARTIAL | no clinic currency setup, item allocation and full authorization |
| Login | PARTIAL | 12-char min, 15-min idle, 8-h expiry exist; progressive throttling and trusted context missing |
| Audit | PARTIAL | metadata audit exists but mutable; no chained verification, no fail-closed guard at all endpoints |
| Attachments | PARTIAL | encrypted, but default 16 MiB and no TIFF/DICOM evaluation, caller-supplied actor |
| Database encryption | NOT DONE | plaintext sqlite3 in current baseline; SQLCipher/Windows compatibility unverified |
| Recovery / backup | PARTIAL | manual encrypted snapshot verified, no retention/scheduling/staged activation |
| Reporting | PARTIAL | limited report types and no CSV formula-injection policy audit |
| Windows | UNVERIFIED | no native Windows x64/DPAPI/SQLCipher testing performed |

## Architectural risks

1. Authenticated actor identity is not propagated into legacy patient, clinical, and financial services; `actor_id` is spoofable.
2. Audit rows are mutable by anyone with database file access. Audit metadata and sensitive mutations must be atomic.
3. Plain SQLite must never be opened as an undisclosed production fallback.
4. Migration preflight needs a consistent backup of existing schema before executing DDL; retain original rows and identifiers.
5. Existing SQL is embedded in services rather than confined to infrastructure/repositories; refactor incrementally, not cosmetically.
6. Windows native encryption and packaging are not verified and cannot be claimed as complete.

## Phase checkpoints

- [x] **0:** inspect, run baseline tests, write this gap analysis.
- [ ] **1 (PARTIAL):** migration snapshot/rollback and envelope recovery tested; SQL isolation, SQLCipher deployment and native DPAPI integration remain open.
- [ ] **2:** trusted identity, complete service authorization, tamper-evident atomic audit.
- [ ] **3:** patient and medical history under authorized service context.
- [ ] **4:** complete dental, visits, treatments and plan integrity.
- [ ] **5:** scheduling and DST/room/working-hour integrity.
- [ ] **6:** currency-aware financial accounting and auditing.
- [ ] **7:** attachment/backup/restore lifecycle and key rotation.
- [ ] **8:** audited reports, secure CSV and optional PDF.
- [ ] **9:** full lifecycle/offline test, real Windows verification and acceptance gate.

Resume at first unchecked phase; do not start frontend.

## Phase 1 interim evidence (2026-11-01)

- 50 unit/integration tests passed, including v1 migration rollback and fail-closed plaintext startup.
- Added ADR 0005 (configuration defaults), ADR 0006 (separate key envelopes and portable recovery), and ADR 0007 (atomic migration and proposed audit serialization).
- Added an explicit `ClinicSettings` domain settings object but not an authorized persistent first-time setup workflow.
- Added `WindowsDPAPIKeyProvider` behind a runtime platform check, not Windows-verified. SQLCipher bindings absent; production data use is still forbidden.
- See `docs/BACKEND_ACCEPTANCE_REPORT.md` for every DONE/PARTIAL/NOT DONE/UNVERIFIED decision and provenance.
