# Security status — NOT CLEARED FOR LIVE PATIENT RECORDS

**The SQLite database is plaintext.** There is no SQLCipher, Windows DPAPI key lifecycle, full-database encryption, secure admin recovery procedure or threat-reviewed packaging. Do not put real clinical data into this build.

Implemented primitives: Argon2id password hashing (`argon2-cffi`), random session tokens stored only as SHA-256 digests, session age and idle limits, initial administrator bootstrap, user deactivation, static role permissions, AES-256-GCM encrypted attachments, filename randomization, MIME magic checks, size limits, encrypted backups and hash-verified restore staging. These primitives are not yet universally enforced by the original `PatientService`, `AppointmentService`, `OdontogramService`, `MedicalService`, `ClinicalService` or `FinanceService`, whose `actor_id` arguments are caller-controlled. **Do not treat this as safe RBAC** until services derive identity from verified sessions.

Encrypted attachment keys are supplied externally and are not persisted by the vault. If lost, encrypted attachments cannot be decrypted. Secure Windows key generation, rotation, DPAPI wrapping, externally anchored audit integrity and recovery must be implemented and tested before production. The same AES key must never be committed to Git. Backups use scrypt-derived AES-256-GCM encryption from a passphrase supplied at use time, not remote storage.

Audit events store event metadata, not clinical details or passwords. Schema v3 adds an HMAC chain, atomic insert signing and startup verification; without protected production keys and an external anchor it cannot defeat total database rollback or a fully privileged attacker. Manual backups do not replace an independently tested disaster-recovery plan.

## Security update — 2026-11-01

`ClinicDatabase` now fails closed by default and accepts plaintext only with `allow_insecure_plaintext_for_tests=True`, which must never be used with real patient information. The separate data-key envelopes, scrypt recovery envelope and DPAPI provider interface are implemented in `security/keys.py`; these are not integrated with live SQLite or all services. SQLCipher/Windows verification is pending. The prior v2 audit design was unsigned; schema v3 adds a development-only keyed audit chain, not a production-validated solution. See ADRs 0005–0008 and the production acceptance report.

### Integration verification boundary

The integration preserves the existing security implementation and its shortcomings. The recovered security tests passed on Linux, but the database is still not encrypted at rest, key envelopes are not wired to production SQLCipher, and service-layer actor IDs are still caller-controllable. No real patient information may be used. The comparison and test provenance are recorded in [`INTEGRATION_CHANGELOG.md`](INTEGRATION_CHANGELOG.md); Ruff/mypy and Windows behavior remain unverified locally.

## v3 hardening evidence and boundaries

New: canonical HMAC-SHA256 audit chain with insert triggers, startup
verification, historic-event backfill, and concurrency/rollback tests.
An audit key can be derived from a protected master via HKDF. The public
constant key is used only in the explicit synthetic SQLite test mode and
provides no real tamper protection. Full truncation cannot be detected
without an external anchor. Login now tracks SHA-256 username fingerprints,
15-second progressive delays starting after five failures (15-minute cap),
generic username/password errors, and resets on success.

**Still unsafe for patient data:** no SQLCipher backend, no Windows DPAPI
validation, unauthenticated legacy business services, incomplete recovery
and backup activation. Review PRODUCTION_READINESS.md before any release.
