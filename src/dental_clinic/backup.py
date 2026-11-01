"""Encrypted, manifest-checked offline backups, restored only to new paths.

Backup encryption is separate from the database-at-rest encryption requirement.
Key management, scheduler integration and live-database replacement are not implemented.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import SCHEMA_VERSION, ClinicDatabase
from .errors import ConflictError, ValidationError

BACKUP_MAGIC = b"DENTALBACKUP1"
MAX_BACKUP_BYTES = 128 * 1024 * 1024


def _derive(password: str, salt: bytes) -> bytes:
    if not isinstance(password, str) or len(password) < 12:
        raise ValidationError("Backup passphrase must be at least 12 characters")
    return hashlib.scrypt(password.encode("utf-8"), salt=salt,
                          n=2**14, r=8, p=1, dklen=32)


def _archive_contents(data: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(data), "r") as z:
            names = z.namelist()
            if len(names) != len(set(names)) or "database.sqlite3" not in names or "manifest.json" not in names:
                raise ValidationError("Backup manifest or database missing")
            total = sum(info.file_size for info in z.infolist())
            if total > MAX_BACKUP_BYTES or any(info.file_size > MAX_BACKUP_BYTES for info in z.infolist()):
                raise ValidationError("Backup is too large")
            if any(not (name in {"database.sqlite3", "manifest.json"} or
                        (name.startswith("attachments/") and name.endswith(".enc")
                         and len(name) == len("attachments/") + 52 and
                         all(c in "0123456789abcdef" for c in name[len("attachments/"):-4])))
                   for name in names):
                raise ValidationError("Untrusted backup archive path")
            content = {name: z.read(name) for name in names}
            manifest = json.loads(content.pop("manifest.json").decode("utf-8"))
            hashes = manifest.get("sha256", {})
            if not isinstance(hashes, dict) or set(hashes) != set(content):
                raise ValidationError("Manifest file list does not match archive")
            for name, blob in content.items():
                if hashlib.sha256(blob).hexdigest() != hashes[name]:
                    raise ValidationError("Backup file checksum mismatch")
            schema = manifest.get("schema_version")
            if type(schema) is not int or schema != SCHEMA_VERSION:
                raise ValidationError("Unsupported backup schema version")
            return content
    except (zipfile.BadZipFile, UnicodeError, ValueError, KeyError, RuntimeError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("Backup archive invalid") from exc


class BackupService:
    def __init__(self, db: ClinicDatabase, attachment_dir: str | Path):
        self.db = db
        self.attachment_dir = Path(attachment_dir)

    def create(self, destination: str | Path, password: str) -> Path:
        """Take a SQLite-consistent online snapshot, then encrypt the archive."""
        output = Path(destination)
        if output.exists():
            raise ConflictError("Backup destination already exists")
        salt = os.urandom(16)
        key = _derive(password, salt)
        with tempfile.TemporaryDirectory() as td:
            snapshot = Path(td) / "database.sqlite3"
            with self.db.read() as source:
                with sqlite3.connect(snapshot) as target:
                    source.backup(target)
            db_bytes = snapshot.read_bytes()
            source_files = {"database.sqlite3": db_bytes}
            if self.attachment_dir.exists():
                for path in sorted(self.attachment_dir.iterdir()):
                    if path.is_symlink():
                        raise ValidationError("Attachment symlink cannot be backed up")
                    if not path.is_file() or not path.name.endswith(".enc"):
                        continue
                    source_files["attachments/" + path.name] = path.read_bytes()
            if sum(map(len, source_files.values())) > MAX_BACKUP_BYTES:
                raise ValidationError("Backup is too large")
            manifest = {"schema_version": SCHEMA_VERSION,
                        "sha256": {name: hashlib.sha256(blob).hexdigest()
                                   for name, blob in source_files.items()}}
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
                for name, blob in source_files.items():
                    z.writestr(name, blob)
                z.writestr("manifest.json", json.dumps(manifest, sort_keys=True))
            nonce = os.urandom(12)
            encrypted = (BACKUP_MAGIC + salt + nonce +
                         AESGCM(key).encrypt(nonce, archive.getvalue(), BACKUP_MAGIC))
            if len(encrypted) > MAX_BACKUP_BYTES:
                raise ValidationError("Encrypted backup exceeds limit")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("xb") as stream:
                stream.write(encrypted)
        return output

    @staticmethod
    def verify(source: str | Path, password: str) -> dict[str, bytes]:
        raw = Path(source).read_bytes()
        if not raw.startswith(BACKUP_MAGIC) or len(raw) > MAX_BACKUP_BYTES:
            raise ValidationError("Invalid encrypted backup envelope")
        pos = len(BACKUP_MAGIC)
        salt, nonce, encrypted = raw[pos:pos+16], raw[pos+16:pos+28], raw[pos+28:]
        try:
            decrypted = AESGCM(_derive(password, salt)).decrypt(nonce, encrypted, BACKUP_MAGIC)
        except InvalidTag as exc:
            raise ValidationError("Backup password incorrect or contents modified") from exc
        contents = _archive_contents(decrypted)
        # A validated archive could still carry a malformed SQLite database.
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "inspect.db"
            db_path.write_bytes(contents["database.sqlite3"])
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValidationError("SQLite snapshot failed integrity check")
                version = conn.execute("PRAGMA user_version").fetchone()[0]
                if version != SCHEMA_VERSION:
                    raise ValidationError("SQLite schema version mismatch")
        return contents

    @staticmethod
    def restore_to(source: str | Path, password: str, *, destination_db: str | Path,
                   destination_attachments: str | Path) -> None:
        """Restore into *new* locations; never overwrite the live clinic database."""
        contents = BackupService.verify(source, password)
        db_dest = Path(destination_db)
        dir_dest = Path(destination_attachments)
        if db_dest.exists() or dir_dest.exists():
            raise ConflictError("Restore destinations must not exist")
        db_dest.parent.mkdir(parents=True, exist_ok=True)
        dir_dest.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=db_dest.parent) as td:
            staging = Path(td)
            staged_db = staging / "database.sqlite3"
            staged_db.write_bytes(contents.pop("database.sqlite3"))
            staged_files = staging / "attachments"
            staged_files.mkdir()
            for name, blob in contents.items():
                (staged_files / name.split("/", 1)[1]).write_bytes(blob)
            if db_dest.exists() or dir_dest.exists():
                raise ConflictError("Restore destination became occupied")
            # Two filesystem moves are not one atomic transaction; caller should
            # restore to a staging location and switch services while stopped.
            os.replace(staged_files, dir_dest)
            try:
                os.replace(staged_db, db_dest)
            except BaseException:
                # Deliberately do not remove user data without manual review.
                raise
