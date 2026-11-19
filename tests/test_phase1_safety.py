"""Security and migration tests use only disposable synthetic records."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from dental_clinic import db as schema
from dental_clinic.db import ClinicDatabase
from dental_clinic.security.keys import (
    TestOnlyKeyProvider as DevelopmentKeyProvider,
)
from dental_clinic.security.keys import (
    WindowsDPAPIKeyProvider,
    generate_keyring,
    generate_master_key,
    open_keyring,
    recover_master,
    wrap_recovery_master,
    write_private_envelope,
)
from dental_clinic.settings import ClinicSettings


class ClinicSetupTests(unittest.TestCase):
    def test_explicit_timezone_and_currency_precision(self):
        with self.assertRaises(TypeError):
            ClinicSettings()  # type: ignore[call-arg]
        eu = ClinicSettings(timezone="Europe/Berlin", currency="EUR")
        jp = ClinicSettings(timezone="Asia/Tokyo", currency="JPY")
        kw = ClinicSettings(timezone="Asia/Kuwait", currency="KWD")
        self.assertEqual((eu.to_minor_units("1.235"), jp.to_minor_units("1.5"),
                          kw.to_minor_units(Decimal("1.2345"))), (124, 2, 1235))
        self.assertEqual((eu.attachment_max_bytes, eu.backup_daily_count,
                          eu.backup_weekly_count), (25 * 1024 * 1024, 7, 4))

    def test_setup_rejects_unselected_and_invalid_values(self):
        for timezone, currency in [("", "EUR"), ("invalid/zone", "EUR"),
                                   ("Europe/Berlin", ""), ("Europe/Berlin", "XXX")]:
            with self.subTest(timezone=timezone, currency=currency):
                with self.assertRaises(ValueError):
                    ClinicSettings(timezone=timezone, currency=currency)
        settings = ClinicSettings(timezone="UTC", currency="EUR")
        for value in (float("nan"), 1.2, "NaN", "Infinity", "-1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                settings.to_minor_units(value)


class SafeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "synthetic.sqlite3"

    def create_v1(self):
        with sqlite3.connect(self.path) as conn:
            for statement in schema.SCHEMA_V1:
                conn.execute(statement)
            conn.execute("PRAGMA user_version=1")
            conn.execute("""INSERT INTO patients(id,full_name,created_utc)
                          VALUES ('stable-id','Synthetic Example','2026-01-01T00:00:00+00:00')""")

    def test_plaintext_is_explicit_opt_in(self):
        with self.assertRaisesRegex(RuntimeError, "production startup denied"):
            ClinicDatabase(self.path).initialize()
        self.assertFalse(self.path.exists(), "Fail-closed startup must not create a database")
        ClinicDatabase(self.path, allow_insecure_plaintext_for_tests=True).initialize()
        self.assertTrue(self.path.is_file())

    def test_migration_preserves_v1_patient_and_backup(self):
        self.create_v1()
        ClinicDatabase(self.path, allow_insecure_plaintext_for_tests=True).initialize()
        backups = list(self.path.parent.glob("*.before-schema-1-*.sqlite3"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT full_name FROM patients WHERE id='stable-id'").fetchone()[0],
                             "Synthetic Example")
        with sqlite3.connect(backups[0]) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT id FROM patients").fetchone()[0], "stable-id")

    def test_failed_migration_rolls_back_original_and_keeps_backup(self):
        self.create_v1()
        invalid = schema.SCHEMA_V2 + ("THIS IS AN INVALID MIGRATION STATEMENT",)
        with patch.object(schema, "SCHEMA_V2", invalid):
            with self.assertRaises(sqlite3.DatabaseError):
                ClinicDatabase(self.path, allow_insecure_plaintext_for_tests=True).initialize()
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT id FROM patients").fetchone()[0], "stable-id")
            self.assertEqual(conn.execute("PRAGMA quick_check").fetchone()[0], "ok")
        self.assertEqual(len(list(self.path.parent.glob("*.before-schema-1-*.sqlite3"))), 1)


class KeyArchitectureTests(unittest.TestCase):
    def test_independent_purpose_keys_and_roundtrip(self):
        master = generate_master_key()
        envelope = generate_keyring(master)
        opened = open_keyring(master, envelope)
        self.assertEqual(set(opened), {"database", "attachments", "backups"})
        self.assertEqual(len(set(opened.values())), 3)
        self.assertTrue(all(len(v) == 32 for v in opened.values()))
        self.assertNotIn(master.hex(), json.dumps(envelope))
        self.assertNotIn(opened["attachments"].hex(), json.dumps(envelope))
        with self.assertRaises(ValueError):
            open_keyring(generate_master_key(), envelope)

    def test_tamper_detection_and_key_version(self):
        master = generate_master_key()
        envelope = generate_keyring(master, key_version=7)
        self.assertEqual(envelope["key_version"], 7)
        envelope["keys"]["attachments"]["ciphertext"] = envelope["keys"]["database"]["ciphertext"]
        with self.assertRaises(ValueError):
            open_keyring(master, envelope)

    def test_independent_recovery_password_roundtrip(self):
        master = generate_master_key()
        password = "synthetic recovery password of sufficient length"
        envelope = wrap_recovery_master(master, password)
        serialized = json.dumps(envelope)
        self.assertNotIn(password, serialized)
        self.assertEqual(recover_master(envelope, password), master)
        with self.assertRaises(ValueError):
            recover_master(envelope, "wrong recovery password")

    def test_recovery_rejects_modified_parameters_before_derive(self):
        envelope = wrap_recovery_master(generate_master_key(), "a recovery password")
        envelope["kdf"]["n"] = 2**23
        with self.assertRaisesRegex(ValueError, "Unsupported recovery"):
            recover_master(envelope, "a recovery password")

    def test_provider_production_guards(self):
        master = generate_master_key()
        provider = DevelopmentKeyProvider(master)
        with self.assertRaises(RuntimeError):
            provider.unlock()
        self.assertEqual(provider.unlock(production=False), master)
        if os.name != "nt":
            with self.assertRaises(RuntimeError):
                WindowsDPAPIKeyProvider("nonexistent.key").unlock()

    def test_mock_dpapi_wrapped_key_roundtrip_without_windows_claim(self):
        class FakeDpapi:
            @staticmethod
            def CryptProtectData(data, *args):
                return b"fake-synthetic-" + data[::-1]

            @staticmethod
            def CryptUnprotectData(data, *args):
                if not data.startswith(b"fake-synthetic-"):
                    raise ValueError("Corrupt synthetic blob")
                return ("description", data[len(b"fake-synthetic-"):][::-1])

        with tempfile.TemporaryDirectory() as tmp:
            provider = WindowsDPAPIKeyProvider(Path(tmp) / "protected.key")
            master = generate_master_key()
            with patch.object(WindowsDPAPIKeyProvider, "_backend", return_value=FakeDpapi):
                provider.initialize(master)
                self.assertNotEqual(provider.path.read_bytes(), master)
                self.assertEqual(provider.unlock(), master)
                with self.assertRaises(FileExistsError):
                    provider.initialize(master)

    def test_corrupted_recovery_ciphertext_is_rejected(self):
        password = "synthetic non-sensitive recovery phrase"
        envelope = wrap_recovery_master(generate_master_key(), password)
        envelope["ciphertext"] = envelope["nonce"]
        with self.assertRaises(ValueError):
            recover_master(envelope, password)

    def test_key_file_is_owner_only_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envelope.json"
            envelope = generate_keyring(generate_master_key())
            write_private_envelope(path, envelope)
            self.assertEqual(json.loads(path.read_text()), envelope)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                write_private_envelope(path, envelope)


if __name__ == "__main__":
    unittest.main()
