"""Offline application services. No network traffic or medical advice."""

import sqlite3
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from .db import ClinicDatabase
from .errors import ConflictError, NotFoundError, ValidationError
from .fdi import validate_fdi
from .models import Appointment, Patient, ToothRecord, ToothState

TOOTH_STATES: frozenset[str] = frozenset(
    {"healthy", "decayed", "missing", "restored", "implant"}
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _dt_dump(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _dt_load(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _audit(
    conn: sqlite3.Connection, actor: str, action: str, kind: str, subject_id: str
) -> None:
    if not isinstance(actor, str) or not (1 <= len(actor.strip()) <= 100):
        raise ValidationError("Actor identifier is required")
    conn.execute(
        """INSERT INTO audit_events
           (occurred_utc, actor_id, action, subject_type, subject_id)
           VALUES (?, ?, ?, ?, ?)""",
        (_dt_dump(_utc_now()), actor.strip(), action, kind, subject_id),
    )


def _patient(row: sqlite3.Row) -> Patient:
    return Patient(
        id=row["id"],
        full_name=row["full_name"],
        birth_date=date.fromisoformat(row["birth_date"]) if row["birth_date"] else None,
        phone=row["phone"],
        active=bool(row["active"]),
        created_utc=_dt_load(row["created_utc"]),
    )


def _appointment(row: sqlite3.Row) -> Appointment:
    return Appointment(
        id=row["id"],
        patient_id=row["patient_id"],
        practitioner_id=row["practitioner_id"],
        start_utc=_dt_load(row["start_utc"]),
        end_utc=_dt_load(row["end_utc"]),
        status=row["status"],
        room_id=row["room_id"],
    )


def _patient_exists(conn: sqlite3.Connection, patient_id: str) -> None:
    row = conn.execute("SELECT active FROM patients WHERE id = ?", (patient_id,)).fetchone()
    if row is None:
        raise NotFoundError("Patient not found")
    if not row["active"]:
        raise ConflictError("Patient is inactive")


def _validate_interval(start: datetime, end: datetime) -> tuple[str, str]:
    if not isinstance(start, datetime) or not isinstance(end, datetime):
        raise ValidationError("Appointments require datetime values")
    if start.tzinfo is None or end.tzinfo is None:
        raise ValidationError("Appointments require timezone-aware datetimes")
    if start.utcoffset() is None or end.utcoffset() is None:
        raise ValidationError("Appointments require valid timezone offsets")
    # Normalize before subtraction: wall-clock arithmetic can be wrong across DST folds.
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if not timedelta(0) < end_utc - start_utc <= timedelta(hours=8):
        raise ValidationError("Appointment duration must be above zero and at most 8 hours")
    return _dt_dump(start_utc), _dt_dump(end_utc)


def _check_conflict(
    conn: sqlite3.Connection,
    patient_id: str,
    practitioner_id: str,
    start_utc: str,
    end_utc: str,
    excluding: str = "",
    room_id: str | None = None,
) -> None:
    collision = conn.execute(
        """SELECT id FROM appointments
           WHERE status = 'scheduled'
             AND id != ?
             AND start_utc < ? AND end_utc > ?
             AND (patient_id = ? OR practitioner_id = ? OR (? IS NOT NULL AND room_id = ?))
           LIMIT 1""",
        (excluding, end_utc, start_utc, patient_id, practitioner_id, room_id, room_id),
    ).fetchone()
    if collision:
        raise ConflictError("The patient or practitioner has an overlapping appointment")


class PatientService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def create(
        self,
        full_name: str,
        birth_date: date | None = None,
        phone: str | None = None,
        *,
        actor_id: str = "system",
    ) -> Patient:
        if not isinstance(full_name, str) or not (1 <= len(full_name.strip()) <= 200):
            raise ValidationError("Name must contain 1 to 200 characters")
        if birth_date is not None and (
            not isinstance(birth_date, date)
            or isinstance(birth_date, datetime)
            or birth_date > date.today()
        ):
            raise ValidationError("Birth date must be a date not in the future")
        if phone is not None and (not isinstance(phone, str) or len(phone) > 80):
            raise ValidationError("Phone must contain at most 80 characters")
        pid = str(uuid4())
        with self.db.transaction() as conn:
            conn.execute(
                """INSERT INTO patients
                   (id, full_name, birth_date, phone, created_utc)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    pid,
                    full_name.strip(),
                    birth_date.isoformat() if birth_date else None,
                    phone.strip() if phone else None,
                    _dt_dump(_utc_now()),
                ),
            )
            _audit(conn, actor_id, "patient.created", "patient", pid)
            row = conn.execute("SELECT * FROM patients WHERE id = ?", (pid,)).fetchone()
            assert row is not None
            return _patient(row)

    def get(self, patient_id: str) -> Patient:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if row is None:
            raise NotFoundError("Patient not found")
        return _patient(row)

    def list_active(self) -> list[Patient]:
        with self.db.read() as conn:
            rows = conn.execute(
                "SELECT * FROM patients WHERE active = 1 ORDER BY full_name, id"
            ).fetchall()
        return [_patient(row) for row in rows]

    def deactivate(self, patient_id: str, *, actor_id: str = "system") -> Patient:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
            if row is None:
                raise NotFoundError("Patient not found")
            # Do not silently invalidate already scheduled appointments.
            if conn.execute(
                """SELECT 1 FROM appointments
                   WHERE patient_id = ? AND status = 'scheduled' LIMIT 1""",
                (patient_id,),
            ).fetchone():
                raise ConflictError("Cancel outstanding appointments before deactivating")
            if row["active"]:
                conn.execute("UPDATE patients SET active = 0 WHERE id = ?", (patient_id,))
                _audit(conn, actor_id, "patient.deactivated", "patient", patient_id)
            updated = conn.execute(
                "SELECT * FROM patients WHERE id = ?", (patient_id,)
            ).fetchone()
            assert updated is not None
            return _patient(updated)


class AppointmentService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def schedule(
        self,
        patient_id: str,
        practitioner_id: str,
        start: datetime,
        end: datetime,
        *,
        actor_id: str = "system",
        room_id: str | None = None,
    ) -> Appointment:
        if not isinstance(practitioner_id, str) or not (
            1 <= len(practitioner_id.strip()) <= 100
        ):
            raise ValidationError("Practitioner identifier is required")
        start_utc, end_utc = _validate_interval(start, end)
        aid = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            if room_id is not None:
                room = conn.execute("SELECT active FROM clinic_rooms WHERE id=?", (room_id,)).fetchone()
                if not room or not room["active"]:
                    raise ValidationError("Active treatment room required")
            _check_conflict(
                conn, patient_id, practitioner_id.strip(), start_utc, end_utc,
                room_id=room_id,
            )
            conn.execute(
                """INSERT INTO appointments
                   (id, patient_id, practitioner_id, start_utc, end_utc, status, room_id)
                   VALUES (?, ?, ?, ?, ?, 'scheduled', ?)""",
                (aid, patient_id, practitioner_id.strip(), start_utc, end_utc, room_id),
            )
            _audit(conn, actor_id, "appointment.scheduled", "appointment", aid)
            row = conn.execute("SELECT * FROM appointments WHERE id = ?", (aid,)).fetchone()
            assert row is not None
            return _appointment(row)

    def get(self, appointment_id: str) -> Appointment:
        with self.db.read() as conn:
            row = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Appointment not found")
        return _appointment(row)

    def cancel(self, appointment_id: str, *, actor_id: str = "system") -> Appointment:
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("Appointment not found")
            if row["status"] != "cancelled":
                conn.execute(
                    "UPDATE appointments SET status = 'cancelled' WHERE id = ?",
                    (appointment_id,),
                )
                _audit(conn, actor_id, "appointment.cancelled", "appointment", appointment_id)
            updated = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            assert updated is not None
            return _appointment(updated)

    def reschedule(
        self,
        appointment_id: str,
        start: datetime,
        end: datetime,
        *,
        actor_id: str = "system",
    ) -> Appointment:
        start_utc, end_utc = _validate_interval(start, end)
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("Appointment not found")
            if row["status"] != "scheduled":
                raise ConflictError("Cannot reschedule a cancelled appointment")
            _patient_exists(conn, row["patient_id"])
            _check_conflict(
                conn,
                row["patient_id"],
                row["practitioner_id"],
                start_utc,
                end_utc,
                excluding=appointment_id,
                room_id=row["room_id"],
            )
            conn.execute(
                """UPDATE appointments SET start_utc = ?, end_utc = ?
                   WHERE id = ?""",
                (start_utc, end_utc, appointment_id),
            )
            _audit(conn, actor_id, "appointment.rescheduled", "appointment", appointment_id)
            updated = conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
            assert updated is not None
            return _appointment(updated)

    def list_for_patient(self, patient_id: str) -> list[Appointment]:
        with self.db.read() as conn:
            rows = conn.execute(
                """SELECT * FROM appointments WHERE patient_id = ?
                   ORDER BY start_utc, id""",
                (patient_id,),
            ).fetchall()
        return [_appointment(row) for row in rows]


class OdontogramService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def set_state(
        self,
        patient_id: str,
        fdi_code: int,
        state: ToothState,
        *,
        actor_id: str = "system",
    ) -> ToothRecord:
        code = validate_fdi(fdi_code)
        if not isinstance(state, str) or state not in TOOTH_STATES:
            raise ValidationError("Unsupported tooth state")
        updated_utc = _dt_dump(_utc_now())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            conn.execute(
                """INSERT INTO tooth_records (patient_id, fdi_code, state, updated_utc)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(patient_id, fdi_code)
                   DO UPDATE SET state = excluded.state, updated_utc = excluded.updated_utc""",
                (patient_id, code, state, updated_utc),
            )
            conn.execute("""INSERT INTO tooth_state_events
                           (id,patient_id,fdi_code,state,recorded_utc,actor_id)
                           VALUES (?,?,?,?,?,?)""",
                         (str(uuid4()), patient_id, code, state, updated_utc, actor_id))
            _audit(conn, actor_id, "tooth.state_set", "patient", patient_id)
        return ToothRecord(patient_id, code, state, _dt_load(updated_utc))

    def list_for_patient(self, patient_id: str) -> list[ToothRecord]:
        with self.db.read() as conn:
            rows = conn.execute(
                """SELECT * FROM tooth_records WHERE patient_id = ?
                   ORDER BY fdi_code""",
                (patient_id,),
            ).fetchall()
        return [
            ToothRecord(row["patient_id"], row["fdi_code"], row["state"],
                        _dt_load(row["updated_utc"]))
            for row in rows
        ]


class ClinicRoomService:
    """Local room directory for appointment conflict validation."""

    def __init__(self, db: ClinicDatabase):
        self.db = db

    def add(self, room_id: str, display_name: str, *, actor_id: str = "system") -> None:
        if not isinstance(room_id, str) or not room_id.strip() or not display_name.strip():
            raise ValidationError("Room identifier and name required")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO clinic_rooms VALUES (?,?,1)",
                         (room_id.strip(), display_name.strip()))
            _audit(conn, actor_id, "room.created", "room", room_id)
