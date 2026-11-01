"""Synthetic tests for v3 audit integrity and progressive auth throttling."""
from __future__ import annotations

import hashlib
import socket
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from dental_clinic import ClinicDatabase, PatientService
from dental_clinic import db as db_module
from dental_clinic.attachments import AttachmentVault
from dental_clinic.audit import GENESIS, canonical_event
from dental_clinic.auth import LOGIN_FAILURE_THRESHOLD, AuthService
from dental_clinic.errors import ValidationError
from dental_clinic.finance import FinanceService
from dental_clinic.security.keys import derive_audit_key, generate_master_key
from dental_clinic.settings import ClinicSettings


class AuditIntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "synthetic.sqlite3"
        self.db = ClinicDatabase(self.path, allow_insecure_plaintext_for_tests=True,
                                 audit_key=b"S" * 32)
        self.db.initialize()

    def test_chain_atomicity_and_tamper_detection(self):
        self.assertTrue(self.db.verify_audit_chain())
        p = PatientService(self.db).create("Synthetic No Identity")
        self.assertTrue(self.db.verify_audit_chain())
        with closing(sqlite3.connect(self.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM audit_events")
        self.assertTrue(self.db.verify_audit_chain())
        # Simulate an attacker who bypasses SQLite's own delete/update triggers.
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DROP TRIGGER protect_audit_events_update")
            conn.execute("UPDATE audit_events SET action='malicious.edit'")
        self.assertFalse(self.db.verify_audit_chain())
        self.assertTrue(p.id)

    def test_audit_signing_failure_rolls_back_patient_creation(self):
        with self.assertRaises(sqlite3.OperationalError):
            with self.db.transaction() as c:
                c.create_function("dental_audit_mac", 8, lambda *args: 1 / 0)
                c.execute("INSERT INTO patients(id,full_name,created_utc) VALUES ('x','Fake','now')")
                c.execute("""INSERT INTO audit_events(occurred_utc,actor_id,action,
                          subject_type,subject_id) VALUES ('now','actor','create','patient','x')""")
        with self.db.read() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM patients").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT count(*) FROM audit_events").fetchone()[0], 0)

    def test_concurrent_writers_chain_order(self):
        def add(index: int):
            return PatientService(self.db).create(f"Synthetic {index}").id
        with ThreadPoolExecutor(max_workers=6) as pool:
            patients = list(pool.map(add, range(12)))
        self.assertEqual(len(set(patients)), 12)
        self.assertTrue(self.db.verify_audit_chain())
        with self.db.read() as c:
            self.assertEqual([r[0] for r in c.execute("SELECT seq FROM audit_chain ORDER BY seq")],
                             list(range(1, 13)))

    def test_v2_migration_backfills_legacy_events(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.db"
            with closing(sqlite3.connect(path)) as c, c:
                for ddl in db_module.SCHEMA_V1:
                    c.execute(ddl)
                for ddl in db_module.SCHEMA_V2:
                    c.execute(ddl)
                c.execute("PRAGMA user_version=2")
                c.execute("""INSERT INTO audit_events(occurred_utc,actor_id,action,
                           subject_type,subject_id) VALUES ('now','x','old','legacy','1')""")
            upgraded = ClinicDatabase(path, allow_insecure_plaintext_for_tests=True,
                                      audit_key=b"X" * 32)
            upgraded.initialize()
            self.assertTrue(upgraded.verify_audit_chain())
            with upgraded.read() as c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 3)
                self.assertEqual(c.execute("SELECT count(*) FROM audit_chain").fetchone()[0], 1)
            self.assertEqual(len(list(path.parent.glob("*.before-schema-2-*.sqlite3"))), 1)

    def test_wrong_audit_key_fails_verification(self):
        PatientService(self.db).create("Synthetic")
        other = ClinicDatabase(self.path, allow_insecure_plaintext_for_tests=True,
                               audit_key=b"F" * 32)
        self.assertFalse(other.verify_audit_chain())

    def test_reopening_wrong_key_rejects_startup(self):
        PatientService(self.db).create("Synthetic")
        wrong = ClinicDatabase(self.path, allow_insecure_plaintext_for_tests=True,
                               audit_key=b"F" * 32)
        with self.assertRaisesRegex(RuntimeError, "Audit integrity"):
            wrong.initialize()

    def test_failed_v2_to_v3_migration_keeps_old_version(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            with closing(sqlite3.connect(path)) as c, c:
                for statement in db_module.SCHEMA_V1 + db_module.SCHEMA_V2:
                    c.execute(statement)
                c.execute("PRAGMA user_version=2")
            legacy = ClinicDatabase(path, allow_insecure_plaintext_for_tests=True)
            with patch.object(db_module, "AUDIT_TRIGGERS_V3",
                              db_module.AUDIT_TRIGGERS_V3 + ("INVALID AUDIT DDL",)):
                with self.assertRaises(sqlite3.DatabaseError):
                    legacy.initialize()
            with closing(sqlite3.connect(path)) as c, c:
                self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(len(list(path.parent.glob("*.before-schema-2-*.sqlite3"))), 1)

    def test_network_blocked_local_workflows(self):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network")), \
             patch.object(socket, "create_connection", side_effect=AssertionError("network")):
            patient = PatientService(self.db).create("Offline Synthetic")
            self.assertEqual(PatientService(self.db).get(patient.id).id, patient.id)
            self.assertTrue(self.db.verify_audit_chain())

    def test_canonical_event_format(self):
        raw = canonical_event((1, 7, "2026-11-01T10:00Z", "staff", "create", "patient", "x", GENESIS))
        self.assertTrue(raw.startswith(b'{"action":"create"'))
        self.assertEqual(hashlib.sha256(raw).hexdigest().__len__(), 64)


class CurrencyAndAttachmentSettingsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.db = ClinicDatabase(Path(temp.name) / "synthetic.db",
                                 allow_insecure_plaintext_for_tests=True)
        self.db.initialize()
        self.patient = PatientService(self.db).create("Synthetic Test Patient")
        self.folder = Path(temp.name) / "vault"

    def test_explicit_currency_and_zero_and_three_decimal_places(self):
        with self.assertRaises(ValidationError):
            FinanceService(self.db).create_invoice(self.patient.id, actor_id="synthetic")
        for currency, expected in (("JPY", 2), ("KWD", 1235), ("EUR", 124)):
            with self.subTest(currency=currency):
                service = FinanceService(self.db, ClinicSettings(timezone="UTC", currency=currency))
                with self.assertRaises(ValidationError):
                    service.create_invoice(self.patient.id, actor_id="synthetic", currency="USD")
                ident = service.create_invoice(self.patient.id, actor_id="synthetic")
                amount = "1.5" if currency == "JPY" else ("1.2345" if currency == "KWD" else "1.235")
                service.add_item(ident, "Synthetic", amount, actor_id="synthetic")
                service.finalize(ident, actor_id="synthetic")
                self.assertEqual(service.balance(ident)["total_minor"], expected)
        self.assertTrue(self.db.verify_audit_chain())

    def test_attachment_atomic_write_and_read_after_transaction(self):
        vault = AttachmentVault(self.db, self.folder, b"Z" * 32)
        payload = b"%PDF-1.5\nsynthetic\n%%EOF"
        ident = vault.store(self.patient.id, "synthetic.pdf", payload,
                            actor_id="synthetic")
        self.assertEqual(vault.load(self.patient.id, ident), payload)
        self.assertEqual(len(list(self.folder.glob("*.pending"))), 0)
        self.assertTrue(self.db.verify_audit_chain())

    def test_attachment_size_limit_can_be_set_and_fails_closed(self):
        vault = AttachmentVault(self.db, self.folder, b"Z" * 32, max_file_bytes=12)
        with self.assertRaises(ValidationError):
            vault.store(self.patient.id, "synthetic.pdf", b"%PDF-1.4" + b"x" * 10,
                        actor_id="synthetic")
        self.assertEqual(len(list(self.folder.glob("*.enc"))), 0)

    def test_key_derivation_is_domain_separated(self):
        master = generate_master_key()
        self.assertNotEqual(derive_audit_key(master), master)
        self.assertNotEqual(derive_audit_key(master, key_version=1),
                            derive_audit_key(master, key_version=2))


class LoginProtectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = ClinicDatabase(Path(tmp.name) / "test.db",
                                 allow_insecure_plaintext_for_tests=True)
        self.db.initialize()
        self.auth = AuthService(self.db)
        self.auth.bootstrap_admin("admin", "test-admin-long-password")

    def test_fifth_failure_triggers_delay_without_permanent_lockout(self):
        now = datetime(2026, 11, 1, 12, tzinfo=UTC)
        with patch("dental_clinic.auth._utc_now", return_value=now):
            for _ in range(LOGIN_FAILURE_THRESHOLD):
                with self.assertRaisesRegex(ValidationError, "Invalid username or password"):
                    self.auth.login("admin", "wrong-password")
            with self.db.read() as c:
                row = c.execute("SELECT failures,retry_utc FROM auth_login_attempts").fetchone()
                self.assertEqual(row["failures"], 5)
                self.assertEqual(row["retry_utc"], (now+timedelta(seconds=15)).isoformat(timespec="microseconds").replace("+00:00", "Z"))
            with self.assertRaises(ValidationError):
                self.auth.login("admin", "test-admin-long-password")
        with patch("dental_clinic.auth._utc_now", return_value=now+timedelta(seconds=16)):
            token = self.auth.login("admin", "test-admin-long-password")
            self.assertTrue(token)
        with self.db.read() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM auth_login_attempts").fetchone()[0], 0)
        self.assertTrue(self.db.verify_audit_chain())

    def test_unknown_username_has_identical_error_and_no_account_created(self):
        for username in ("unknown", "admin"):
            with self.subTest(username=username), self.assertRaisesRegex(
                ValidationError, "Invalid username or password"
            ):
                self.auth.login(username, "invalid-guess")
        with self.db.read() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM users").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT count(*) FROM auth_login_attempts").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
