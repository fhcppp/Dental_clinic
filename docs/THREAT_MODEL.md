# Initial threat model

Assets: patient identity details, appointment history, tooth-state entries,
clinician identity, backups and executable integrity. Trust boundary:
application service -> local database file; future UI and authentication
boundary not yet constructed.

| Threat | Current mitigation | Residual risk |
|---|---|---|
| SQL injection | parametrized service queries | unsafe future code possible |
| Overlapping slot race | `BEGIN IMMEDIATE` and conflict recheck | direct DB edits bypass service rules |
| Unauthorized record read | none | **critical** |
| Laptop theft / disk extraction | none (plaintext SQLite) | **critical** |
| Forged audit identity | none; actor label supplied by caller | **critical** |
| Ransomware / lost drive | none; backups not implemented | **critical** |
| Network exfiltration by core | no network calls implemented | third-party UI/dependencies unreviewed |
| Corrupted/supplied DB | SQLite constraints, schema-version guard | broader integrity verification missing |

Security release gate: authentication + authorization, encrypted storage with
reviewed key lifecycle, integrity-protected audit, backup/restore tests,
privilege separation, dependency review, threat review and manual validation.
