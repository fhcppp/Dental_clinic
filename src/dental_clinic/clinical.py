"""Dentist-entered clinical events, treatment history and dental planning.

No automatic diagnoses, treatment recommendations or online dependencies.
Clinical records are append-only once finalized; amendments are new records.
"""
from __future__ import annotations

import sqlite3
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from .db import ClinicDatabase
from .errors import ConflictError, NotFoundError, ValidationError
from .fdi import validate_fdi
from .services import _audit, _dt_dump, _patient_exists, _utc_now

SURFACES = frozenset({"mesial", "distal", "occlusal", "incisal", "buccal", "lingual", "palatal"})
TOOTH_CONDITIONS = frozenset({"healthy", "caries", "missing", "restored", "fractured",
                              "impacted", "implant_supported", "other"})
PLAN_STATUSES = frozenset({"proposed", "accepted", "rejected", "scheduled",
                           "in_progress", "completed", "cancelled"})


def validated_surfaces(fdi_code: int, surfaces: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    validate_fdi(fdi_code)
    if not isinstance(surfaces, (tuple, list)) or len(surfaces) > 7:
        raise ValidationError("Surfaces must be a short sequence")
    if any(not isinstance(x, str) or x not in SURFACES for x in surfaces):
        raise ValidationError("Unrecognized dental surface")
    if len(surfaces) != len(set(surfaces)):
        raise ValidationError("Duplicate surfaces")
    anterior = fdi_code % 10 <= 3
    if anterior and "occlusal" in surfaces:
        raise ValidationError("Anterior teeth do not have an occlusal surface")
    if not anterior and "incisal" in surfaces:
        raise ValidationError("Posterior teeth do not have an incisal surface")
    if fdi_code // 10 in (3, 4, 7, 8) and "palatal" in surfaces:
        raise ValidationError("Mandibular teeth do not have a palatal surface")
    return tuple(surfaces)


def money_minor(amount: Decimal | str) -> int:
    """Convert exact base-10 amounts to two-decimal integer minor units."""
    if isinstance(amount, float) or isinstance(amount, bool):
        raise ValidationError("Floating-point currency values are not accepted")
    try:
        value = Decimal(amount)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Invalid monetary amount") from exc
    if not value.is_finite() or value < 0 or value * 100 != (value * 100).to_integral_value():
        raise ValidationError("Amount must be nonnegative with at most two decimals")
    minor = value * 100
    if minor > 9_000_000_000_000_000:
        raise ValidationError("Amount exceeds supported range")
    return int(minor)


def _dentist(conn: sqlite3.Connection, dentist_id: str) -> None:
    r = conn.execute("SELECT active FROM dentists WHERE id = ?", (dentist_id,)).fetchone()
    if not r or not r["active"]:
        raise ValidationError("Active dentist required")


def _visit(conn: sqlite3.Connection, visit_id: str, patient_id: str, dentist_id: str) -> None:
    r = conn.execute("SELECT dentist_id, status FROM clinical_visits WHERE id = ? AND patient_id = ?",
                     (visit_id, patient_id)).fetchone()
    if not r or r["dentist_id"] != dentist_id:
        raise ValidationError("Visit, patient and dentist must match")
    if r["status"] != "open":
        raise ConflictError("Visit is finalized")


class ClinicalService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def add_dentist(self, dentist_id: str, display_name: str, *, actor_id: str) -> None:
        if not dentist_id.strip() or not display_name.strip():
            raise ValidationError("Dentist name and identifier required")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO dentists(id, display_name) VALUES (?, ?)",
                         (dentist_id.strip(), display_name.strip()))
            _audit(conn, actor_id, "dentist.created", "dentist", dentist_id)

    def add_procedure(self, name: str, category: str, *, actor_id: str) -> str:
        if not isinstance(name, str) or not name.strip() or not category.strip():
            raise ValidationError("Name and category required")
        pid = str(uuid4())
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO procedure_catalog(id, name, category) VALUES (?,?,?)",
                         (pid, name.strip(), category.strip()))
            _audit(conn, actor_id, "catalog.created", "procedure", pid)
        return pid

    def open_visit(self, patient_id: str, dentist_id: str, *, actor_id: str,
                   appointment_id: str | None = None, chief_complaint: str | None = None,
                   diagnosis: str | None = None, notes: str | None = None) -> str:
        vid = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            _dentist(conn, dentist_id)
            if appointment_id:
                a = conn.execute("SELECT patient_id, practitioner_id FROM appointments WHERE id = ?",
                                 (appointment_id,)).fetchone()
                if not a or a["patient_id"] != patient_id or a["practitioner_id"] != dentist_id:
                    raise ValidationError("Appointment must match patient and dentist")
            conn.execute("""INSERT INTO clinical_visits
                (id, patient_id, dentist_id, appointment_id, visit_utc, chief_complaint,
                 clinical_notes, diagnosis, status) VALUES (?,?,?,?,?,?,?,?,'open')""",
                (vid, patient_id, dentist_id, appointment_id, _dt_dump(_utc_now()),
                 chief_complaint, notes, diagnosis))
            _audit(conn, actor_id, "visit.created", "clinical_visit", vid)
        return vid

    def add_observation(self, patient_id: str, dentist_id: str, fdi_code: int,
                        condition: str, surfaces: tuple[str, ...] = (), *, actor_id: str,
                        visit_id: str | None = None, note: str | None = None,
                        supersedes_id: str | None = None) -> str:
        tooth = validate_fdi(fdi_code)
        chosen = validated_surfaces(tooth, surfaces)
        if condition not in TOOTH_CONDITIONS:
            raise ValidationError("Unrecognized tooth condition")
        oid = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            _dentist(conn, dentist_id)
            if visit_id:
                _visit(conn, visit_id, patient_id, dentist_id)
            if supersedes_id:
                prev = conn.execute("SELECT patient_id, fdi_code FROM tooth_observations WHERE id = ?",
                                    (supersedes_id,)).fetchone()
                if not prev or prev["patient_id"] != patient_id or prev["fdi_code"] != tooth:
                    raise ValidationError("Observation amendment target mismatch")
            conn.execute("""INSERT INTO tooth_observations
                (id,patient_id,visit_id,dentist_id,fdi_code,condition,observed_utc,
                 clinical_note,supersedes_id) VALUES (?,?,?,?,?,?,?,?,?)""",
                (oid, patient_id, visit_id, dentist_id, tooth, condition,
                 _dt_dump(_utc_now()), note, supersedes_id))
            conn.executemany("INSERT INTO observation_surfaces VALUES (?,?)",
                             [(oid, surface) for surface in chosen])
            _audit(conn, actor_id, "tooth.observed", "tooth_observation", oid)
        return oid

    def create_plan(self, patient_id: str, dentist_id: str, title: str, *, actor_id: str) -> str:
        if not title.strip():
            raise ValidationError("Plan title required")
        plan_id = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            _dentist(conn, dentist_id)
            conn.execute("INSERT INTO treatment_plans VALUES (?,?,?,?,?)",
                         (plan_id, patient_id, dentist_id, _dt_dump(_utc_now()), title.strip()))
            _audit(conn, actor_id, "plan.created", "treatment_plan", plan_id)
        return plan_id

    def add_plan_item(self, plan_id: str, procedure_id: str, *, actor_id: str,
                      fdi_code: int | None = None, surfaces: tuple[str, ...] = (),
                      estimated: Decimal | str | None = None, explanation: str | None = None) -> str:
        if fdi_code is None and surfaces:
            raise ValidationError("Surfaces require a tooth")
        chosen = validated_surfaces(fdi_code, surfaces) if fdi_code is not None else ()
        amount = money_minor(estimated) if estimated is not None else None
        item_id = str(uuid4())
        with self.db.transaction() as conn:
            plan = conn.execute("SELECT patient_id,dentist_id FROM treatment_plans WHERE id = ?",
                                (plan_id,)).fetchone()
            if not plan:
                raise NotFoundError("Treatment plan not found")
            procedure = conn.execute("SELECT active FROM procedure_catalog WHERE id = ?",
                                     (procedure_id,)).fetchone()
            if not procedure or not procedure["active"]:
                raise ValidationError("Active procedure required")
            conn.execute("""INSERT INTO treatment_plan_items
                (id,patient_id,plan_id,procedure_id,dentist_id,fdi_code,estimated_minor,
                 explanation) VALUES (?,?,?,?,?,?,?,?)""",
                (item_id, plan["patient_id"], plan_id, procedure_id, plan["dentist_id"],
                 fdi_code, amount, explanation))
            conn.executemany("INSERT INTO plan_item_surfaces VALUES (?,?)",
                             [(item_id, surface) for surface in chosen])
            _audit(conn, actor_id, "plan.item_added", "treatment_plan_item", item_id)
        return item_id

    def record_treatment(self, patient_id: str, visit_id: str, dentist_id: str,
                         procedure_id: str, *, actor_id: str, fdi_code: int | None = None,
                         surfaces: tuple[str, ...] = (), notes: str | None = None,
                         materials: str | None = None, actual: Decimal | str | None = None,
                         plan_item_id: str | None = None, completed: bool = True,
                         amendment_of: str | None = None) -> str:
        if fdi_code is None and surfaces:
            raise ValidationError("Tooth surfaces cannot exist without tooth")
        chosen = validated_surfaces(fdi_code, surfaces) if fdi_code is not None else ()
        if completed and (not notes or not notes.strip()):
            raise ValidationError("Completed treatment must include a clinical note")
        minor = money_minor(actual) if actual is not None else None
        treatment_id = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            _dentist(conn, dentist_id)
            _visit(conn, visit_id, patient_id, dentist_id)
            proc = conn.execute("SELECT active FROM procedure_catalog WHERE id = ?",
                                (procedure_id,)).fetchone()
            if not proc or not proc["active"]:
                raise ValidationError("Active procedure required")
            if plan_item_id:
                item = conn.execute("""SELECT patient_id, procedure_id, fdi_code, status
                                      FROM treatment_plan_items WHERE id = ?""",
                                    (plan_item_id,)).fetchone()
                if (not item or item["patient_id"] != patient_id
                    or item["procedure_id"] != procedure_id or item["fdi_code"] != fdi_code
                    or item["status"] in ("rejected", "cancelled", "completed")):
                    raise ValidationError("Plan item does not match proposed treatment")
            if amendment_of:
                prev = conn.execute("SELECT patient_id, status FROM treatments WHERE id = ?",
                                    (amendment_of,)).fetchone()
                if not prev or prev["patient_id"] != patient_id or prev["status"] != "completed":
                    raise ValidationError("Amendment must reference completed treatment")
                if conn.execute("SELECT 1 FROM treatments WHERE amendment_of = ?",
                                (amendment_of,)).fetchone():
                    raise ConflictError("Treatment has already been amended")
            conn.execute("""INSERT INTO treatments
                (id, patient_id, visit_id, dentist_id, procedure_id, plan_item_id,
                 fdi_code, performed_utc, status, notes, materials, actual_minor, amendment_of)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (treatment_id, patient_id, visit_id, dentist_id, procedure_id, plan_item_id,
                 fdi_code, _dt_dump(_utc_now()), "draft",
                 notes, materials, minor, amendment_of))
            conn.executemany("INSERT INTO treatment_surfaces VALUES (?,?)",
                             [(treatment_id, surface) for surface in chosen])
            if completed:
                conn.execute("UPDATE treatments SET status = 'completed' WHERE id = ?",
                             (treatment_id,))
            if plan_item_id and completed:
                conn.execute("UPDATE treatment_plan_items SET status = 'completed' WHERE id = ?",
                             (plan_item_id,))
            _audit(conn, actor_id, "treatment.amended" if amendment_of else "treatment.recorded",
                   "treatment", treatment_id)
        return treatment_id

    def add_restoration(self, treatment_id: str, *, actor_id: str, material: str,
                        category: str | None = None, shade: str | None = None,
                        cavity_class: str | None = None, extent: str | None = None) -> None:
        with self.db.transaction() as conn:
            tx = conn.execute("SELECT status FROM treatments WHERE id = ?", (treatment_id,)).fetchone()
            if not tx or tx["status"] != "draft":
                raise ConflictError("Restoration details require a draft treatment")
            conn.execute("""INSERT INTO restoration_details
                (treatment_id,category,material,cavity_class,extent,shade) VALUES (?,?,?,?,?,?)""",
                (treatment_id, category, material, cavity_class, extent, shade))
            _audit(conn, actor_id, "restoration.recorded", "treatment", treatment_id)

    def add_endodontic_stage(self, treatment_id: str, stage: str, *, actor_id: str,
                             canals: dict[str, Decimal | str | None] | None = None,
                             notes: str | None = None) -> str:
        if not stage.strip():
            raise ValidationError("Endodontic stage required")
        stage_id = str(uuid4())
        with self.db.transaction() as conn:
            treatment = conn.execute("SELECT status FROM treatments WHERE id = ?",
                                     (treatment_id,)).fetchone()
            if not treatment or treatment["status"] != "draft":
                raise ConflictError("Endodontic stage requires a draft treatment")
            conn.execute("""INSERT INTO endodontic_stages
                (id,treatment_id,stage,notes,recorded_utc) VALUES (?,?,?,?,?)""",
                (stage_id, treatment_id, stage.strip(), notes, _dt_dump(_utc_now())))
            for canal, length in (canals or {}).items():
                if not canal.strip():
                    raise ValidationError("Canal identification required")
                if length is None:
                    value = None
                else:
                    try:
                        decimal = Decimal(str(length))
                    except InvalidOperation as exc:
                        raise ValidationError("Invalid working length") from exc
                    if not decimal.is_finite() or not Decimal("0") < decimal <= Decimal("80"):
                        raise ValidationError("Working length outside allowed range")
                    value = str(decimal)
                conn.execute("INSERT INTO endodontic_canals VALUES (?,?,?,?)",
                             (str(uuid4()), stage_id, canal.strip(), value))
            _audit(conn, actor_id, "endodontic.stage_recorded", "treatment", treatment_id)
        return stage_id

    def finalize_draft(self, treatment_id: str, *, actor_id: str) -> None:
        with self.db.transaction() as conn:
            tx = conn.execute("SELECT status,notes,plan_item_id FROM treatments WHERE id = ?",
                              (treatment_id,)).fetchone()
            if not tx or tx["status"] != "draft":
                raise ConflictError("Only draft treatments can be finalized")
            if not tx["notes"] or not tx["notes"].strip():
                raise ValidationError("Completion note required")
            conn.execute("UPDATE treatments SET status = 'completed' WHERE id = ?", (treatment_id,))
            if tx["plan_item_id"]:
                conn.execute("UPDATE treatment_plan_items SET status = 'completed' WHERE id = ?",
                             (tx["plan_item_id"],))
            _audit(conn, actor_id, "treatment.finalized", "treatment", treatment_id)

    def finalize_visit(self, visit_id: str, *, actor_id: str) -> None:
        with self.db.transaction() as conn:
            if conn.execute("SELECT 1 FROM treatments WHERE visit_id = ? AND status = 'draft'",
                            (visit_id,)).fetchone():
                raise ConflictError("Finalize or remove draft treatments before finalizing visit")
            if conn.execute("UPDATE clinical_visits SET status = 'finalized' WHERE id = ? AND status = 'open'",
                            (visit_id,)).rowcount != 1:
                raise ConflictError("Visit is missing or already finalized")
            _audit(conn, actor_id, "visit.finalized", "clinical_visit", visit_id)

    def treatment_history(self, patient_id: str, tooth: int | None = None) -> list[dict]:
        if tooth is not None:
            validate_fdi(tooth)
        with self.db.read() as conn:
            sql = "SELECT * FROM treatments WHERE patient_id = ?"
            params: list[object] = [patient_id]
            if tooth is not None:
                sql += " AND fdi_code = ?"
                params.append(tooth)
            sql += " ORDER BY performed_utc, id"
            output = []
            for row in conn.execute(sql, params).fetchall():
                obj = dict(row)
                obj["surfaces"] = [r["surface"] for r in conn.execute(
                    "SELECT surface FROM treatment_surfaces WHERE treatment_id = ? ORDER BY surface",
                    (row["id"],)).fetchall()]
                output.append(obj)
            return output

    def tooth_observation_history(self, patient_id: str, tooth: int) -> list[dict]:
        validate_fdi(tooth)
        with self.db.read() as conn:
            rows = conn.execute("""SELECT * FROM tooth_observations WHERE patient_id = ?
                                   AND fdi_code = ? ORDER BY observed_utc,id""",
                                (patient_id, tooth)).fetchall()
            return [dict(r) for r in rows]
