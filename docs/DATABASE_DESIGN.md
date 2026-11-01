# Database design (schema 1)

SQLite `PRAGMA user_version` tracks migrations. `ClinicDatabase.initialize()`
is idempotent; unknown newer schema versions fail closed. Schema v1 is applied
in a single write transaction, with foreign keys enabled on each connection.

| Table | Purpose | Invariants |
|---|---|---|
| `patients` | basic directory | UUID string key, nonempty name, active flag |
| `appointments` | visit slots | patient FK, start < end, scheduled/cancelled |
| `tooth_records` | basic FDI state | (patient, FDI) key, fixed state enumeration |
| `audit_events` | metadata-only activity | timestamp, actor label, action, subject reference |

**Conflict algorithm:** An active appointment conflicts when
`existing.start < proposed.end AND existing.end > proposed.start`, and shares
either patient or practitioner. `BEGIN IMMEDIATE` ensures two instances of
these services cannot both complete overlapping inserts; no concurrent
alternative-writer bypass is supported. Boundary-touching appointments are
allowed. Cancellations free the slot. Cancelled appointments cannot be
rescheduled; patients with scheduled appointments cannot be deactivated.

**Time:** The service requires aware datetimes, normalizes to UTC and limits a
slot to 8 hours. It makes no assumption about office hours, holidays,
appointment recurrence, or practitioners' schedules.

This schema is **not encrypted**. Plan future migrations, backups, locking,
retention and compatibility prior to production use. Editing the schema by
hand risks bypassing service invariants.
