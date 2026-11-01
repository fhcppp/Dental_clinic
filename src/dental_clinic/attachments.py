"""Encrypted offline attachment store; caller must securely provision the AES-256 key.

No on-disk key storage or implicit permission bypass is provided. In production,
retrieve/store must be invoked only from authenticated, authorized use cases.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path
from uuid import uuid4

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import ClinicDatabase
from .errors import NotFoundError, ValidationError
from .services import _audit, _dt_dump, _patient_exists, _utc_now

MAGIC = b"DENTALVAULT1"
MAX_FILE_BYTES = 25 * 1024 * 1024
ALLOWED = {".pdf": ("application/pdf", b"%PDF-"),
           ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
           ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
           ".png": ("image/png", b"\x89PNG\r\n\x1a\n")}


class AttachmentVault:
    def __init__(self, db: ClinicDatabase, directory: str | Path, key: bytes,
                 *, max_file_bytes: int = MAX_FILE_BYTES):
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValidationError("AES-256 key must contain 32 random bytes")
        if type(max_file_bytes) is not int or not 1 <= max_file_bytes <= 1024 * 1024 * 1024:
            raise ValidationError("Attachment size limit is invalid")
        if Path(directory).is_symlink():
            raise ValidationError("Attachment storage directory cannot be a symlink")
        self.max_file_bytes = max_file_bytes
        self.db = db
        self.root = Path(directory).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cipher = AESGCM(key)

    def store(self, patient_id: str, filename: str, payload: bytes, *, actor_id: str,
              visit_id: str | None = None, treatment_id: str | None = None) -> str:
        if not isinstance(payload, bytes) or not 0 < len(payload) <= self.max_file_bytes:
            raise ValidationError("Attachment exceeds the configured size limit")
        extension = Path(filename).suffix.lower()
        meta = ALLOWED.get(extension)
        if not meta or not payload.startswith(meta[1]):
            raise ValidationError("Unsupported or mismatched file type")
        attachment_id = str(uuid4())
        basename = secrets.token_hex(24) + ".enc"
        nonce = os.urandom(12)
        associated = (patient_id + ":" + attachment_id).encode("utf-8")
        blob = MAGIC + nonce + self.cipher.encrypt(nonce, payload, associated)
        digest = hashlib.sha256(blob).hexdigest()
        path = self.root / basename
        # Use an unpredictable temp name and durable rename, so database rows
        # never reference half-written ciphertext after an interrupted write.
        temporary = self.root / (secrets.token_hex(24) + ".pending")
        try:
            with temporary.open("xb") as stream:
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            with self.db.transaction() as conn:
                _patient_exists(conn, patient_id)
                for table, record_id in (("clinical_visits", visit_id), ("treatments", treatment_id)):
                    if record_id:
                        if not conn.execute("SELECT 1 FROM " + table + " WHERE id=? AND patient_id=?",
                                            (record_id, patient_id)).fetchone():
                            raise ValidationError("Attachment relationship does not match patient")
                conn.execute("""INSERT INTO attachments
                  (id,patient_id,visit_id,treatment_id,storage_name,mime_type,
                   original_extension,ciphertext_bytes,sha256,recorded_utc)
                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
                  (attachment_id, patient_id, visit_id, treatment_id, basename,
                   meta[0], extension, len(blob), digest, _dt_dump(_utc_now())))
                _audit(conn, actor_id, "attachment.created", "attachment", attachment_id)
        except BaseException:
            temporary.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
            raise
        return attachment_id

    def load(self, patient_id: str, attachment_id: str) -> bytes:
        with self.db.read() as conn:
            record = conn.execute("SELECT * FROM attachments WHERE id = ? AND patient_id = ?",
                                  (attachment_id, patient_id)).fetchone()
        if record is None:
            raise NotFoundError("Attachment not found")
        basename = record["storage_name"]
        # A database corruption or poisoned filename must never escape the vault.
        if not basename.endswith(".enc") or len(basename) != 52 or not all(
            c in "0123456789abcdef" for c in basename[:-4]
        ):
            raise ValidationError("Invalid attachment storage reference")
        path = self.root / basename
        if path.is_symlink():
            raise ValidationError("Symbolic links are not valid attachments")
        try:
            blob = path.read_bytes()
        except OSError as exc:
            raise NotFoundError("Attachment ciphertext is unavailable") from exc
        if (len(blob) != record["ciphertext_bytes"]
            or hashlib.sha256(blob).hexdigest() != record["sha256"]
            or not blob.startswith(MAGIC)):
            raise ValidationError("Attachment integrity check failed")
        offset = len(MAGIC)
        try:
            data = self.cipher.decrypt(blob[offset:offset+12], blob[offset+12:],
                                       (patient_id + ":" + attachment_id).encode("utf-8"))
        except InvalidTag as exc:
            raise ValidationError("Attachment authentication failed") from exc
        return data
