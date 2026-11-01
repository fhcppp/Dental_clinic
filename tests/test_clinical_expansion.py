"""Synthetic-only tests of the additive schema and application services."""
import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from dental_clinic import ClinicDatabase, PatientService
from dental_clinic.clinical import ClinicalService, money_minor, validated_surfaces
from dental_clinic.errors import ConflictError, ValidationError
from dental_clinic.finance import FinanceService
from dental_clinic.medical import MedicalService, age_on

ACTOR = "synthetic-staff"


class ExpandedBackendTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = ClinicDatabase(Path(temp.name) / "synthetic.db")
        self.db.initialize()
        self.patient = PatientService(self.db).create("Synthetic Alice", date(1992, 7, 5))
        self.other = PatientService(self.db).create("Synthetic Bob")
        self.medical = MedicalService(self.db)
        self.clinical = ClinicalService(self.db)
        self.finance = FinanceService(self.db)
        self.clinical.add_dentist("dentist-A", "Synthetic Dentist A", actor_id=ACTOR)
        self.clinical.add_dentist("dentist-B", "Synthetic Dentist B", actor_id=ACTOR)
        self.proc = self.clinical.add_procedure("Composite restoration", "Restorative", actor_id=ACTOR)
        self.visit = self.clinical.open_visit(self.patient.id, "dentist-A", actor_id=ACTOR)

    def test_age_leap_day_and_approx(self):
        self.assertEqual(age_on(date(2000, 2, 29), date(2025, 2, 28)), (24, False))
        self.assertEqual(age_on(None, date(2027, 10, 1), 30, date(2026, 10, 1)), (31, True))
        profile = self.medical.update_profile(self.other.id, {"estimated_age": 29,
            "age_reference_date": date(2025, 1, 1)}, actor_id=ACTOR)
        self.assertEqual(profile["estimated_age"], 29)
        self.assertTrue(self.medical.profile(self.other.id, as_of=date(2026, 7, 1))["approximate_age"])
        with self.assertRaises(ValidationError):
            self.medical.update_profile(self.patient.id, {"estimated_age": 20,
                "age_reference_date": date(2026, 1, 1)}, actor_id=ACTOR)

    def test_profile_revisions_duplicates_phone(self):
        self.medical.update_profile(self.patient.id, {
            "phone": "+49 0123 456", "first_name": "Alice", "last_name": "Example"}, actor_id=ACTOR)
        self.assertEqual(self.medical.profile(self.patient.id)["phone"], "+49 0123 456")
        self.assertEqual(len(self.medical.profile_revisions(self.patient.id)), 1)
        self.assertIn(self.patient.id, self.medical.possible_duplicates("synthetic ALICE", date(1992, 7, 5)))
        with self.assertRaises(ValidationError):
            self.medical.update_profile(self.patient.id, {"phone": "123; DROP TABLE"}, actor_id=ACTOR)

    def test_medical_records_append_only_and_amended(self):
        c = self.medical.add_entry(self.patient.id, "condition", "Hypertension", "active",
                                   actor_id=ACTOR, severity="self-reported")
        self.medical.add_entry(self.patient.id, "allergy", "Latex", "active",
                               actor_id=ACTOR, reaction="rash")
        self.medical.add_entry(self.patient.id, "medication", "Synthetic test med", "active",
                               actor_id=ACTOR, dosage="10 mg")
        self.medical.add_entry(self.patient.id, "condition", "Hypertension", "resolved",
                               actor_id=ACTOR, supersedes_id=c)
        self.assertEqual(len(self.medical.history(self.patient.id)), 4)
        self.assertEqual(len(self.medical.history(self.patient.id, current_only=True)), 3)
        with self.assertRaises(ValidationError):
            self.medical.add_entry(self.other.id, "condition", "Wrong", "active",
                                   actor_id=ACTOR, supersedes_id=c)
        with self.assertRaises(ValidationError):
            self.medical.add_entry(self.patient.id, "condition", "Duplicate", "active",
                                   actor_id=ACTOR, supersedes_id=c)

    def test_fdi_surfaces(self):
        self.assertEqual(validated_surfaces(26, ["mesial", "occlusal", "distal"]),
                         ("mesial", "occlusal", "distal"))
        for code, surfaces in [(11, ["occlusal"]), (36, ["incisal"]),
                               (41, ["palatal"]), (16, ["mesial", "mesial"])]:
            with self.assertRaises(ValidationError):
                validated_surfaces(code, surfaces)

    def test_observation_history(self):
        first = self.clinical.add_observation(self.patient.id, "dentist-A", 16, "caries",
            ("occlusal",), actor_id=ACTOR, visit_id=self.visit)
        self.clinical.add_observation(self.patient.id, "dentist-A", 16, "restored",
            ("occlusal",), actor_id=ACTOR, visit_id=self.visit, supersedes_id=first)
        self.assertEqual(len(self.clinical.tooth_observation_history(self.patient.id, 16)), 2)

    def test_multi_treatment_history_and_immutability(self):
        first = self.clinical.record_treatment(self.patient.id, self.visit,
             "dentist-A", self.proc, actor_id=ACTOR, fdi_code=16,
             surfaces=("occlusal",), notes="Synthetic completed procedure")
        second = self.clinical.record_treatment(self.patient.id, self.visit,
             "dentist-A", self.proc, actor_id=ACTOR, fdi_code=16,
             surfaces=("mesial", "occlusal"), notes="Synthetic amended observation",
             amendment_of=first)
        history = self.clinical.treatment_history(self.patient.id, 16)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1]["amendment_of"], first)
        self.assertEqual(len(history[1]["surfaces"]), 2)
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as c:
            c.execute("UPDATE treatments SET notes = 'rewritten' WHERE id = ?", (first,))
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as c:
            c.execute("DELETE FROM treatments WHERE id = ?", (second,))

    def test_cross_patient_visit_rejected(self):
        with self.assertRaises(ValidationError):
            self.clinical.record_treatment(self.other.id, self.visit, "dentist-A",
                self.proc, actor_id=ACTOR, notes="Mislinked", fdi_code=16)
        with self.assertRaises(ValidationError):
            self.clinical.record_treatment(self.patient.id, self.visit, "dentist-B",
                self.proc, actor_id=ACTOR, notes="Mislinked", fdi_code=16)

    def test_plan_does_not_imply_completed_treatment(self):
        plan = self.clinical.create_plan(self.patient.id, "dentist-A", "Synthetic plan", actor_id=ACTOR)
        item = self.clinical.add_plan_item(plan, self.proc, actor_id=ACTOR,
                                            fdi_code=26, surfaces=("mesial", "occlusal"))
        self.assertEqual(self.clinical.treatment_history(self.patient.id), [])
        with self.db.read() as c:
            self.assertEqual(c.execute("SELECT status FROM treatment_plan_items WHERE id=?",
                                       (item,)).fetchone()[0], "proposed")
        tx = self.clinical.record_treatment(self.patient.id, self.visit, "dentist-A", self.proc,
            actor_id=ACTOR, fdi_code=26, surfaces=("mesial", "occlusal"),
            notes="Synthetic performed", plan_item_id=item)
        self.assertEqual(self.clinical.treatment_history(self.patient.id)[0]["id"], tx)
        with self.db.read() as c:
            self.assertEqual(c.execute("SELECT status FROM treatment_plan_items WHERE id=?",
                                       (item,)).fetchone()[0], "completed")

    def test_endodontic_stages_and_working_length(self):
        tx = self.clinical.record_treatment(self.patient.id, self.visit, "dentist-A",
            self.proc, actor_id=ACTOR, fdi_code=16, completed=False,
            notes="Synthetic canal staging")
        stage = self.clinical.add_endodontic_stage(tx, "Working length", actor_id=ACTOR,
            canals={"MB": Decimal("19.5"), "DB": Decimal("20.0")})
        with self.db.read() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM endodontic_canals WHERE stage_id=?",
                                       (stage,)).fetchone()[0], 2)
        with self.assertRaises(ValidationError):
            self.clinical.add_endodontic_stage(tx, "Invalid", actor_id=ACTOR,
                                                canals={"MB": "-2"})
        self.clinical.finalize_draft(tx, actor_id=ACTOR)
        with self.assertRaises(ConflictError):
            self.clinical.add_endodontic_stage(tx, "Too late", actor_id=ACTOR)

    def test_money_precision_and_partial_refund(self):
        invoice = self.finance.create_invoice(self.patient.id, actor_id=ACTOR)
        self.finance.add_item(invoice, "Synthetic filling", Decimal("100.25"), actor_id=ACTOR)
        self.finance.add_item(invoice, "Synthetic exam", Decimal("12.50"),
                              actor_id=ACTOR, quantity=2)
        self.finance.finalize(invoice, actor_id=ACTOR)
        self.assertEqual(self.finance.balance(invoice)["total_minor"], 12525)
        p1 = self.finance.record_payment(invoice, "100.20", actor_id=ACTOR)
        self.assertEqual(self.finance.balance(invoice)["outstanding_minor"], 2505)
        self.finance.refund(p1, "0.20", actor_id=ACTOR)
        self.assertEqual(self.finance.balance(invoice)["outstanding_minor"], 2525)
        with self.assertRaises(ConflictError):
            self.finance.record_payment(invoice, "26", actor_id=ACTOR)
        with self.assertRaises(ValidationError):
            money_minor(0.1)
        with self.assertRaises(ValidationError):
            money_minor("0.001")
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as c:
            c.execute("UPDATE invoice_items SET unit_minor=0 WHERE invoice_id=?", (invoice,))
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as c:
            c.execute("DELETE FROM payments WHERE id = ?", (p1,))

    def test_restrict_delete_patient_preserves_records(self):
        self.medical.add_entry(self.patient.id, "allergy", "Synthetic allergy", "active", actor_id=ACTOR)
        with self.assertRaises(sqlite3.IntegrityError), self.db.transaction() as c:
            c.execute("DELETE FROM patients WHERE id = ?", (self.patient.id,))

    def test_atomic_migration_v1_to_v2(self):
        from dental_clinic.db import SCHEMA_V1
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "legacy.sqlite3"
            old = ClinicDatabase(path)
            with old.transaction() as c:
                for ddl in SCHEMA_V1:
                    c.execute(ddl)
                c.execute("PRAGMA user_version = 1")
                c.execute("INSERT INTO patients(id,full_name,created_utc) VALUES ('legacy','Old Synthetic','2026-10-01')")
            old.initialize()
            old.initialize()
            self.assertEqual(MedicalService(old).profile("legacy")["full_name"], "Old Synthetic")
            with old.read() as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()


