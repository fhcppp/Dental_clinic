"""Transactional HMAC audit chain over legacy audit_events (schema v3).

A separate, externally protected audit key is required for security. The
fixed test key is used ONLY by explicitly insecure synthetic databases.
This detects edits within a retained chain, not full database truncation.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
from collections.abc import Sequence

GENESIS = "0" * 64
KEY_VERSION = 1
INSECURE_TEST_AUDIT_KEY = hashlib.sha256(
    b"dental-clinic synthetic test-only audit key - NOT FOR CLINICAL USE"
).digest()


def canonical_event(fields: Sequence[object]) -> bytes:
    if len(fields) != 8:
        raise ValueError("Audit chain requires 8 canonical fields")
    if type(fields[0]) is not int or type(fields[1]) is not int:
        raise ValueError("Audit sequence and event ID must be integers")
    if not all(isinstance(x, str) for x in fields[2:]):
        raise ValueError("Malformed audit event")
    return json.dumps(
        {"schema": 1, "sequence": fields[0], "event_id": fields[1],
         "occurred_utc": fields[2], "actor_id": fields[3], "action": fields[4],
         "subject_type": fields[5], "subject_id": fields[6],
         "previous_mac": fields[7]},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def event_mac(key: bytes, *fields: object) -> str:
    if not isinstance(key, bytes) or len(key) != 32:
        raise ValueError("Invalid audit HMAC key")
    return hmac.new(key, canonical_event(fields), hashlib.sha256).hexdigest()


def verify_chain(conn: sqlite3.Connection, audit_key: bytes) -> bool:
    """Verify every retained event, its order and its matching keyed MAC.

    Event truncation at the tail is detectable only with an external trusted
    checkpoint. Without one the full database can be rolled back undetected.
    """
    rows = conn.execute("""SELECT c.seq,c.event_id,e.occurred_utc,e.actor_id,
        e.action,e.subject_type,e.subject_id,c.previous_mac,c.mac,c.key_version
        FROM audit_chain c JOIN audit_events e ON c.event_id=e.id
        ORDER BY c.seq""").fetchall()
    count = conn.execute("SELECT count(*) FROM audit_events").fetchone()[0]
    if len(rows) != count:
        return False
    previous = GENESIS
    for sequence, row in enumerate(rows, 1):
        seq, event_id, when, actor, action, kind, subject, prior, mac, key_version = row
        if seq != sequence or key_version != KEY_VERSION or prior != previous:
            return False
        expected = event_mac(audit_key, seq, event_id, when, actor, action, kind,
                             subject, prior)
        if not isinstance(mac, str) or not hmac.compare_digest(mac, expected):
            return False
        previous = mac
    return True


def backfill_chain(conn: sqlite3.Connection, audit_key: bytes) -> None:
    """Sign retained v1/v2 events exactly once, inside the migration TX."""
    previous = GENESIS
    for seq, row in enumerate(conn.execute("""SELECT id,occurred_utc,actor_id,
              action,subject_type,subject_id FROM audit_events ORDER BY id"""), 1):
        ident, when, actor, action, kind, subject = row
        mac = event_mac(audit_key, seq, ident, when, actor, action, kind,
                        subject, previous)
        conn.execute("""INSERT INTO audit_chain
             (seq,event_id,previous_mac,mac,key_version) VALUES (?,?,?,?,?)""",
             (seq, ident, previous, mac, KEY_VERSION))
        previous = mac
