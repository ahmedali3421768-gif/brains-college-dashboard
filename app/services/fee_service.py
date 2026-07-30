"""Fee engine (single source of truth).

Whenever a payment is recorded or an installment changes, call
`recompute(db, application)`. It re-derives, automatically:

    payment_status      unpaid | partially_paid | fully_paid
    eligibility_status  eligible when paid >= 75% of total fee
    application_status  auto-approved once the advance (1st installment) is paid
    admission_status    admitted when fully paid

so every screen (challan, lists, dashboards, portal) always agrees.
"""
import logging

from sqlalchemy.orm import Session

from app.models import (
    AdmissionStatus, Application, ApplicationStatus, EligibilityStatus,
    Installment, InstallmentStatus, PaymentStatus,
)
from app.utils.timeutil import now

logger = logging.getLogger(__name__)

CLASS_ELIGIBILITY_THRESHOLD = 0.75  # the 75% fee rule


def paid_total(application: Application) -> float:
    return round(sum(i.paid_amount or 0 for i in application.installments), 2)


def ensure_not_overdue(application: Application, inst=None) -> None:
    """A payment cannot be taken once its due date has passed.

    If the student turns up after the deadline, the admin must first extend the
    due date on the payment schedule. That keeps the schedule honest: money is
    never recorded against a date that has already gone by, and every extension
    is a deliberate, logged decision rather than a silent one.

    ``inst`` — the specific stage being paid. When omitted (a general "record
    payment"), the stage the money would land on next is checked.
    """
    from fastapi import HTTPException

    today = now().date()

    if inst is None:
        pending = sorted(
            [i for i in application.installments
             if i.status != InstallmentStatus.PAID and (i.amount or 0) > 0],
            key=lambda i: (i.number, i.id))
        inst = next(iter(pending), None)
        if inst is None:
            return

    due = inst.due_date
    if due and due < today:
        from app.services.schedule_service import STAGE_LABEL, stage_of
        name = STAGE_LABEL.get(stage_of(inst), inst.label or "This installment")
        days = (today - due).days
        raise HTTPException(
            status_code=409,
            detail=(f"{name} was due on {due.strftime('%d-%m-%Y')} — "
                    f"{days} day{'s' if days != 1 else ''} ago. Payment cannot "
                    f"be recorded against a date that has passed. Extend the "
                    f"due date on the payment schedule first, then record the "
                    f"payment."))


def payment_state(inst) -> dict:
    """The true state of one scheduled payment, including lateness.

    A payment made after its due date is NOT simply "paid" — the deadline was
    missed, and the record has to say so. Four states:

        paid       — settled on or before the due date
        paid_late  — settled, but after the due date (keeps days_late)
        overdue    — still unpaid and the due date has passed
        pending    — still unpaid, due date is in the future (or none set)
    """
    today = now().date()
    due = inst.due_date
    is_paid = inst.status == InstallmentStatus.PAID

    if is_paid:
        paid_on = inst.paid_at.date() if inst.paid_at else None
        if due and paid_on and paid_on > due:
            return {"state": "paid_late", "label": "Paid Late",
                    "days_late": (paid_on - due).days,
                    "paid_on": str(paid_on)}
        return {"state": "paid", "label": "Paid", "days_late": 0,
                "paid_on": str(paid_on) if paid_on else ""}

    if due and due < today:
        return {"state": "overdue", "label": "Overdue",
                "days_late": (today - due).days, "paid_on": ""}
    return {"state": "pending", "label": "Pending", "days_late": 0,
            "paid_on": ""}


def summary(application: Application) -> dict:
    """All fee numbers for one application — used by API, challan, dashboards."""
    total = application.total_fee or 0
    paid = paid_total(application)
    remaining = max(0.0, round(total - paid, 2))
    today = now().date()

    installments = sorted(application.installments, key=lambda i: (i.number, i.id))
    completed = [i for i in installments if i.status == InstallmentStatus.PAID]
    pending = [i for i in installments if i.status != InstallmentStatus.PAID]
    overdue = [i for i in pending if i.due_date and i.due_date < today]
    current = next((i for i in pending), None)  # next unpaid = current installment
    # "always display the most recent due date"
    next_due = current.due_date if current and current.due_date else None

    paid_late = [i for i in completed
                 if payment_state(i)["state"] == "paid_late"]

    return {
        "total_fee": total,
        "paid": paid,
        "remaining": remaining,
        "installments_paid_late": len(paid_late),
        "percent_paid": round(paid / total * 100, 1) if total else 0.0,
        "payment_status": application.payment_status,
        "eligibility_status": application.eligibility_status,
        "installments_total": len(installments),
        "installments_completed": len(completed),
        "installments_pending": len(pending),
        "installments_overdue": len(overdue),
        "current_installment": _inst_dict(current, today) if current else None,
        "next_due_date": str(next_due) if next_due else None,
        "installments": [_inst_dict(i, today) for i in installments],
    }


def _inst_dict(i: Installment, today) -> dict:
    st = payment_state(i)
    return {
        "id": i.id, "number": i.number, "label": i.label, "amount": i.amount,
        "due_date": str(i.due_date) if i.due_date else None,
        "status": st["state"],          # paid | paid_late | overdue | pending
        "state_label": st["label"],
        "days_late": st["days_late"],
        "paid_on": st["paid_on"],
        "paid_amount": i.paid_amount, "paid_at": i.paid_at,
        "paid_method": i.paid_method, "recorded_by": i.recorded_by_name,
    }


