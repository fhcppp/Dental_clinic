"""Versioned envelope keyring and independent recovery-password protection.

A master key wraps separate random purpose-specific 256-bit data keys. A recovery
password separately wraps the master key; it is not tied to any workstation.
No code here claims that the SQLite database is encrypted: SQLCipher integration
is a separate requirement and opening plaintext production databases is denied.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import json
import os
import secrets
from pathlib import Path
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

PURPOSES = ("database", "attachments", "backups")
ENVELOPE_VERSION = 1
KDF_N, KDF_R, KDF_P = 2**15, 8, 1


def _encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _decode(data: str, expected: int | None = None) -> bytes:
    if not isinstance(data, str) or len(data) > 4096:
        raise ValueError("Invalid envelope field")
    try:
        value = base64.b64decode(data, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid envelope encoding") from exc
    if expected is not None and len(value) != expected:
        raise ValueError("Invalid envelope field size")
    return value


def _require_master(key: bytes) -> None:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("A random 32-byte master key is required")


def generate_master_key() -> bytes:
    return secrets.token_bytes(32)


def derive_audit_key(master_key: bytes, *, key_version: int = 1) -> bytes:
    """Purpose-separated audit HMAC key, independent of other data keys.

    The master key must be securely unlocked through a trusted key provider;
    this derived key must never be stored in the SQLite database.
    """
    _require_master(master_key)
    if not 1 <= key_version <= 65535:
        raise ValueError("Invalid audit key version")
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"dental-clinic/audit/hmac-sha256/v{key_version}".encode("ascii")
               ).derive(master_key)


def generate_keyring(master_key: bytes, *, key_version: int = 1) -> dict:
    """Generate independent data keys and wrap each with the master key."""
    _require_master(master_key)
    if not 1 <= key_version <= 65535:
        raise ValueError("Invalid key version")
    entries = {}
    for purpose in PURPOSES:
        data_key = secrets.token_bytes(32)
        nonce = secrets.token_bytes(12)
        aad = f"dental-clinic:key:{purpose}:{key_version}".encode("ascii")
        entries[purpose] = {
            "nonce": _encode(nonce),
            "ciphertext": _encode(AESGCM(master_key).encrypt(nonce, data_key, aad)),
        }
    return {
        "format": "dental-clinic-encrypted-keyring",
        "envelope_version": ENVELOPE_VERSION,
        "key_version": key_version,
        "wrap_cipher": "AES-256-GCM",
        "keys": entries,
    }


def open_keyring(master_key: bytes, envelope: dict) -> dict[str, bytes]:
    _require_master(master_key)
    if (not isinstance(envelope, dict)
        or envelope.get("format") != "dental-clinic-encrypted-keyring"
        or envelope.get("envelope_version") != ENVELOPE_VERSION
        or envelope.get("wrap_cipher") != "AES-256-GCM"
        or not isinstance(envelope.get("key_version"), int)
        or not 1 <= envelope["key_version"] <= 65535
        or not isinstance(envelope.get("keys"), dict)
        or set(envelope["keys"]) != set(PURPOSES)):
        raise ValueError("Unsupported keyring envelope")
    result = {}
    for purpose in PURPOSES:
        entry = envelope["keys"][purpose]
        if not isinstance(entry, dict):
            raise ValueError("Malformed keyring envelope")
        nonce = _decode(entry["nonce"], 12)
        ciphertext = _decode(entry["ciphertext"], 48)
        aad = f"dental-clinic:key:{purpose}:{envelope['key_version']}".encode("ascii")
        try:
            result[purpose] = AESGCM(master_key).decrypt(nonce, ciphertext, aad)
        except InvalidTag as exc:
            raise ValueError("Keyring authentication failed") from exc
    return result


def wrap_recovery_master(master_key: bytes, recovery_password: str) -> dict:
    """Passphrase recovery envelope contains no password and no plaintext key."""
    _require_master(master_key)
    if not isinstance(recovery_password, str) or not 12 <= len(recovery_password) <= 1024:
        raise ValueError("Recovery password length must be between 12 and 1024")
    salt = os.urandom(16)
    nonce = os.urandom(12)
    wrapping_key = hashlib.scrypt(recovery_password.encode("utf-8"), salt=salt,
                                  n=KDF_N, r=KDF_R, p=KDF_P, dklen=32,
                                  maxmem=64 * 1024 * 1024)
    aad = b"dental-clinic:recovery:v1"
    return {
        "format": "dental-clinic-master-recovery",
        "envelope_version": ENVELOPE_VERSION,
        "kdf": {"algorithm": "scrypt", "n": KDF_N, "r": KDF_R,
                "p": KDF_P, "key_length": 32},
        "cipher": "AES-256-GCM",
        "salt": _encode(salt),
        "nonce": _encode(nonce),
        "ciphertext": _encode(AESGCM(wrapping_key).encrypt(nonce, master_key, aad)),
    }


def recover_master(envelope: dict, recovery_password: str) -> bytes:
    if not isinstance(recovery_password, str):
        raise ValueError("Recovery authentication failed")
    if (not isinstance(envelope, dict)
        or envelope.get("format") != "dental-clinic-master-recovery"
        or envelope.get("envelope_version") != ENVELOPE_VERSION
        or envelope.get("cipher") != "AES-256-GCM"
        or envelope.get("kdf") != {"algorithm": "scrypt", "n": KDF_N,
                                   "r": KDF_R, "p": KDF_P, "key_length": 32}):
        raise ValueError("Unsupported recovery envelope")
    salt = _decode(envelope["salt"], 16)
    nonce = _decode(envelope["nonce"], 12)
    ciphertext = _decode(envelope["ciphertext"], 48)
    wrapping_key = hashlib.scrypt(recovery_password.encode("utf-8"), salt=salt,
                                  n=KDF_N, r=KDF_R, p=KDF_P, dklen=32,
                                  maxmem=64 * 1024 * 1024)
    try:
        return AESGCM(wrapping_key).decrypt(nonce, ciphertext,
                                             b"dental-clinic:recovery:v1")
    except InvalidTag as exc:
        raise ValueError("Recovery authentication failed") from exc


def write_private_envelope(path: str | Path, envelope: dict) -> None:
    """Create-only, owner-only metadata file; callers must not overwrite keys."""
    filename = Path(path)
    content = (json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n").encode()
    fd = os.open(filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        filename.unlink(missing_ok=True)
        raise


class KeyProvider(Protocol):
    def unlock(self) -> bytes:
        """Return the master key or fail closed."""


class TestOnlyKeyProvider:
    """Explicitly non-production key provider for deterministic unit tests."""

    def __init__(self, master_key: bytes):
        _require_master(master_key)
        self._key = master_key

    def unlock(self, *, production: bool = True) -> bytes:
        if production:
            raise RuntimeError("Test keys are forbidden in production")
        return self._key


class WindowsDPAPIKeyProvider:
    """Protect a master key for this Windows user using OS DPAPI.

    Requires win32crypt on Windows. Must be verified on real Windows x64.
    The separate recovery envelope is necessary for workstation loss.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @staticmethod
    def _backend():
        if os.name != "nt":
            raise RuntimeError("DPAPI is only available on Windows")
        try:
            return importlib.import_module("win32crypt")
        except ImportError as exc:
            raise RuntimeError("Install the vetted pywin32 Windows package") from exc

    def initialize(self, master_key: bytes) -> None:
        _require_master(master_key)
        api = self._backend()
        ciphertext = api.CryptProtectData(master_key, "Dental Clinic master key", None, None,
                                           None, 0)
        path = self.path
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(ciphertext)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def unlock(self) -> bytes:
        api = self._backend()
        key = api.CryptUnprotectData(self.path.read_bytes(), None, None, None, 0)[1]
        _require_master(key)
        return key
