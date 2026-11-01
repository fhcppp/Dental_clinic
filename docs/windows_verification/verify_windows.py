"""One-time native Windows x64 security smoke test with synthetic data only.

Runs DPAPI and SQLCipher basics in a temporary folder. Requires vetted native
Windows pywin32/sqlcipher3 distributions installed by the clinic integrator.
This script does not verify entire application packaging or production safety.
"""
from __future__ import annotations

import importlib
import os
import platform
import sqlite3
import sys
import tempfile
from pathlib import Path


def main() -> int:
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        print("UNVERIFIED: must run on native Windows x64")
        return 2
    errors = []
    try:
        win32crypt = importlib.import_module("win32crypt")
        secret = os.urandom(32)
        encrypted = win32crypt.CryptProtectData(secret, "synthetic DPAPI test", None,
                                                None, None, 0)
        assert encrypted != secret
        assert win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1] == secret
        print("PASS: native Windows DPAPI user-scoped roundtrip")
    except (ImportError, OSError, AssertionError, RuntimeError) as exc:
        errors.append(f"DPAPI not verified: {type(exc).__name__}")

    try:
        driver = importlib.import_module("sqlcipher3")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "synthetic-encrypted.db"
            password = os.urandom(32).hex()
            with driver.connect(str(path)) as conn:
                conn.execute(f"PRAGMA key = \"x'{password}'\"")
                conn.execute("CREATE TABLE synthetic_check(value TEXT NOT NULL)")
                conn.execute("INSERT INTO synthetic_check VALUES('synthetic-only')")
            with driver.connect(str(path)) as conn:
                conn.execute(f"PRAGMA key = \"x'{password}'\"")
                assert conn.execute("SELECT value FROM synthetic_check").fetchone()[0] == "synthetic-only"
            with driver.connect(str(path)) as conn:
                conn.execute("PRAGMA key = 'wrong-key'")
                try:
                    conn.execute("SELECT value FROM synthetic_check").fetchone()
                    raise AssertionError("Wrong SQLCipher key unexpectedly succeeded")
                except driver.DatabaseError:
                    pass
            with sqlite3.connect(path) as conn:
                try:
                    conn.execute("SELECT value FROM synthetic_check").fetchone()
                    raise AssertionError("Plain SQLite unexpectedly read encrypted database")
                except sqlite3.DatabaseError:
                    pass
            print("PASS: SQLCipher native encrypted read, wrong key rejection, plaintext rejection")
    except (ImportError, AssertionError, OSError, RuntimeError, sqlite3.DatabaseError) as exc:
        errors.append(f"SQLCipher not verified: {type(exc).__name__}")

    if errors:
        for error in errors:
            print("UNVERIFIED:", error)
        return 1
    print("PASS: Windows smoke tests (not a release acceptance test)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