def recompute(db: Session, application: Application) -> None:
    """Apply the admission rules. Call after ANY fee change; commits."""
    total = application.total_fee or 0
    paid = paid_total(application)

    # ── payment status (green / yellow / red) ───────────────────────────
    if paid <= 0:
        application.payment_status = PaymentStatus.UNPAID
    elif total and paid >= total:
        application.payment_status = PaymentStatus.FULLY_PAID
    else:
        application.payment_status = PaymentStatus.PARTIALLY_PAID

    # ── advance-payment rule ────────────────────────────────────────────
    # paying the 1st installment (advance) secures admission automatically
    first = min(application.installments, key=lambda i: (i.number, i.id),
                default=None)
    advance_paid = bool(first and first.status == InstallmentStatus.PAID)
    if advance_paid and application.application_status == ApplicationStatus.PENDING:
        application.application_status = ApplicationStatus.APPROVED

    # ── 75% rule → class eligibility ────────────────────────────────────
    if total and paid >= CLASS_ELIGIBILITY_THRESHOLD * total:
        application.eligibility_status = EligibilityStatus.ELIGIBLE
    else:
        application.eligibility_status = EligibilityStatus.NOT_ELIGIBLE

    # ── full payment ────────────────────────────────────────────────────
    if application.payment_status == PaymentStatus.FULLY_PAID:
        if application.admission_status == AdmissionStatus.NOT_ADMITTED:
            application.admission_status = AdmissionStatus.ADMITTED

    db.commit()


def create_advance_installment(db: Session, application: Application,
                               amount: float, due_date) -> Installment:
    """First installment (the advance) created with every new application."""
    inst = Installment(application_id=application.id, number=1,
                       label="Advance / Admission", amount=amount,
                       due_date=due_date)
    db.add(inst)
    if not application.total_fee:
        application.total_fee = amount
    db.commit()
    db.refresh(inst)
    return inst


def ensure_within_total(application: Application, incoming: float,
                        exclude_installment_id: int | None = None) -> None:
    """Total collected must never exceed the student's total course fee.

    Admission fee + every installment payment, added together, has to stay
    within total_fee. Raises 422 with a clear message otherwise.
    """
    from fastapi import HTTPException

    total = application.total_fee or 0
    if total <= 0:
        return                                  # no fee set yet — nothing to cap

    already = sum((i.paid_amount or 0) for i in application.installments
                  if exclude_installment_id is None
                  or i.id != exclude_installment_id)
    new_total = round(already + (incoming or 0), 2)
    if new_total > round(total, 2) + 0.01:
        allowed = max(0.0, round(total - already, 2))
        raise HTTPException(
            status_code=422,
            detail=(f"Total collected cannot exceed the total course fee. "
                    f"Total fee is Rs {total:,.0f} and Rs {already:,.0f} is "
                    f"already paid, so at most Rs {allowed:,.0f} can be "
                    f"recorded now."))


def record_allocation(db: Session, application, inst, amount: float,
                      method: str, receipt_number: str,
                      recorded_by: str, campus: str = "") -> None:
    """Log exactly which schedule stage this money landed on, and on what day.

    The Recoveries export reads these rows to show what was collected on a
    given date, stage by stage.
    """
    if not amount:
        return
    from app.models import PaymentAllocation
    from app.services.schedule_service import stage_of

    rc_campus = (campus or getattr(application, "campus", "") or "").strip()
    db.add(PaymentAllocation(
        application_id=application.id,
        installment_id=inst.id,
        stage=stage_of(inst),
        amount=round(amount, 2),
        receipt_number=receipt_number or "",
        method=method or "",
        campus=rc_campus,
        paid_on=now().date(),
        recorded_by_name=recorded_by or "",
    ))


def apply_payment(db: Session, application: Application, amount: float,
                  method: str, recorded_by: str,
                  receipt_number: str = "", campus: str = "") -> list[Installment]:
    """Record a received payment against the oldest unpaid installment(s)."""
    remaining = amount
    touched = []
    rc_campus = (campus or getattr(application, "campus", "") or "").strip()
    for inst in sorted(application.installments, key=lambda i: (i.number, i.id)):
        if remaining <= 0:
            break
        if inst.status == InstallmentStatus.PAID:
            continue
        due = max(0.0, (inst.amount or 0) - (inst.paid_amount or 0))
        chunk = min(remaining, due) if due else remaining
        inst.paid_amount = round((inst.paid_amount or 0) + chunk, 2)
        remaining = round(remaining - chunk, 2)
        if inst.paid_amount >= (inst.amount or 0):
            inst.status = InstallmentStatus.PAID
        inst.paid_at = now()
        inst.paid_method = method
        if receipt_number:
            inst.receipt_number = receipt_number
        inst.recorded_by_name = recorded_by
        record_allocation(db, application, inst, chunk, method,
                          receipt_number, recorded_by, campus=rc_campus)
        touched.append(inst)
    if remaining > 0 and touched:
        # overpayment — keep it on the last touched installment
        touched[-1].paid_amount = round(touched[-1].paid_amount + remaining, 2)
    db.commit()
    recompute(db, application)
    return touched
