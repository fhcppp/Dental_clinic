"""Versioned SQLite schema and explicitly bounded write transactions.

IMPORTANT: SQLite is not encrypted at rest here. Use synthetic data only until
production authentication, authorization, and encryption are implemented.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 1
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


class ClinicDatabase:
    """Open one SQLite connection per operation, safe for multi-threaded callers."""

    def __init__(self, path: str | Path):
        self.path = str(path)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def initialize(self) -> None:
        """Apply schema v1 once; refuse to open schemas from a newer version."""
        with self.transaction() as conn:
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError("Database schema is newer than this application")
            if version == 0:
                # DDL uses execute (not executescript) to preserve atomic migration.
                for statement in SCHEMA_V1:
                    conn.execute(statement)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

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
