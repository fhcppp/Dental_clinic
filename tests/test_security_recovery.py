"""Synthetic attachment, session, and recovery tests; no live data."""
import os
import tempfile
import unittest
from pathlib import Path

from dental_clinic import ClinicDatabase, PatientService
from dental_clinic.attachments import AttachmentVault
from dental_clinic.auth import AuthService
from dental_clinic.backup import BackupService
from dental_clinic.errors import ConflictError, NotFoundError, ValidationError


class SecureInfrastructureTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.db = ClinicDatabase(self.folder / "clinic.sqlite3")
        self.db.initialize()
        self.p = PatientService(self.db).create("Synthetic Privacy Case")
        self.other = PatientService(self.db).create("Synthetic Other")
        self.vault_path = self.folder / "vault"
        self.key = os.urandom(32)
        self.vault = AttachmentVault(self.db, self.vault_path, self.key)

    def test_auth_roles_login_logout(self):
        auth = AuthService(self.db)
        uid = auth.bootstrap_admin("testadmin", "a-long-synthetic-password")
        with self.assertRaises(ConflictError):
            auth.bootstrap_admin("other", "another-long-password")
        with self.assertRaises(ValidationError):
            auth.login("testadmin", "wrong-password")
        token = auth.login("testadmin", "a-long-synthetic-password")
        self.assertEqual(auth.authorize(token, "users.manage"), uid)
        auth.create_user(token, "testdentist", "another-synthetic-password", "dentist")
        dentist_token = auth.login("testdentist", "another-synthetic-password")
        self.assertTrue(auth.authorize(dentist_token, "clinical.write"))
        with self.assertRaises(ValidationError):
            auth.authorize(dentist_token, "users.manage")
        auth.logout(dentist_token)
        with self.assertRaises(ValidationError):
            auth.authorize(dentist_token, "clinical.write")
        with self.db.read() as c:
            self.assertNotIn("a-long-synthetic-password", c.execute(
                "SELECT password_hash FROM users WHERE id = ?", (uid,)).fetchone()[0])

    def test_auth_expiry_and_password_rotation(self):
        auth = AuthService(self.db)
        auth.bootstrap_admin("testadmin", "a-long-synthetic-password")
        old = auth.login("testadmin", "a-long-synthetic-password")
        with self.db.transaction() as c:
            c.execute("UPDATE local_sessions SET last_seen_utc='2001-01-01T00:00:00Z'")
        with self.assertRaises(ValidationError):
            auth.authorize(old, "patients.read")
        token = auth.login("testadmin", "a-long-synthetic-password")
        auth.change_password(token, "a-long-synthetic-password", "new-long-synthetic-pass")
        with self.assertRaises(ValidationError):
            auth.authorize(token, "patients.read")
        auth.login("testadmin", "new-long-synthetic-pass")

    def test_attachment_roundtrip_wrong_key_and_path(self):
        plaintext = b"%PDF-1.4\nSynthetic unidentifiable patient test data\n%%EOF"
        attachment = self.vault.store(self.p.id, "document.pdf", plaintext, actor_id="staff-test")
        self.assertEqual(self.vault.load(self.p.id, attachment), plaintext)
        with self.assertRaises(NotFoundError):
            self.vault.load(self.other.id, attachment)
        with self.assertRaises(ValidationError):
            AttachmentVault(self.db, self.vault_path, os.urandom(32)).load(self.p.id, attachment)
        with self.db.read() as c:
            name = c.execute("SELECT storage_name FROM attachments WHERE id = ?",
                             (attachment,)).fetchone()[0]
        self.assertNotIn(b"Synthetic unidentifiable", (self.vault_path / name).read_bytes())
        with self.assertRaises(ValidationError):
            self.vault.store(self.p.id, "../foo.exe", plaintext, actor_id="staff-test")
        with self.assertRaises(ValidationError):
            self.vault.store(self.p.id, "file.png", plaintext, actor_id="staff-test")

    def test_attachment_integrity_modified_ciphertext(self):
        a = self.vault.store(self.p.id, "x.jpg", b"\xff\xd8\xffsynthetic", actor_id="staff-test")
        with self.db.read() as c:
            name = c.execute("SELECT storage_name FROM attachments WHERE id = ?", (a,)).fetchone()[0]
        file = self.vault_path / name
        contents = bytearray(file.read_bytes())
        contents[-1] ^= 1
        file.write_bytes(contents)
        with self.assertRaises(ValidationError):
            self.vault.load(self.p.id, a)

    def test_encrypted_backup_restore_and_wrong_password(self):
        original = b"%PDF-1.4\nSynthetic secure backup\n%%EOF"
        att = self.vault.store(self.p.id, "x.pdf", original, actor_id="staff-test")
        backup = self.folder / "encrypted.clinicbackup"
        service = BackupService(self.db, self.vault_path)
        service.create(backup, "strong-synthetic-archive-password")
        self.assertNotIn(b"Synthetic secure backup", backup.read_bytes())
        with self.assertRaises(ValidationError):
            BackupService.verify(backup, "wrong-synthetic-password")
        database = self.folder / "restored.db"
        files = self.folder / "restored_attachments"
        service.restore_to(backup, "strong-synthetic-archive-password",
                           destination_db=database, destination_attachments=files)
        restored = ClinicDatabase(database)
        self.assertEqual(PatientService(restored).get(self.p.id).full_name,
                         "Synthetic Privacy Case")
        self.assertEqual(AttachmentVault(restored, files, self.key).load(self.p.id, att), original)
        with self.assertRaises(ConflictError):
            service.restore_to(backup, "strong-synthetic-archive-password",
                               destination_db=database, destination_attachments=files)

    def test_corrupt_backup_does_not_replace_data(self):
        backup = self.folder / "safe.clinicbackup"
        BackupService(self.db, self.vault_path).create(backup, "strong-synthetic-password")
        raw = bytearray(backup.read_bytes())
        raw[-1] ^= 1
        backup.write_bytes(raw)
        with self.assertRaises(ValidationError):
            BackupService.verify(backup, "strong-synthetic-password")
        self.assertFalse((self.folder / "target.db").exists())
        with self.db.read() as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
