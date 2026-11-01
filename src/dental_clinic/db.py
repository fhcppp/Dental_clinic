"""Versioned SQLite schema and explicitly bounded write transactions.

IMPORTANT: SQLite is not encrypted at rest here. Use synthetic data only until
production authentication, authorization, and encryption are implemented.
"""

import os
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

SCHEMA_VERSION = 2
SCHEMA_V1 = (
    """CREATE TABLE patients (
        id TEXT PRIMARY KEY,
        full_name TEXT NOT NULL CHECK(length(trim(full_name)) BETWEEN 1 AND 200),
        birth_date TEXT,
        phone TEXT,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
        created_utc TEXT NOT NULL
    )""",
    """CREATE TABLE appointments (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        practitioner_id TEXT NOT NULL CHECK(length(trim(practitioner_id)) BETWEEN 1 AND 100),
        start_utc TEXT NOT NULL,
        end_utc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('scheduled', 'cancelled')),
        CHECK(start_utc < end_utc)
    )""",
    """CREATE INDEX idx_appointments_practitioner_interval
       ON appointments(practitioner_id, start_utc, end_utc)""",
    """CREATE INDEX idx_appointments_patient_interval
       ON appointments(patient_id, start_utc, end_utc)""",
    """CREATE TABLE tooth_records (
        patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        fdi_code INTEGER NOT NULL,
        state TEXT NOT NULL CHECK(state IN
            ('healthy', 'decayed', 'missing', 'restored', 'implant')),
        updated_utc TEXT NOT NULL,
        PRIMARY KEY(patient_id, fdi_code)
    )""",
    """CREATE TABLE audit_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_utc TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        action TEXT NOT NULL,
        subject_type TEXT NOT NULL,
        subject_id TEXT NOT NULL
    )""",
)