class AdditionalIntegrationTests(unittest.TestCase):
    def test_room_collision_and_reporting(self):
        from datetime import UTC, datetime, timedelta
        from dental_clinic.services import AppointmentService, ClinicRoomService
        from dental_clinic.reporting import ReportingService
        with tempfile.TemporaryDirectory() as tmp:
            db = ClinicDatabase(Path(tmp) / 'test.db')
            db.initialize()
            patients = PatientService(db)
            first = patients.create('Synthetic First')
            second = patients.create('Synthetic Second')
            rooms = ClinicRoomService(db)
            rooms.add('R1', 'Synthetic Room')
            appointments = AppointmentService(db)
            start = datetime(2026, 11, 2, 8, tzinfo=UTC)
            a = appointments.schedule(first.id, 'dentist-A', start, start+timedelta(hours=1),
                                      room_id='R1')
            self.assertEqual(a.room_id, 'R1')
            with self.assertRaises(ConflictError):
                appointments.schedule(second.id, 'dentist-B', start, start+timedelta(hours=1),
                                      room_id='R1')
            summary = ReportingService(db).appointment_summary(date(2026,11,2), date(2026,11,2))
            self.assertEqual(summary[0]['appointments'], 1)
            self.assertEqual(ReportingService.csv_text([{'v': '=DANGEROUS'}]), "v\r\n'=DANGEROUS\r\n")
