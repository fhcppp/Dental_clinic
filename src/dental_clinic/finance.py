"""Transactional offline invoice and payment ledger (integer minor currency units)."""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from .clinical import money_minor
from .db import ClinicDatabase
from .errors import ConflictError, NotFoundError, ValidationError
from .services import _audit, _dt_dump, _patient_exists, _utc_now


class FinanceService:
    def __init__(self, db: ClinicDatabase):
        self.db = db

    def create_invoice(self, patient_id: str, *, actor_id: str, currency: str = "EUR") -> str:
        if (not isinstance(currency, str) or len(currency) != 3
            or not currency.isascii() or not currency.isalpha()):
            raise ValidationError("Currency must be an ISO-style three-letter code")
        invoice_id = str(uuid4())
        with self.db.transaction() as conn:
            _patient_exists(conn, patient_id)
            conn.execute("INSERT INTO invoices VALUES (?,?,?,?, 'draft')",
                         (invoice_id, patient_id, currency.upper(), _dt_dump(_utc_now())))
            _audit(conn, actor_id, "invoice.created", "invoice", invoice_id)
        return invoice_id

    def add_item(self, invoice_id: str, description: str, amount: Decimal | str, *,
                 actor_id: str, quantity: int = 1, treatment_id: str | None = None) -> str:
        if type(quantity) is not int or quantity <= 0 or quantity > 1_000_000:
            raise ValidationError("Quantity must be a positive integer")
        if not isinstance(description, str) or not description.strip():
            raise ValidationError("Item description is required")
        unit_minor = money_minor(amount)
        item_id = str(uuid4())
        with self.db.transaction() as conn:
            inv = conn.execute("SELECT patient_id,status FROM invoices WHERE id = ?",
                               (invoice_id,)).fetchone()
            if not inv:
                raise NotFoundError("Invoice not found")
            if inv["status"] != "draft":
                raise ConflictError("Finalized invoices are immutable")
            if treatment_id:
                tx = conn.execute("SELECT patient_id,status FROM treatments WHERE id = ?",
                                  (treatment_id,)).fetchone()
                if not tx or tx["patient_id"] != inv["patient_id"] or tx["status"] != "completed":
                    raise ValidationError("Invoice treatment must be completed for same patient")
            conn.execute("INSERT INTO invoice_items VALUES (?,?,?,?,?,?)",
                         (item_id, invoice_id, description.strip(), quantity, unit_minor, treatment_id))
            _audit(conn, actor_id, "invoice.item_added", "invoice", invoice_id)
        return item_id

    def finalize(self, invoice_id: str, *, actor_id: str) -> None:
        with self.db.transaction() as conn:
            row = conn.execute("SELECT status FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
            if not row or row["status"] != "draft":
                raise ConflictError("Only draft invoices can be finalized")
            if not conn.execute("SELECT 1 FROM invoice_items WHERE invoice_id = ?",
                                (invoice_id,)).fetchone():
                raise ValidationError("Cannot finalize an empty invoice")
            conn.execute("UPDATE invoices SET status = 'finalized' WHERE id = ?", (invoice_id,))
            _audit(conn, actor_id, "invoice.finalized", "invoice", invoice_id)

    def balance(self, invoice_id: str) -> dict[str, int | str]:
        with self.db.read() as conn:
            invoice = conn.execute("SELECT currency,status FROM invoices WHERE id = ?",
                                   (invoice_id,)).fetchone()
            if not invoice:
                raise NotFoundError("Invoice not found")
            total = conn.execute("""SELECT COALESCE(SUM(quantity * unit_minor),0)
                                    FROM invoice_items WHERE invoice_id = ?""",
                                 (invoice_id,)).fetchone()[0]
            paid = conn.execute("""SELECT COALESCE(SUM(CASE WHEN kind = 'payment'
                                  THEN amount_minor ELSE -amount_minor END),0)
                                  FROM payments WHERE invoice_id = ?""",
                                (invoice_id,)).fetchone()[0]
        return {"currency": invoice["currency"], "status": invoice["status"],
                "total_minor": total, "paid_minor": paid, "outstanding_minor": total-paid}

    def record_payment(self, invoice_id: str, amount: Decimal | str, *,
                       actor_id: str, method: str = "other") -> str:
        cents = money_minor(amount)
        if cents <= 0:
            raise ValidationError("Payment must be positive")
        payment_id = str(uuid4())
        with self.db.transaction() as conn:
            invoice = conn.execute("SELECT status FROM invoices WHERE id = ?",
                                   (invoice_id,)).fetchone()
            if not invoice or invoice["status"] != "finalized":
                raise ConflictError("Payments require a finalized invoice")
            total = conn.execute("SELECT COALESCE(SUM(quantity * unit_minor),0) FROM invoice_items WHERE invoice_id = ?",
                                 (invoice_id,)).fetchone()[0]
            paid = conn.execute("""SELECT COALESCE(SUM(CASE WHEN kind='payment' THEN amount_minor
                                 ELSE -amount_minor END),0) FROM payments WHERE invoice_id=?""",
                                (invoice_id,)).fetchone()[0]
            if cents > total - paid:
                raise ConflictError("Payment exceeds the outstanding invoice balance")
            conn.execute("""INSERT INTO payments
                           (id, invoice_id, amount_minor, recorded_utc, method, kind)
                           VALUES (?,?,?,?,?,'payment')""",
                         (payment_id, invoice_id, cents, _dt_dump(_utc_now()), method))
            _audit(conn, actor_id, "payment.recorded", "payment", payment_id)
        return payment_id

    def refund(self, original_payment_id: str, amount: Decimal | str, *, actor_id: str) -> str:
        cents = money_minor(amount)
        if cents <= 0:
            raise ValidationError("Refund must be positive")
        refund_id = str(uuid4())
        with self.db.transaction() as conn:
            original = conn.execute("""SELECT invoice_id,amount_minor,kind
                                      FROM payments WHERE id = ?""",
                                    (original_payment_id,)).fetchone()
            if not original or original["kind"] != "payment":
                raise ValidationError("Refund must reference a payment")
            prior_refunds = conn.execute("""SELECT COALESCE(SUM(amount_minor),0)
                FROM payments WHERE original_payment_id = ? AND kind = 'refund'""",
                (original_payment_id,)).fetchone()[0]
            if cents > original["amount_minor"] - prior_refunds:
                raise ConflictError("Refund exceeds remaining refundable amount")
            conn.execute("""INSERT INTO payments
                (id,invoice_id,amount_minor,recorded_utc,method,kind,original_payment_id)
                VALUES (?,?,?,?, 'refund','refund',?)""",
                (refund_id, original["invoice_id"], cents, _dt_dump(_utc_now()), original_payment_id))
            _audit(conn, actor_id, "payment.refunded", "payment", refund_id)
        return refund_id

    def history(self, invoice_id: str) -> list[dict]:
        with self.db.read() as conn:
            rows = conn.execute("SELECT * FROM payments WHERE invoice_id = ? ORDER BY recorded_utc,id",
                                (invoice_id,)).fetchall()
            return [dict(r) for r in rows]
