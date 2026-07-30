"""The four-stage payment schedule every student has.

    Admission Fee · 1st Installment · 2nd Installment · Test Session

Each stage carries an editable amount and an editable due date. The four rows
always exist, so the Installments tab is a proper schedule rather than an
ad-hoc list. The combined amount can never exceed the finalised course fee.
"""
from __future__ import annotations

from datetime import date as _date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Application, Installment, InstallmentStatus

# Canonical order — never changes.
STAGES = [
    ("admission_fee", "Admission Fee"),
    ("first_installment", "1st Installment"),
    ("second_installment", "2nd Installment"),
    ("test_session", "Test Session"),
]
STAGE_KEYS = [k for k, _ in STAGES]
STAGE_LABEL = dict(STAGES)


def stage_of(inst: Installment) -> str:
    """The stage an installment belongs to, inferring it for legacy rows."""
    if getattr(inst, "stage", ""):
        return inst.stage
    label = (inst.label or "").lower()
    if "advance" in label or "admission" in label:
        return "admission_fee"
    if "test" in label:
        return "test_session"
    if "2" in label or "second" in label:
        return "second_installment"
    if "1" in label or "first" in label:
        return "first_installment"
    return ""


def ensure_schedule(db: Session, app: Application) -> list[Installment]:
    """Make sure all four stage rows exist. Existing rows are adopted into the
    schedule (never duplicated, never deleted), so old data keeps working."""
    by_stage: dict[str, Installment] = {}

    # Adopt whatever is already there.
    for inst in sorted(app.installments, key=lambda i: (i.number, i.id)):
        s = stage_of(inst)
        if s and s not in by_stage:
            if not getattr(inst, "stage", ""):
                inst.stage = s
            by_stage[s] = inst

    # Any un-staged leftovers fill the first free slot, so nothing is lost.
    leftovers = [i for i in app.installments
                 if i not in by_stage.values()]
    for inst in leftovers:
        free = next((k for k in STAGE_KEYS if k not in by_stage), None)
        if free is None:
            break
        inst.stage = free
        by_stage[free] = inst

    created = False
    for idx, (key, label) in enumerate(STAGES, start=1):
        inst = by_stage.get(key)
        if inst is None:
            inst = Installment(application_id=app.id, number=idx, label=label,
                               stage=key, amount=0, due_date=None,
                               status=InstallmentStatus.PENDING)
            db.add(inst)
            by_stage[key] = inst
            created = True
        else:
            inst.number = idx
            inst.label = label

    if created or True:
        db.commit()
        db.refresh(app)
    return schedule_rows(app)


def schedule_rows(app: Application) -> list[Installment]:
    """The four rows, in canonical order."""
    by_stage = {stage_of(i): i for i in app.installments if stage_of(i)}
    return [by_stage[k] for k in STAGE_KEYS if k in by_stage]


def to_dict(inst: Installment) -> dict:
    from app.services.fee_service import payment_state

    key = stage_of(inst)
    st = payment_state(inst)
    return {
        "id": inst.id,
        "stage": key,
        "schedule": STAGE_LABEL.get(key, inst.label or ""),
        "amount": inst.amount or 0,
        "due_date": str(inst.due_date) if inst.due_date else "",
        "paid_amount": inst.paid_amount or 0,
        "status": inst.status,                 # raw: pending | paid
        "state": st["state"],                  # paid | paid_late | overdue | pending
        "state_label": st["label"],
        "days_late": st["days_late"],
        "paid_on": st["paid_on"],
        "receipt_number": inst.receipt_number or "",
        "paid_at": inst.paid_at,
    }


def get_schedule(db: Session, app: Application) -> dict:
    rows = ensure_schedule(db, app)
    total = app.total_fee or 0
    scheduled = round(sum(r.amount or 0 for r in rows), 2)
    return {
        "total_fee": total,
        "scheduled_total": scheduled,
        "unscheduled": round(total - scheduled, 2),
        "paid_total": round(sum(r.paid_amount or 0 for r in rows), 2),
        "rows": [to_dict(r) for r in rows],
    }


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, _date):
        return v
    try:
        return _date.fromisoformat(str(v)[:10])
    except ValueError:
        raise HTTPException(status_code=422,
                            detail=f"Invalid date: {v}. Use YYYY-MM-DD.")


def save_schedule(db: Session, app: Application, rows: list[dict],
                  by_name: str = "") -> tuple[dict, list[dict]]:
    """Update amounts and due dates for the four stages.

    Returns (schedule, due_date_changes) — the caller sends a notification for
    each due-date change.
    """
    ensure_schedule(db, app)
    current = {stage_of(i): i for i in app.installments if stage_of(i)}

    incoming: dict[str, dict] = {}
    for r in rows or []:
        key = (r.get("stage") or "").strip()
        if key not in STAGE_KEYS:
            raise HTTPException(status_code=422,
                                detail=f"Unknown payment stage: {key or '—'}")
        incoming[key] = r

    # ── Validation: the schedule can never exceed the finalised course fee ──
    total = app.total_fee or 0
    new_amounts = {}
    for key in STAGE_KEYS:
        inst = current.get(key)
        if key in incoming and incoming[key].get("amount") is not None:
            try:
                amt = float(incoming[key]["amount"] or 0)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422,
                    detail=f"{STAGE_LABEL[key]}: amount must be a number.")
            if amt < 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"{STAGE_LABEL[key]}: amount cannot be negative.")
        else:
            amt = (inst.amount or 0) if inst else 0
        new_amounts[key] = round(amt, 2)

    scheduled = round(sum(new_amounts.values()), 2)
    if total > 0 and scheduled > total + 0.01:
        raise HTTPException(
            status_code=422,
            detail=(f"The payment schedule totals Rs {scheduled:,.0f}, which is "
                    f"more than the total course fee of Rs {total:,.0f}. "
                    f"Reduce the amounts so they add up to Rs {total:,.0f} or less."))

    # An amount can't be lowered below what has already been collected for it.
    for key in STAGE_KEYS:
        inst = current.get(key)
        paid = (inst.paid_amount or 0) if inst else 0
        if paid and new_amounts[key] < paid - 0.01:
            raise HTTPException(
                status_code=422,
                detail=(f"{STAGE_LABEL[key]}: Rs {paid:,.0f} has already been "
                        f"collected, so the amount cannot be set below that."))

    # ── Apply ──
    changes: list[dict] = []
    for key in STAGE_KEYS:
        inst = current[key]
        inst.amount = new_amounts[key]

        if key in incoming and "due_date" in incoming[key]:
            new_due = _parse_date(incoming[key].get("due_date"))
            old_due = inst.due_date
            if (old_due or None) != (new_due or None):
                changes.append({
                    "stage": key,
                    "schedule": STAGE_LABEL[key],
                    "old": str(old_due) if old_due else "—",
                    "new": str(new_due) if new_due else "—",
                })
                inst.due_date = new_due

        # keep status honest after an amount change
        if inst.amount and (inst.paid_amount or 0) >= inst.amount:
            inst.status = InstallmentStatus.PAID
        elif inst.status == InstallmentStatus.PAID and \
                (inst.paid_amount or 0) < (inst.amount or 0):
            inst.status = InstallmentStatus.PENDING
        if by_name:
            inst.recorded_by_name = by_name

    db.commit()
    db.refresh(app)

    from app.services import fee_service
    fee_service.recompute(db, app)

    return get_schedule(db, app), changes
