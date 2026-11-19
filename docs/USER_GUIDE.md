# User guide — developer prototype

There is no graphical interface in this milestone. The service-layer example
in the README demonstrates how to create **synthetic** test entries and slots.

- `ClinicDatabase(path).initialize()` initializes schema version 1.
- `PatientService`: `create`, `get`, `list_active`, `deactivate`.
- `AppointmentService`: `schedule`, `get`, `reschedule`, `cancel`, `list_for_patient`.
- `OdontogramService`: `set_state`, `list_for_patient`.

Appointments need timezone-aware start/end datetimes; appointments for the
same patient or practitioner cannot overlap. FDI tooth codes include 11–48
within valid quadrants and 51–85 within primary quadrants. State names are
`healthy`, `decayed`, `missing`, `restored`, and `implant`, not a complete
clinical notation system. Do not use these limited classifications to make
clinical decisions.

`ValidationError`, `NotFoundError`, and `ConflictError` are ordinary domain
errors. SQLite failure may still raise `sqlite3.Error`. Before a clinic UI is
built, specify patient-consent flows, safe deletion, clinical chart semantics,
role-specific navigation, accessibility and language requirements.

## Not for patient records

Current code is a backend-only development prototype. No authorized,
encrypted Windows clinical workflow is available yet.
