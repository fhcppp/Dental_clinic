# Local SQLite database and migration history

`PRAGMA user_version` selects the only migration mechanism. Schema v1 preserves the existing patients, appointments, tooth_records and audit_events. Schema v2 adds profile details and revisions, medical entries, dentist/room catalogues, clinical visits, tooth observations and surfaces, plans and items, treatment history and relational surfaces, restoration and endodontic details, financial records, users/sessions, encrypted-attachment metadata and tooth-state events.

## Integrity rules

- `patients.id` is stable and independent of contact numbers.
- `patients.birth_date` is authoritative when known; approximate age is stored with an explicit reference date, not as a claim of exact birth date.
- Conditions, allergies, medications, alerts, tooth observations and tooth-state events are historical records, not a single mutable string.
- `treatments` references `(visit_id, patient_id)` and plan items via composite foreign keys so a treatment cannot refer to another patient's visit or plan.
- `treatment_surfaces`, `observation_surfaces`, and `plan_item_surfaces` use rows with constrained surface codes, not arbitrary JSON.
- Finalized treatment and invoice record modifications are blocked by selected SQLite triggers. The application API enforces additional clinical validation.
- Invoices and payments use integer minor currency units. Do not store float amounts.
- Patient deletion is restricted by existing history foreign keys; archival uses active status.

All migrations are carried out transactionally by `ClinicDatabase.initialize()` and preserve v1 identifiers. Schema v2 is additive, but not yet a fully constrained production-grade clinical schema. The SQLite DB is **plaintext**. `PRAGMA foreign_keys=ON` is set per connection.
