# Security status — NOT CLEARED FOR LIVE PATIENT RECORDS

**The SQLite database is plaintext.** There is no SQLCipher, Windows DPAPI key lifecycle, full-database encryption, secure admin recovery procedure or threat-reviewed packaging. Do not put real clinical data into this build.

Implemented primitives: Argon2id password hashing (`argon2-cffi`), random session tokens stored only as SHA-256 digests, session age and idle limits, initial administrator bootstrap, user deactivation, static role permissions, AES-256-GCM encrypted attachments, filename randomization, MIME magic checks, size limits, encrypted backups and hash-verified restore staging. These primitives are not yet universally enforced by the original `PatientService`, `AppointmentService`, `OdontogramService`, `MedicalService`, `ClinicalService` or `FinanceService`, whose `actor_id` arguments are caller-controlled. **Do not treat this as safe RBAC** until services derive identity from verified sessions.

Encrypted attachment keys are supplied externally and are not persisted by the vault. If lost, encrypted attachments cannot be decrypted. Secure Windows key generation, rotation, DPAPI wrapping, tamper evidence and recovery must be implemented and tested before production. The same AES key must never be committed to Git. Backups use scrypt-derived AES-256-GCM encryption from a passphrase supplied at use time, not remote storage.

All audit events store event metadata, not clinical details or passwords, but there is no tamper-evident chain. The local process and SQLite file owner can modify audit records. Manual backups do not replace an independently tested disaster-recovery plan.
