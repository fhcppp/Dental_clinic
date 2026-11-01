# Architecture

## Current boundaries

`ClinicDatabase` is the only persistence gateway. `PatientService`,
`AppointmentService`, and `OdontogramService` encapsulate validation and SQL.
`models.py` contains immutable read values and `fdi.py` holds tooth-number
rules. There are no HTTP endpoints, cloud APIs, background syncing, desktop
screens, or injectable secret credentials.

```
Future PySide6 screens  [NOT IMPLEMENTED]
        |
Patient / Appointment / Odontogram services [IMPLEMENTED]
        |
ClinicDatabase -> file-backed SQLite [IMPLEMENTED]
```

Calls are synchronous. Each business operation uses a fresh connection;
write transactions start with `BEGIN IMMEDIATE`, serialize overlapping
read-check-write transactions and roll back on error. UTC timestamps are
stored as fixed-width ISO 8601 strings for consistent lexicographic ordering.
The desktop's local timezone conversion belongs in the future interface.

## Current limits

The system has no authenticated user, access-control checks, encryption,
content-addressed/tamper-resistant audit trail, treatment workflows, or
Windows installer. It is an **engineering prototype only**, not an approved
clinical system. These gaps block accepting real patient data.
