"""Export-ready, local-only administrative summaries. No UI calculations required."""
from __future__ import annotations

import csv
import io
from datetime import date

from .db import ClinicDatabase
from .errors import ValidationError


def _range(start: date, end: date) -> tuple[str, str]:
    if type(start) is not date or type(end) is not date or end < start:
        raise ValidationError("Report requires a valid inclusive date interval")
    return start.isoformat(), end.isoformat()


class ReportingService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def registrations(self, start: date, end: date) -> list[dict]:
        a, b = _range(start, end)
        with self.db.read() as c:
            return [dict(r) for r in c.execute("""SELECT substr(created_utc,1,10) day,
                COUNT(*) registrations FROM patients WHERE substr(created_utc,1,10) BETWEEN ? AND ?
                GROUP BY day ORDER BY day""", (a, b)).fetchall()]

    def appointment_summary(self, start: date, end: date) -> list[dict]:
        a, b = _range(start, end)
        with self.db.read() as c:
            return [dict(r) for r in c.execute("""SELECT practitioner_id, status,
                COUNT(*) appointments FROM appointments WHERE substr(start_utc,1,10)
                BETWEEN ? AND ? GROUP BY practitioner_id,status ORDER BY practitioner_id,status""",
                (a, b)).fetchall()]

    def procedure_statistics(self, start: date, end: date) -> list[dict]:
        a, b = _range(start, end)
        with self.db.read() as c:
            return [dict(r) for r in c.execute("""SELECT p.category, p.name, t.dentist_id,
                COUNT(*) total, COALESCE(SUM(t.actual_minor),0) actual_minor
                FROM treatments t JOIN procedure_catalog p ON p.id=t.procedure_id
                WHERE t.status='completed' AND substr(t.performed_utc,1,10) BETWEEN ? AND ?
                GROUP BY p.category,p.name,t.dentist_id
                ORDER BY p.category,p.name,t.dentist_id""", (a, b)).fetchall()]

    def revenue(self, start: date, end: date) -> list[dict]:
        a, b = _range(start, end)
        with self.db.read() as c:
            return [dict(r) for r in c.execute("""SELECT i.currency,
                SUM(CASE WHEN p.kind='payment' THEN p.amount_minor ELSE -p.amount_minor END)
                collected_minor FROM payments p JOIN invoices i ON i.id=p.invoice_id
                WHERE substr(p.recorded_utc,1,10) BETWEEN ? AND ? GROUP BY i.currency
                ORDER BY i.currency""", (a, b)).fetchall()]

    def outstanding_invoices(self) -> list[dict]:
        with self.db.read() as c:
            return [dict(r) for r in c.execute("""SELECT i.id,i.patient_id,i.currency,
                 COALESCE((SELECT SUM(quantity * unit_minor) FROM invoice_items
                           WHERE invoice_id=i.id),0) -
                 COALESCE((SELECT SUM(CASE WHEN kind='payment' THEN amount_minor
                           ELSE -amount_minor END) FROM payments WHERE invoice_id=i.id),0)
                 outstanding_minor FROM invoices i WHERE i.status='finalized'
                 ORDER BY i.issued_utc, i.id""").fetchall()]

    @staticmethod
    def csv_text(rows: list[dict]) -> str:
        if not rows:
            return ""
        headers = list(rows[0])
        sink = io.StringIO()
        writer = csv.DictWriter(sink, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Escape spreadsheet formula injection in CSV opened with Excel/LibreOffice.
            safe = {k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(
                ("=", "+", "-", "@")) else v) for k, v in row.items()}
            writer.writerow(safe)
        return sink.getvalue()
