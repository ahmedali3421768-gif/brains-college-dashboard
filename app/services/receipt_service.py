"""Central receipt-number logic.

Every payment (advance, installment, full payment, verified challan) carries a
unique receipt number. This module is the single place that checks uniqueness,
so the same rule is enforced from every entry point:

  • installment "pay"            (fees.py)
  • record any received amount   (fees.py)
  • challan / receipt approval   (payments.py)

Receipt numbers live in two tables — ``installments.receipt_number`` and
``payments.receipt_number`` — so uniqueness is checked across BOTH. A DB-level
unique index on each column is the final backstop against races (two admins
approving at the same instant); this service gives the friendly, instant error
before we ever hit that.
"""
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Installment, Payment


def normalize(receipt_number: str) -> str:
    return (receipt_number or "").strip()


def is_taken(db: Session, receipt_number: str,
             exclude_installment_id: int | None = None,
             exclude_payment_id: int | None = None) -> bool:
    """True if this receipt number already exists on any payment record.
    Case-insensitive so "rc-1" and "RC-1" can't both be used."""
    rn = normalize(receipt_number)
    if not rn:
        return False
    low = rn.lower()

    iq = db.query(Installment.id).filter(
        func.lower(Installment.receipt_number) == low)
    if exclude_installment_id is not None:
        iq = iq.filter(Installment.id != exclude_installment_id)
    if db.query(iq.exists()).scalar():
        return True

    pq = db.query(Payment.id).filter(
        func.lower(Payment.receipt_number) == low)
    if exclude_payment_id is not None:
        pq = pq.filter(Payment.id != exclude_payment_id)
    if db.query(pq.exists()).scalar():
        return True

    return False


def ensure_unique(db: Session, receipt_number: str,
                  exclude_installment_id: int | None = None,
                  exclude_payment_id: int | None = None) -> str:
    """Return the cleaned receipt number, or raise a 409 with a clear message
    if it's already used. Call this right before saving any payment."""
    rn = normalize(receipt_number)
    if not rn:
        raise HTTPException(
            status_code=422,
            detail="Receipt Number is required before approval.")
    if is_taken(db, rn, exclude_installment_id, exclude_payment_id):
        raise HTTPException(
            status_code=409,
            detail=f'Receipt Number "{rn}" already exists. '
                   f"Please enter a unique receipt number.")
    return rn


def owner_application_id(db: Session, receipt_number: str) -> int | None:
    """Which application already owns this receipt number? None if unused."""
    rn = normalize(receipt_number)
    if not rn:
        return None
    low = rn.lower()
    p = (db.query(Payment)
         .filter(func.lower(Payment.receipt_number) == low).first())
    if p:
        return p.application_id
    i = (db.query(Installment)
         .filter(func.lower(Installment.receipt_number) == low).first())
    if i:
        return i.application_id
    return None


def resolve_for_challan(db: Session, receipt_number: str,
                        application_id: int) -> tuple[str, bool]:
    """Decide what a receipt number means when approving a challan.

    Admins normally record the payment on the admissions page first (which
    issues the receipt number), then approve the matching challan using that
    SAME receipt number. That must be allowed — it links the challan to the
    payment that already exists. It must NOT record the payment a second time,
    or the fee would be counted twice.

    Returns (clean_receipt_number, already_recorded)
        already_recorded = True  → just mark the challan paid and link it
        already_recorded = False → this is a brand-new receipt, record the payment

    Raises 409 only when the receipt number belongs to a DIFFERENT student.
    """
    rn = normalize(receipt_number)
    if not rn:
        raise HTTPException(
            status_code=422,
            detail="Receipt Number is required before approval.")

    owner = owner_application_id(db, rn)
    if owner is None:
        return rn, False                      # new receipt → record payment
    if owner == application_id:
        return rn, True                       # same student → link only
    raise HTTPException(
        status_code=409,
        detail=f'Receipt Number "{rn}" already belongs to another student. '
               f"Please enter the correct receipt number.")


def latest_for_application(db: Session, application_id: int) -> str:
    """The most recent receipt number issued to a student (across installments
    and payments), newest first. Empty string if none."""
    latest = ""
    latest_when = None

    p = (db.query(Payment)
         .filter(Payment.application_id == application_id,
                 Payment.receipt_number != "")
         .order_by(Payment.created_at.desc())
         .first())
    if p and p.receipt_number:
        latest, latest_when = p.receipt_number, p.created_at

    for i in db.query(Installment).filter(
            Installment.application_id == application_id,
            Installment.receipt_number != "").all():
        when = i.paid_at or i.updated_at or i.created_at
        if latest_when is None or (when and when > latest_when):
            latest, latest_when = i.receipt_number, when

    return latest
