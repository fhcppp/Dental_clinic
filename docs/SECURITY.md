# Security posture — NOT PRODUCTION READY

## Current safeguards

The implementation uses parameterized SQL statements, strong UUID4 record
identifiers, `CHECK` constraints, enabled foreign keys, transactional writes,
fixed state enumerations, and synthetic-only tests. Audit events contain
operation metadata but no names or clinical notes. The application core does
not perform network requests or emit record data to logs.

## Unresolved blockers for real patients

1. No login, identity binding, lockout, inactivity timeout or role-based
   authorization; the `actor_id` argument is caller-controlled.
2. SQLite contents, temporary/journal data and backups are **not encrypted**.
   Encrypt at rest with a reviewed SQLCipher or equivalent design and
   Windows-appropriate key protection; do not store a hard-coded master key.
3. Audit rows are mutable by anyone with database access and have no integrity
   protection, retention rule or verified actor identity.
4. No signed software releases, authenticated update channel, malware
   assessment, penetration test or independent clinical safety evaluation.
5. No tested backup, recovery, destruction/retention or clinic privacy policy.

**Do not enter any real names, medical histories, patient photographs,
insurance numbers, imaging data or other patient information in this version.**

No claim of HIPAA, GDPR, MDR or other regulatory compliance is made.
Assessment of applicable laws and clinical-device classification requires
qualified legal/clinical review in the deployment jurisdiction.
