"""Offline Argon2id authentication with hashed session tokens and RBAC primitives.

Legacy services that accept caller-supplied actor_id are NOT yet protected by this
boundary; integration of every service through authenticated use cases is required.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from uuid import uuid4

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

from .db import ClinicDatabase
from .errors import ConflictError, ValidationError
from .services import _audit, _dt_dump, _dt_load, _utc_now

PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2, type=Type.ID)
# Avoid revealing whether an attempted username exists through different
# password-hash work; generated at application startup, never a real account.
_DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash("not-a-real-clinic-account-password")
LOGIN_FAILURE_THRESHOLD = 5
MAX_LOGIN_DELAY_SECONDS = 15 * 60
PERMISSIONS = {
    "administrator": {"users.manage", "patients.read", "patients.write", "clinical.write",
                      "billing.write", "backups.manage"},
    "dentist": {"patients.read", "patients.write", "clinical.write"},
    "receptionist": {"patients.read", "patients.write", "billing.write"},
    "dental_assistant": {"patients.read"},
}
SESSION_TTL = timedelta(hours=8)
IDLE_TIMEOUT = timedelta(minutes=15)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_ok(password: str) -> None:
    if not isinstance(password, str) or len(password) < 12 or len(password) > 1024:
        raise ValidationError("Password must be 12-1024 characters")


class AuthService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def bootstrap_admin(self, username: str, password: str) -> str:
        _password_ok(password)
        if not isinstance(username, str) or not username.strip():
            raise ValidationError("Username required")
        uid = str(uuid4())
        digest = PASSWORD_HASHER.hash(password)
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                raise ConflictError("Administrator already initialized")
            conn.execute("INSERT INTO users VALUES (?, ?, ?, 'administrator', 1, ?)",
                         (uid, username.strip(), digest, _dt_dump(_utc_now())))
            _audit(conn, uid, "users.admin_initialized", "user", uid)
        return uid

    def login(self, username: str, password: str) -> str:
        """Authenticate with bounded inputs, shared errors and progressive delays.

        Failed attempts are committed along with their audit events before an
        error is returned. All concurrent attempts use BEGIN IMMEDIATE.
        """
        generic = "Invalid username or password"
        if (not isinstance(username, str) or not isinstance(password, str)
            or not 1 <= len(username.strip()) <= 128 or len(password) > 1024):
            raise ValidationError(generic)
        username = username.strip()
        fingerprint = hashlib.sha256(username.casefold().encode("utf-8")).hexdigest()
        now = _utc_now()
        token: str | None = None
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username=? COLLATE NOCASE AND active=1",
                (username,),
            ).fetchone()
            attempt = conn.execute(
                "SELECT failures,retry_utc FROM auth_login_attempts WHERE username_digest=?",
                (fingerprint,),
            ).fetchone()
            blocked = bool(attempt is not None and attempt["retry_utc"]
                           and _dt_load(attempt["retry_utc"]) > now)
            if not blocked:
                try:
                    PASSWORD_HASHER.verify(
                        row["password_hash"] if row is not None else _DUMMY_PASSWORD_HASH,
                        password,
                    )
                    valid = row is not None
                except (VerificationError, InvalidHashError):
                    valid = False
                if valid:
                    conn.execute(
                        "DELETE FROM auth_login_attempts WHERE username_digest=?",
                        (fingerprint,),
                    )
                    token = secrets.token_urlsafe(48)
                    conn.execute(
                        "INSERT INTO local_sessions VALUES (?,?,?,?,0)",
                        (_hash_token(token), row["id"], _dt_dump(now + SESSION_TTL),
                         _dt_dump(now)),
                    )
                    _audit(conn, row["id"], "session.started", "user", row["id"])
                else:
                    failures = int(attempt["failures"]) + 1 if attempt else 1
                    # Five failures trigger 15 seconds, then 30, 60, ... up
                    # to 15 minutes. No permanent lockout: prevents trivial
                    # denial of service by permanently disabling an account.
                    delay = (min(MAX_LOGIN_DELAY_SECONDS,
                                 15 * 2 ** min(failures - LOGIN_FAILURE_THRESHOLD, 6))
                             if failures >= LOGIN_FAILURE_THRESHOLD else 0)
                    retry = _dt_dump(now + timedelta(seconds=delay)) if delay else None
                    conn.execute(
                        """INSERT INTO auth_login_attempts
                           (username_digest,failures,retry_utc,updated_utc)
                           VALUES (?,?,?,?) ON CONFLICT(username_digest) DO UPDATE SET
                           failures=excluded.failures,retry_utc=excluded.retry_utc,
                           updated_utc=excluded.updated_utc""",
                        (fingerprint, failures, retry, _dt_dump(now)),
                    )
                    _audit(conn, "unauthenticated", "auth.login_failed", "login", fingerprint)
            else:
                _audit(conn, "unauthenticated", "auth.login_delayed", "login", fingerprint)
        if token is None:
            raise ValidationError(generic)
        return token

    def authorize(self, token: str, permission: str) -> str:
        if not isinstance(token, str) or len(token) > 256:
            raise ValidationError("Session invalid or expired")
        now = _utc_now()
        with self.db.transaction() as conn:
            row = conn.execute("""SELECT s.expires_utc,s.last_seen_utc,s.revoked,
                               u.id,u.active,u.role FROM local_sessions s JOIN users u
                               ON u.id=s.user_id WHERE s.token_hash=?""",
                               (_hash_token(token),)).fetchone()
            if (not row or row["revoked"] or not row["active"]
                or _dt_load(row["expires_utc"]) <= now
                or _dt_load(row["last_seen_utc"]) + IDLE_TIMEOUT <= now):
                raise ValidationError("Session invalid or expired")
            if permission not in PERMISSIONS[row["role"]]:
                raise ValidationError("Permission denied")
            conn.execute("UPDATE local_sessions SET last_seen_utc=? WHERE token_hash=?",
                         (_dt_dump(now), _hash_token(token)))
            return row["id"]

    def logout(self, token: str) -> None:
        with self.db.transaction() as conn:
            conn.execute("UPDATE local_sessions SET revoked=1 WHERE token_hash=?",
                         (_hash_token(token),))

    def create_user(self, token: str, username: str, password: str, role: str) -> str:
        actor = self.authorize(token, "users.manage")
        _password_ok(password)
        if role not in PERMISSIONS or not username.strip():
            raise ValidationError("Invalid username or role")
        uid = str(uuid4())
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO users VALUES (?,?,?,?,1,?)",
                         (uid, username.strip(), PASSWORD_HASHER.hash(password), role,
                          _dt_dump(_utc_now())))
            _audit(conn, actor, "users.created", "user", uid)
        return uid

    def deactivate_user(self, token: str, user_id: str) -> None:
        actor = self.authorize(token, "users.manage")
        if actor == user_id:
            raise ConflictError("Administrator cannot deactivate their own account")
        with self.db.transaction() as conn:
            if conn.execute("UPDATE users SET active=0 WHERE id=?", (user_id,)).rowcount != 1:
                raise ValidationError("User not found")
            conn.execute("UPDATE local_sessions SET revoked=1 WHERE user_id=?", (user_id,))
            _audit(conn, actor, "users.deactivated", "user", user_id)

    def change_password(self, token: str, old_password: str, new_password: str) -> None:
        actor = self.authorize(token, "patients.read")
        _password_ok(new_password)
        with self.db.transaction() as conn:
            row = conn.execute("SELECT password_hash FROM users WHERE id=?", (actor,)).fetchone()
            assert row is not None
            try:
                PASSWORD_HASHER.verify(row["password_hash"], old_password)
            except (VerificationError, InvalidHashError) as exc:
                raise ValidationError("Incorrect current password") from exc
            conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                         (PASSWORD_HASHER.hash(new_password), actor))
            conn.execute("UPDATE local_sessions SET revoked=1 WHERE user_id=?", (actor,))
            _audit(conn, actor, "users.password_changed", "user", actor)
