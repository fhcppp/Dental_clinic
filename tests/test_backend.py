"""Integration tests use temporary SQLite files and synthetic patient values."""

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dental_clinic import (
    AppointmentService,
    ClinicDatabase,
    ConflictError,
    NotFoundError,
    OdontogramService,
    PatientService,
    ValidationError,
)
from dental_clinic.fdi import PERMANENT_CODES, PRIMARY_CODES, validate_fdi

START = datetime(2026, 11, 2, 10, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)


class BackendIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = ClinicDatabase(Path(self.temp.name) / "test.sqlite3", allow_insecure_plaintext_for_tests=True)
        self.db.initialize()
        self.patients = PatientService(self.db)
        self.appointments = AppointmentService(self.db)
        self.odontogram = OdontogramService(self.db)
        self.alex = self.patients.create("Test Patient A", date(1990, 5, 3))
        self.beth = self.patients.create("Test Patient B")

    def test_initialization_idempotent_and_data_persists(self) -> None:
        self.db.initialize()
        self.assertEqual(self.patients.get(self.alex.id).birth_date, date(1990, 5, 3))
        with self.db.read() as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_reject_newer_schema(self) -> None:
        with self.db.transaction() as conn:
            conn.execute("PRAGMA user_version = 4")
        with self.assertRaises(RuntimeError):
            self.db.initialize()

    def test_patient_validation_and_list(self) -> None:
        with self.assertRaises(ValidationError):
            self.patients.create("  ")
        with self.assertRaises(ValidationError):
            self.patients.create("Synthetic", date(2999, 1, 1))
        self.assertEqual(len(self.patients.list_active()), 2)
        with self.assertRaises(NotFoundError):
            self.patients.get("not-an-id")

    def test_patient_name_is_parameterized(self) -> None:
        p = self.patients.create("X'); DROP TABLE patients; --")
        self.assertEqual(self.patients.get(p.id).full_name, "X'); DROP TABLE patients; --")
        self.assertEqual(len(self.patients.list_active()), 3)

    def test_appointment_overlap_same_practitioner(self) -> None:
        self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        with self.assertRaises(ConflictError):
            self.appointments.schedule(
                self.beth.id, "doctor-1", START + timedelta(minutes=30), START + HOUR * 2
            )

    def test_appointment_overlap_same_patient_different_practitioner(self) -> None:
        self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        with self.assertRaises(ConflictError):
            self.appointments.schedule(self.alex.id, "doctor-2", START, START + HOUR)

    def test_touching_boundaries_allowed(self) -> None:
        self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        result = self.appointments.schedule(
            self.beth.id, "doctor-1", START + HOUR, START + HOUR * 2
        )
        self.assertEqual(result.status, "scheduled")

    def test_same_time_different_patient_and_practitioner_allowed(self) -> None:
        self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        self.appointments.schedule(self.beth.id, "doctor-2", START, START + HOUR)

    def test_cancel_releases_slot_and_is_idempotent(self) -> None:
        a = self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        self.assertEqual(self.appointments.cancel(a.id).status, "cancelled")
        self.assertEqual(self.appointments.cancel(a.id).status, "cancelled")
        self.appointments.schedule(self.beth.id, "doctor-1", START, START + HOUR)
        with self.db.read() as conn:
            count = conn.execute(
                "SELECT count(*) FROM audit_events WHERE action = 'appointment.cancelled'"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_reschedule_rechecks_collision_and_rolls_back(self) -> None:
        a = self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        self.appointments.schedule(self.beth.id, "doctor-1", START + HOUR, START + HOUR * 2)
        with self.assertRaises(ConflictError):
            self.appointments.reschedule(a.id, START + HOUR, START + HOUR * 2)
        self.assertEqual(self.appointments.get(a.id).start_utc, START)
        self.assertEqual(
            self.appointments.reschedule(a.id, START - HOUR, START).start_utc,
            START - HOUR,
        )

    def test_timezone_conversion_and_invalid_intervals(self) -> None:
        plus_two = timezone(timedelta(hours=2))
        a = self.appointments.schedule(
            self.alex.id,
            "doctor-1",
            START.astimezone(plus_two),
            (START + HOUR).astimezone(plus_two),
        )
        self.assertEqual(a.start_utc, START)
        with self.assertRaises(ValidationError):
            self.appointments.schedule(
                self.beth.id, "doctor-2", START.replace(tzinfo=None), START + HOUR
            )
        with self.assertRaises(ValidationError):
            self.appointments.schedule(self.beth.id, "doctor-2", START, START)
        with self.assertRaises(ValidationError):
            self.appointments.schedule(self.beth.id, "doctor-2", START, START + HOUR * 9)

    def test_dst_fold_validates_actual_elapsed_time(self) -> None:
        berlin = ZoneInfo("Europe/Berlin")
        # The wall clock goes back one hour on 2026-10-25 in Berlin.
        later_instant = datetime(2026, 10, 25, 2, 15, tzinfo=berlin, fold=1)
        earlier_instant = datetime(2026, 10, 25, 2, 30, tzinfo=berlin, fold=0)
        with self.assertRaises(ValidationError):
            self.appointments.schedule(
                self.alex.id, "doctor-1", later_instant, earlier_instant
            )

    def test_deactivate_requires_cancel_and_disallows_future_booking(self) -> None:
        a = self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)
        with self.assertRaises(ConflictError):
            self.patients.deactivate(self.alex.id)
        self.appointments.cancel(a.id)
        self.assertFalse(self.patients.deactivate(self.alex.id).active)
        with self.assertRaises(ConflictError):
            self.appointments.schedule(self.alex.id, "doctor-1", START, START + HOUR)

    def test_tooth_codes_primary_permanent_and_invalid(self) -> None:
        self.assertEqual(len(PRIMARY_CODES), 20)
        self.assertEqual(len(PERMANENT_CODES), 32)
        for value in (11, 48, 51, 85):
            self.assertEqual(validate_fdi(value), value)
        for value in (0, 19, 49, 56, 91, True, "11"):
            with self.assertRaises(ValidationError):
                validate_fdi(value)

    def test_odontogram_updates_existing_record(self) -> None:
        self.odontogram.set_state(self.alex.id, 11, "healthy")
        self.odontogram.set_state(self.alex.id, 11, "restored")
        self.odontogram.set_state(self.alex.id, 51, "missing")
        states = self.odontogram.list_for_patient(self.alex.id)
        self.assertEqual([(r.fdi_code, r.state) for r in states],
                         [(11, "restored"), (51, "missing")])
        with self.assertRaises(ValidationError):
            self.odontogram.set_state(self.alex.id, 11, "unapproved")

    def test_audit_rollback_if_actor_missing(self) -> None:
        with self.assertRaises(ValidationError):
            self.patients.create("Should not persist", actor_id="")
        self.assertEqual(len(self.patients.list_active()), 2)
        with self.db.read() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0], 2)

    def test_simultaneous_overlaps_allow_one(self) -> None:
        def book(patient_id: str) -> str:
            try:
                self.appointments.schedule(patient_id, "doctor-1", START, START + HOUR)
                return "ok"
            except ConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(book, [self.alex.id, self.beth.id]))
        self.assertCountEqual(outcomes, ["ok", "conflict"])

    def test_sqlite_foreign_key_enforced(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO tooth_records
                   (patient_id, fdi_code, state, updated_utc) VALUES (?, ?, ?, ?)""",
                ("nonexistent", 11, "healthy", "2026-11-01T00:00:00.000000Z"),
            )


if __name__ == "__main__":
    unittest.main()