# Schema v2 is strictly additive: existing v1 records and identifiers are preserved.
# All changes use the single PRAGMA user_version migration mechanism.
SCHEMA_V2 = (
    """CREATE TABLE clinic_rooms (
        id TEXT PRIMARY KEY, display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
         CHECK(active IN (0,1))
    )""",
    "ALTER TABLE appointments ADD COLUMN room_id TEXT REFERENCES clinic_rooms(id) ON DELETE RESTRICT",
    "CREATE INDEX idx_appointments_room_interval ON appointments(room_id, start_utc, end_utc)",
    "ALTER TABLE patients ADD COLUMN first_name TEXT",
    "ALTER TABLE patients ADD COLUMN last_name TEXT",
    "ALTER TABLE patients ADD COLUMN gender TEXT",
    "ALTER TABLE patients ADD COLUMN email TEXT",
    "ALTER TABLE patients ADD COLUMN secondary_phone TEXT",
    "ALTER TABLE patients ADD COLUMN address TEXT",
    "ALTER TABLE patients ADD COLUMN emergency_name TEXT",
    "ALTER TABLE patients ADD COLUMN emergency_phone TEXT",
    "ALTER TABLE patients ADD COLUMN administrative_notes TEXT",
    "ALTER TABLE patients ADD COLUMN estimated_age INTEGER",
    "ALTER TABLE patients ADD COLUMN age_reference_date TEXT",
    """CREATE TABLE patient_profile_revisions (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        recorded_utc TEXT NOT NULL, actor_id TEXT NOT NULL,
        old_full_name TEXT NOT NULL, old_birth_date TEXT, old_phone TEXT,
        old_first_name TEXT, old_last_name TEXT, old_gender TEXT, old_email TEXT,
        old_secondary_phone TEXT, old_address TEXT, old_emergency_name TEXT,
        old_emergency_phone TEXT, old_administrative_notes TEXT,
        old_estimated_age INTEGER, old_age_reference_date TEXT
    )""",
    """CREATE TABLE medical_entries (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        category TEXT NOT NULL CHECK(category IN ('condition', 'allergy', 'medication', 'alert')),
        label TEXT NOT NULL CHECK(length(trim(label)) > 0),
        status TEXT NOT NULL CHECK(length(trim(status)) > 0),
        reaction TEXT, severity TEXT, dosage TEXT, frequency TEXT, route TEXT,
        diagnosed_on TEXT, start_on TEXT, end_on TEXT, last_reviewed_on TEXT,
        prescriber TEXT, notes TEXT, recorded_utc TEXT NOT NULL,
        recorded_by TEXT NOT NULL, supersedes_id TEXT REFERENCES medical_entries(id) ON DELETE RESTRICT,
        UNIQUE(id, patient_id)
    )""",
    "CREATE INDEX idx_medical_patient_history ON medical_entries(patient_id, category, recorded_utc)",
    """CREATE TABLE dentists (
        id TEXT PRIMARY KEY, display_name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
           CHECK(active IN (0, 1))
    )""",
    """CREATE TABLE clinical_visits (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        dentist_id TEXT NOT NULL REFERENCES dentists(id) ON DELETE RESTRICT,
        appointment_id TEXT REFERENCES appointments(id) ON DELETE RESTRICT,
        visit_utc TEXT NOT NULL, start_utc TEXT, end_utc TEXT,
        chief_complaint TEXT, clinical_notes TEXT, diagnosis TEXT, followup_notes TEXT,
        status TEXT NOT NULL CHECK(status IN ('open', 'finalized')),
        UNIQUE(id, patient_id)
    )""",
    """CREATE TABLE procedure_catalog (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
    )""",
    """CREATE TABLE tooth_observations (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        visit_id TEXT, dentist_id TEXT NOT NULL REFERENCES dentists(id) ON DELETE RESTRICT,
        fdi_code INTEGER NOT NULL CHECK((fdi_code / 10 BETWEEN 1 AND 4 AND fdi_code % 10 BETWEEN 1 AND 8)
          OR (fdi_code / 10 BETWEEN 5 AND 8 AND fdi_code % 10 BETWEEN 1 AND 5)),
        condition TEXT NOT NULL, observed_utc TEXT NOT NULL, clinical_note TEXT,
        supersedes_id TEXT REFERENCES tooth_observations(id) ON DELETE RESTRICT,
        FOREIGN KEY(visit_id, patient_id) REFERENCES clinical_visits(id, patient_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE observation_surfaces (
        observation_id TEXT NOT NULL REFERENCES tooth_observations(id) ON DELETE RESTRICT,
        surface TEXT NOT NULL CHECK(surface IN
          ('mesial', 'distal', 'occlusal', 'incisal', 'buccal', 'lingual', 'palatal')),
        PRIMARY KEY(observation_id, surface)
    )""",
    """CREATE TABLE treatment_plans (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        dentist_id TEXT NOT NULL REFERENCES dentists(id) ON DELETE RESTRICT,
        created_utc TEXT NOT NULL, title TEXT NOT NULL,
        UNIQUE(id, patient_id)
    )""",
    """CREATE TABLE treatment_plan_items (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL,
        plan_id TEXT NOT NULL, procedure_id TEXT NOT NULL REFERENCES procedure_catalog(id) ON DELETE RESTRICT,
        dentist_id TEXT NOT NULL REFERENCES dentists(id) ON DELETE RESTRICT,
        fdi_code INTEGER, priority TEXT, estimated_minor INTEGER CHECK(estimated_minor >= 0),
        planned_on TEXT, explanation TEXT, status TEXT NOT NULL DEFAULT 'proposed'
          CHECK(status IN ('proposed', 'accepted', 'rejected', 'scheduled',
                         'in_progress', 'completed', 'cancelled')),
        FOREIGN KEY(plan_id, patient_id) REFERENCES treatment_plans(id, patient_id) ON DELETE RESTRICT,
        UNIQUE(id, patient_id)
    )""",
    """CREATE TABLE plan_item_surfaces (
        plan_item_id TEXT NOT NULL REFERENCES treatment_plan_items(id) ON DELETE RESTRICT,
        surface TEXT NOT NULL CHECK(surface IN
          ('mesial', 'distal', 'occlusal', 'incisal', 'buccal', 'lingual', 'palatal')),
        PRIMARY KEY(plan_item_id, surface)
    )""",
    """CREATE TABLE treatments (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL, visit_id TEXT NOT NULL,
        dentist_id TEXT NOT NULL REFERENCES dentists(id) ON DELETE RESTRICT,
        procedure_id TEXT NOT NULL REFERENCES procedure_catalog(id) ON DELETE RESTRICT,
        plan_item_id TEXT, fdi_code INTEGER, performed_utc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft', 'completed', 'voided')),
        notes TEXT, materials TEXT, anesthesia TEXT, followup TEXT,
        actual_minor INTEGER CHECK(actual_minor >= 0),
        amendment_of TEXT REFERENCES treatments(id) ON DELETE RESTRICT,
        FOREIGN KEY(visit_id, patient_id) REFERENCES clinical_visits(id, patient_id) ON DELETE RESTRICT,
        FOREIGN KEY(plan_item_id, patient_id) REFERENCES treatment_plan_items(id, patient_id) ON DELETE RESTRICT,
        UNIQUE(id, patient_id)
    )""",
    """CREATE TABLE treatment_surfaces (
        treatment_id TEXT NOT NULL REFERENCES treatments(id) ON DELETE RESTRICT,
        surface TEXT NOT NULL CHECK(surface IN
          ('mesial', 'distal', 'occlusal', 'incisal', 'buccal', 'lingual', 'palatal')),
        PRIMARY KEY(treatment_id, surface)
    )""",
    """CREATE TABLE restoration_details (
        treatment_id TEXT PRIMARY KEY REFERENCES treatments(id) ON DELETE RESTRICT,
        category TEXT, material TEXT, cavity_class TEXT, extent TEXT, shade TEXT, note TEXT
    )""",
    """CREATE TABLE endodontic_stages (
        id TEXT PRIMARY KEY, treatment_id TEXT NOT NULL REFERENCES treatments(id) ON DELETE RESTRICT,
        stage TEXT NOT NULL, notes TEXT, recorded_utc TEXT NOT NULL,
        instrumentation TEXT, irrigation TEXT, obturation_method TEXT, obturation_material TEXT
    )""",
    """CREATE TABLE endodontic_canals (
        id TEXT PRIMARY KEY, stage_id TEXT NOT NULL REFERENCES endodontic_stages(id) ON DELETE RESTRICT,
        canal TEXT NOT NULL, working_length_mm TEXT,
        CHECK (working_length_mm IS NULL OR CAST(working_length_mm AS REAL) > 0)
    )""",
    """CREATE TABLE invoices (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        currency TEXT NOT NULL, issued_utc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('draft', 'finalized')),
        UNIQUE(id, patient_id)
    )""",
    """CREATE TABLE invoice_items (
        id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
        description TEXT NOT NULL, quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit_minor INTEGER NOT NULL CHECK(unit_minor >= 0),
        treatment_id TEXT REFERENCES treatments(id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE payments (
        id TEXT PRIMARY KEY, invoice_id TEXT NOT NULL REFERENCES invoices(id) ON DELETE RESTRICT,
        amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
        recorded_utc TEXT NOT NULL, method TEXT, kind TEXT NOT NULL CHECK(kind IN ('payment', 'refund')),
        original_payment_id TEXT REFERENCES payments(id) ON DELETE RESTRICT
    )""",
    """CREATE TRIGGER protect_completed_treatments BEFORE UPDATE ON treatments
        WHEN OLD.status IN ('completed', 'voided')
        BEGIN SELECT RAISE(ABORT, 'finalized treatment is immutable'); END""",
    """CREATE TRIGGER protect_completed_treatments_delete BEFORE DELETE ON treatments
        WHEN OLD.status IN ('completed', 'voided')
        BEGIN SELECT RAISE(ABORT, 'finalized treatment is immutable'); END""",
    """CREATE TRIGGER protect_final_invoices BEFORE UPDATE ON invoices
        WHEN OLD.status = 'finalized'
        BEGIN SELECT RAISE(ABORT, 'finalized invoice is immutable'); END""",
    """CREATE TRIGGER protect_payment_updates BEFORE UPDATE ON payments
        BEGIN SELECT RAISE(ABORT, 'payments are immutable'); END""",
    """CREATE TRIGGER protect_payment_deletes BEFORE DELETE ON payments
        BEGIN SELECT RAISE(ABORT, 'payments are immutable'); END""",
    """CREATE TRIGGER protect_final_invoice_items_insert BEFORE INSERT ON invoice_items
        WHEN (SELECT status FROM invoices WHERE id = NEW.invoice_id) = 'finalized'
        BEGIN SELECT RAISE(ABORT, 'finalized invoice items are immutable'); END""",
    """CREATE TRIGGER protect_final_invoice_items_update BEFORE UPDATE ON invoice_items
        WHEN (SELECT status FROM invoices WHERE id = OLD.invoice_id) = 'finalized'
        BEGIN SELECT RAISE(ABORT, 'finalized invoice items are immutable'); END""",
    """CREATE TRIGGER protect_final_invoice_items_delete BEFORE DELETE ON invoice_items
        WHEN (SELECT status FROM invoices WHERE id = OLD.invoice_id) = 'finalized'
        BEGIN SELECT RAISE(ABORT, 'finalized invoice items are immutable'); END""",
    """CREATE TRIGGER protect_treatment_surfaces_insert BEFORE INSERT ON treatment_surfaces
        WHEN (SELECT status FROM treatments WHERE id = NEW.treatment_id) = 'completed'
        BEGIN SELECT RAISE(ABORT, 'finalized treatment surfaces are immutable'); END""",
    """CREATE TRIGGER protect_treatment_surfaces_update BEFORE UPDATE ON treatment_surfaces
        WHEN (SELECT status FROM treatments WHERE id = OLD.treatment_id) = 'completed'
        BEGIN SELECT RAISE(ABORT, 'finalized treatment surfaces are immutable'); END""",
    """CREATE TRIGGER protect_treatment_surfaces_delete BEFORE DELETE ON treatment_surfaces
        WHEN (SELECT status FROM treatments WHERE id = OLD.treatment_id) = 'completed'
        BEGIN SELECT RAISE(ABORT, 'finalized treatment surfaces are immutable'); END""",
    """CREATE TABLE users (
        id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN
         ('administrator', 'dentist', 'receptionist', 'dental_assistant')),
        active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
        created_utc TEXT NOT NULL
    )""",
    """CREATE TABLE local_sessions (
        token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
        expires_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0 CHECK(revoked IN (0,1))
    )""",
    "CREATE INDEX idx_local_sessions_user ON local_sessions(user_id)",
    """CREATE TABLE attachments (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        visit_id TEXT, treatment_id TEXT, storage_name TEXT NOT NULL UNIQUE,
        mime_type TEXT NOT NULL, original_extension TEXT NOT NULL,
        ciphertext_bytes INTEGER NOT NULL CHECK(ciphertext_bytes > 0),
        sha256 TEXT NOT NULL, recorded_utc TEXT NOT NULL,
        FOREIGN KEY(visit_id,patient_id) REFERENCES clinical_visits(id,patient_id) ON DELETE RESTRICT,
        FOREIGN KEY(treatment_id,patient_id) REFERENCES treatments(id,patient_id) ON DELETE RESTRICT
    )""",
    """CREATE TABLE tooth_state_events (
        id TEXT PRIMARY KEY, patient_id TEXT NOT NULL REFERENCES patients(id) ON DELETE RESTRICT,
        fdi_code INTEGER NOT NULL, state TEXT NOT NULL, recorded_utc TEXT NOT NULL,
        actor_id TEXT NOT NULL
    )""",
    "CREATE INDEX idx_tooth_state_history ON tooth_state_events(patient_id, fdi_code, recorded_utc)",
    """CREATE TRIGGER protect_medical_entry_update BEFORE UPDATE ON medical_entries
        BEGIN SELECT RAISE(ABORT, 'medical history is append-only'); END""",
    """CREATE TRIGGER protect_medical_entry_delete BEFORE DELETE ON medical_entries
        BEGIN SELECT RAISE(ABORT, 'medical history is append-only'); END""",
    """CREATE TRIGGER protect_tooth_observations_update BEFORE UPDATE ON tooth_observations
        BEGIN SELECT RAISE(ABORT, 'tooth observations are append-only'); END""",
    """CREATE TRIGGER protect_tooth_observations_delete BEFORE DELETE ON tooth_observations
        BEGIN SELECT RAISE(ABORT, 'tooth observations are append-only'); END""",
    """CREATE TRIGGER protect_final_clinical_visits BEFORE UPDATE ON clinical_visits
        WHEN OLD.status='finalized'
        BEGIN SELECT RAISE(ABORT, 'clinical visit finalized'); END""",
    """CREATE TRIGGER protect_final_clinical_visits_delete BEFORE DELETE ON clinical_visits
        WHEN OLD.status='finalized'
        BEGIN SELECT RAISE(ABORT, 'clinical visit finalized'); END""",
    """CREATE TRIGGER validate_visit_appointment BEFORE INSERT ON clinical_visits
        WHEN NEW.appointment_id IS NOT NULL AND NOT EXISTS (
          SELECT 1 FROM appointments WHERE id=NEW.appointment_id AND
          patient_id=NEW.patient_id AND practitioner_id=NEW.dentist_id)
        BEGIN SELECT RAISE(ABORT, 'visit appointment does not match patient and dentist'); END""",
    "CREATE INDEX idx_treatments_history ON treatments(patient_id, fdi_code, performed_utc)",
    "CREATE INDEX idx_visits_patient_date ON clinical_visits(patient_id, visit_utc)",
    "CREATE INDEX idx_invoice_patient_date ON invoices(patient_id, issued_utc)",
)

