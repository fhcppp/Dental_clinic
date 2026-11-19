"""Structured, append-only medical-history events and patient profile revisions.

These APIs are *not* an authorization boundary: a trusted authenticated session
must replace caller-supplied actor_id before use with real patient data.
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from .db import ClinicDatabase
from .errors import NotFoundError, ValidationError
from .services import _audit, _dt_dump, _patient_exists, _utc_now

PROFILE_FIELDS = frozenset({
    "full_name", "first_name", "last_name", "birth_date", "phone", "secondary_phone",
    "gender", "email", "address", "emergency_name", "emergency_phone",
    "administrative_notes", "estimated_age", "age_reference_date",
})
DATE_FIELDS = frozenset({"birth_date", "age_reference_date"})
MEDICAL_CATEGORIES = frozenset({"condition", "allergy", "medication", "alert"})
MEDICAL_FIELDS = frozenset({"reaction", "severity", "dosage", "frequency", "route",
                            "diagnosed_on", "start_on", "end_on", "last_reviewed_on",
                            "prescriber", "notes"})
MEDICAL_DATE_FIELDS = frozenset({"diagnosed_on", "start_on", "end_on", "last_reviewed_on"})


def age_on(dob: date | None, as_of: date, estimated_age: int | None = None,
           reference_date: date | None = None) -> tuple[int | None, bool]:
    """Return (age, approximate), with leap-day birthdays handled by date comparison."""
    if dob is not None:
        if dob > as_of:
            raise ValidationError("Date of birth cannot be in the future")
        return (as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day)), False)
    if estimated_age is not None and reference_date is not None:
        if estimated_age < 0 or reference_date > as_of:
            raise ValidationError("Invalid approximate age reference")
        return (estimated_age + as_of.year - reference_date.year -
                ((as_of.month, as_of.day) < (reference_date.month, reference_date.day)), True)
    return (None, False)


def _iso_date(value: object, label: str) -> str | None:
    if value is None:
        return None
    if type(value) is not date:
        raise ValidationError(f"{label} must be a date")
    return value.isoformat()


def _str(value: object, field: str, limit: int = 5000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit:
        raise ValidationError(f"Invalid {field}")
    return value.strip()


class MedicalService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def update_profile(self, patient_id: str, changes: dict[str, object], *,
                       actor_id: str) -> dict[str, object]:
        if not changes or not changes.keys() <= PROFILE_FIELDS:
            raise ValidationError("Unknown or empty patient profile change")
        values: dict[str, object] = {}
        for field, value in changes.items():
            if field in DATE_FIELDS:
                values[field] = _iso_date(value, field)
            elif field == "estimated_age":
                if value is not None and (type(value) is not int or not 0 <= value <= 130):
                    raise ValidationError("Estimated age must be 0..130")
                values[field] = value
            else:
                values[field] = _str(value, field, 200 if field == "full_name" else 5000)
                if field in {"full_name", "first_name", "last_name"} and not values[field]:
                    raise ValidationError(f"{field} cannot be blank")
                if "phone" in field and values[field] and not all(
                    ch.isdigit() or ch in "+- ()/." for ch in str(values[field])
                ):
                    raise ValidationError("Phone contains unsupported characters")
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            old = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
            assert old is not None
            future = dict(old)
            future.update(values)
            dob = date.fromisoformat(future["birth_date"]) if future["birth_date"] else None
            ref = (date.fromisoformat(future["age_reference_date"])
                   if future["age_reference_date"] else None)
            if dob and (future["estimated_age"] is not None or ref is not None):
                raise ValidationError("Exact and approximate age cannot coexist")
            if (future["estimated_age"] is None) != (ref is None):
                raise ValidationError("Approximate age needs a reference date")
            age_on(dob, date.today(), future["estimated_age"], ref)
            previous = [old[k] for k in ("full_name", "birth_date", "phone", "first_name",
                         "last_name", "gender", "email", "secondary_phone", "address",
                         "emergency_name", "emergency_phone", "administrative_notes",
                         "estimated_age", "age_reference_date")]
            conn.execute("""INSERT INTO patient_profile_revisions
                (id, patient_id, recorded_utc, actor_id, old_full_name, old_birth_date,
                 old_phone, old_first_name, old_last_name, old_gender, old_email,
                 old_secondary_phone, old_address, old_emergency_name, old_emergency_phone,
                 old_administrative_notes, old_estimated_age, old_age_reference_date)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (str(uuid4()), patient_id, _dt_dump(_utc_now()), actor_id, *previous))
            conn.execute("UPDATE patients SET " + ", ".join(f"{k} = ?" for k in values)
                         + " WHERE id = ?", (*values.values(), patient_id))
            _audit(conn, actor_id, "patient.profile_updated", "patient", patient_id)
            row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
            assert row is not None
            return dict(row)

    def profile(self, patient_id: str, *, as_of: date | None = None) -> dict[str, object]:
        with self.db.read() as conn:
            row = conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if row is None:
            raise NotFoundError("Patient not found")
        item = dict(row)
        dob = date.fromisoformat(item["birth_date"]) if item["birth_date"] else None
        ref = date.fromisoformat(item["age_reference_date"]) if item["age_reference_date"] else None
        item["calculated_age"], item["approximate_age"] = age_on(
            dob, as_of or date.today(), item["estimated_age"], ref)
        return item

    def possible_duplicates(self, full_name: str, birth_date: date | None = None) -> list[str]:
        normalized = " ".join(full_name.split()).casefold()
        with self.db.read() as conn:
            rows = conn.execute("SELECT id, full_name, birth_date FROM patients").fetchall()
        return [r["id"] for r in rows if " ".join(r["full_name"].split()).casefold()
                == normalized and (birth_date is None or r["birth_date"] == birth_date.isoformat())]

    def add_entry(self, patient_id: str, category: str, label: str, status: str, *,
                  actor_id: str, supersedes_id: str | None = None,
                  **details: object) -> str:
        if category not in MEDICAL_CATEGORIES or not isinstance(label, str) or not label.strip():
            raise ValidationError("Invalid medical entry")
        if not isinstance(status, str) or not status.strip():
            raise ValidationError("Status is required")
        if not details.keys() <= MEDICAL_FIELDS:
            raise ValidationError("Unsupported medical field")
        sanitized = {k: (_iso_date(v, k) if k in MEDICAL_DATE_FIELDS else _str(v, k))
                     for k, v in details.items()}
        entry_id = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            if supersedes_id:
                prior = conn.execute("SELECT patient_id, category FROM medical_entries WHERE id = ?",
                                     (supersedes_id,)).fetchone()
                if not prior or prior["patient_id"] != patient_id or prior["category"] != category:
                    raise ValidationError("Amendment target must be same patient's category")
                if conn.execute("SELECT 1 FROM medical_entries WHERE supersedes_id = ?",
                                (supersedes_id,)).fetchone():
                    raise ValidationError("Medical record already superseded")
            fields = ["id", "patient_id", "category", "label", "status", "recorded_utc",
                      "recorded_by", "supersedes_id", *sanitized]
            values = [entry_id, patient_id, category, label.strip(), status.strip(),
                      _dt_dump(_utc_now()), actor_id, supersedes_id, *sanitized.values()]
            conn.execute("INSERT INTO medical_entries (" + ",".join(fields) + ") VALUES ("
                         + ",".join("?" for _ in fields) + ")", values)
            _audit(conn, actor_id, "medical." + category + ".recorded", "patient", patient_id)
        return entry_id

    def history(self, patient_id: str, category: str | None = None, *,
                current_only: bool = False) -> list[dict[str, object]]:
        if category is not None and category not in MEDICAL_CATEGORIES:
            raise ValidationError("Unknown medical category")
        sql = "SELECT * FROM medical_entries e WHERE patient_id = ?"
        args: list[object] = [patient_id]
        if category:
            sql += " AND category = ?"
            args.append(category)
        if current_only:
            sql += " AND NOT EXISTS (SELECT 1 FROM medical_entries newer WHERE newer.supersedes_id = e.id)"
        sql += " ORDER BY recorded_utc, id"
        with self.db.read() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    def profile_revisions(self, patient_id: str) -> list[dict[str, object]]:
        with self.db.read() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM patient_profile_revisions WHERE patient_id = ? ORDER BY recorded_utc, id",
                (patient_id,)).fetchall()]
