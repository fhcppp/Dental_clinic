# ADR 0002 — SQLite with explicit schema versioning

**Status:** Accepted for prototype, subject to encryption review (2026-11-01)

**Context:** Deployment must work without servers or internet access.

**Decision:** Use file-backed SQLite, `PRAGMA user_version`, foreign keys on
every connection and `BEGIN IMMEDIATE` for read-check-write services.

**Consequence:** Simple local durability, but the current DB is plaintext.
Production selection must include at-rest encryption, key handling and a
backup/restore lifecycle before clinic use.