class ClinicDatabase:
    """Open one SQLite connection per operation, safe for multi-threaded callers."""

    def __init__(self, path: str | Path, *, allow_insecure_plaintext_for_tests: bool = False):
        """Fail closed unless plaintext storage is explicitly enabled for tests.

        A production-ready SQLCipher backend is not implemented. This safeguard
        prevents mistakenly opening clinical data with standard sqlite3.
        """
        self.path = str(path)
        self.allow_insecure_plaintext_for_tests = allow_insecure_plaintext_for_tests

    def _require_safe_mode(self) -> None:
        if not self.allow_insecure_plaintext_for_tests:
            raise RuntimeError(
                "Database encryption is unavailable: production startup denied. "
                "For synthetic test data only, explicitly pass "
                "allow_insecure_plaintext_for_tests=True."
            )

    def _backup_before_migration(self) -> Path | None:
        """Create a consistent verified SQLite snapshot before existing-db DDL.

        This does not replace the transaction; failure still rolls back the
        original and the snapshot is intentionally retained for recovery.
        """
        location = Path(self.path)
        if not location.is_file():
            return None
        with self.read() as source:
            version = int(source.execute("PRAGMA user_version").fetchone()[0])
            if not 0 < version < SCHEMA_VERSION:
                return None
            destination = location.with_name(
                f"{location.name}.before-schema-{version}-{uuid4().hex}.sqlite3"
            )
            fd, temp_name = tempfile.mkstemp(prefix=".migration-", suffix=".sqlite3",
                                              dir=location.parent)
            os.close(fd)
            try:
                with sqlite3.connect(temp_name) as target:
                    source.backup(target)
                    if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                        raise RuntimeError("Pre-migration backup integrity failure")
                    if int(target.execute("PRAGMA user_version").fetchone()[0]) != version:
                        raise RuntimeError("Pre-migration backup schema mismatch")
                os.replace(temp_name, destination)
            finally:
                Path(temp_name).unlink(missing_ok=True)
            return destination

    def connect(self) -> sqlite3.Connection:
        self._require_safe_mode()
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        """Apply schema v1 once; refuse to open schemas from a newer version."""
        self._require_safe_mode()
        self._backup_before_migration()
        with self.transaction() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("Database schema is newer than this application")
            if version == 0:
                # DDL uses execute (not executescript) to preserve atomic migration.
                for statement in SCHEMA_V1:
                    conn.execute(statement)
                conn.execute("PRAGMA user_version = 1")
                version = 1
            if version == 1:
                for statement in SCHEMA_V2:
                    conn.execute(statement)
                conn.execute("PRAGMA user_version = 2")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Serialize read-check-write operations and roll back on every error."""
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            else:
                conn.commit()
        finally:
            conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()
