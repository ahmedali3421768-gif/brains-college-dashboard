"""Business logic for inter-campus money transfers.

The rules, in one place so both the API and any report read the same truth:

  · A transfer moves money the SOURCE campus has already collected for a student
    to the DESTINATION campus. It never invents money — the amount can't exceed
    what the student has actually paid, minus anything already transferred out.
  · Nothing changes until the destination campus approves, and approval requires
    the destination to re-key the student's roll number (a deliberate double
    check against transferring the wrong student).
  · An approved transfer is booked as a ledger movement: it lowers the source
    campus's net collection for the day and raises the destination's. The
    student's own fee records are left exactly as they were — the money simply
    now belongs to a different campus's books.
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (Application, MoneyTransfer, Payment, Student)
from app.services import fee_service


def _gen_transfer_no(db: Session) -> str:
    year = datetime.now().year
    n = db.query(func.count(MoneyTransfer.id)).scalar() or 0
    return f"MT-{year}-{n + 1:05d}"


def transferable_balance(db: Session, application: Application) -> float:
    """How much of this student's paid fee is still available to transfer out.

    = total the student has paid  −  already approved transfers out for them.
    """
    fee = fee_service.summary(application)
    paid = fee["paid"] or 0
    moved = (db.query(func.coalesce(func.sum(MoneyTransfer.amount), 0.0))
             .filter(MoneyTransfer.application_id == application.id,
                     MoneyTransfer.status == "approved").scalar() or 0.0)
    return round(max(0.0, paid - moved), 2)


def lookup(db: Session, source_campus: str, roll: str) -> dict:
    """Student summary for the source form. The student must exist and belong
    to the source campus."""
    roll = (roll or "").strip()
    if not roll:
        raise HTTPException(status_code=422, detail="Roll number is required.")
    s = (db.query(Student).filter(func.lower(Student.roll_number) ==
                                  roll.lower()).first())
    if not s:
        raise HTTPException(status_code=404,
                            detail=f"No student found with roll number {roll}.")
    a = (db.query(Application).filter(Application.student_id == s.id)
         .order_by(Application.id.desc()).first())
    if not a:
        raise HTTPException(status_code=404,
                            detail="That student has no application on record.")
    if (a.campus or "") != source_campus:
        raise HTTPException(
            status_code=422,
            detail=f"{s.roll_number} belongs to {a.campus or 'another campus'}, "
                   f"not {source_campus}. You can only transfer money for your "
                   f"own campus's students.")
    fee = fee_service.summary(a)
    return {
        "application_id": a.id, "student_id": s.id,
        "roll_number": s.roll_number, "student_name": s.full_name,
        "father_name": s.father_name, "course": a.course_name,
        "campus": a.campus, "total_fee": fee["total_fee"],
        "total_paid": fee["paid"], "remaining_fee": fee["remaining"],
        "transferable": transferable_balance(db, a),
    }


def create_request(db: Session, admin, dest_campus: str, roll: str,
                   amount: float, remarks: str) -> MoneyTransfer:
    from app.config import VALID_CAMPUSES

    source_campus = admin.campus or ""
    if not source_campus:
        raise HTTPException(
            status_code=403,
            detail="Super admins pick a campus context to raise a transfer; "
                   "this action is for a campus user.")
    if dest_campus not in VALID_CAMPUSES:
        raise HTTPException(status_code=422, detail="Unknown destination campus.")
    if dest_campus == source_campus:
        raise HTTPException(status_code=422,
                            detail="Source and destination campus cannot be the same.")

    info = lookup(db, source_campus, roll)
    a = db.get(Application, info["application_id"])

    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Amount must be a number.")
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be greater than 0.")

    avail = transferable_balance(db, a)
    if amount > avail + 0.01:
        raise HTTPException(
            status_code=422,
            detail=f"Amount Rs {amount:,.0f} is more than the transferable "
                   f"balance of Rs {avail:,.0f} (the student's paid fee, less "
                   f"any amount already transferred out).")

    # no duplicate pending request for the same student + amount
    dup = (db.query(MoneyTransfer)
           .filter(MoneyTransfer.application_id == a.id,
                   MoneyTransfer.status == "pending",
                   MoneyTransfer.amount == amount).first())
    if dup:
        raise HTTPException(
            status_code=409,
            detail=f"An identical pending transfer ({dup.transfer_no}) already "
                   f"exists for this student and amount.")

    mt = MoneyTransfer(
        transfer_no=_gen_transfer_no(db),
        source_campus=source_campus, dest_campus=dest_campus,
        application_id=a.id, student_id=info["student_id"],
        student_name=info["student_name"], father_name=info["father_name"],
        course=info["course"], source_roll=info["roll_number"],
        amount=amount, remarks=(remarks or "").strip()[:300],
        status="pending",
        requested_by_id=admin.id, requested_by_name=admin.name)
    db.add(mt)
    db.commit()
    db.refresh(mt)
    return mt


def approve(db: Session, admin, mt: MoneyTransfer, dest_roll: str) -> MoneyTransfer:
    """Approve after verifying the destination-entered roll matches the source
    roll. The whole thing is one commit — if anything is wrong we raise before
    writing, so the books never end up half-updated."""
    if mt.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"This transfer is already {mt.status}.")

    # verification: destination must re-key the student's roll number
    if (dest_roll or "").strip().lower() != (mt.source_roll or "").lower():
        raise HTTPException(
            status_code=422,
            detail="Roll number does not match. Transfer cannot be completed.")

    # guard against negatives even now (balance could have moved meanwhile)
    a = db.get(Application, mt.application_id)
    if a is not None:
        avail = transferable_balance(db, a)
        if mt.amount > avail + 0.01:
            raise HTTPException(
                status_code=422,
                detail=f"Transferable balance has changed. Only Rs {avail:,.0f} "
                       f"is available now; this request is for Rs {mt.amount:,.0f}.")

    mt.status = "approved"
    mt.dest_roll = mt.source_roll
    mt.decided_by_id = admin.id
    mt.decided_by_name = admin.name
    mt.approved_at = datetime.now()
    db.commit()
    db.refresh(mt)
    return mt


def reject(db: Session, admin, mt: MoneyTransfer, reason: str) -> MoneyTransfer:
    if mt.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"This transfer is already {mt.status}.")
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(status_code=422,
                            detail="A rejection reason is required.")
    mt.status = "rejected"
    mt.reject_reason = reason[:300]
    mt.decided_by_id = admin.id
    mt.decided_by_name = admin.name
    mt.rejected_at = datetime.now()
    db.commit()
    db.refresh(mt)
    return mt


def to_dict(mt: MoneyTransfer, viewer_campus: str = "") -> dict:
    direction = ""
    if viewer_campus:
        if viewer_campus == mt.dest_campus:
            direction = "incoming"
        elif viewer_campus == mt.source_campus:
            direction = "outgoing"
    return {
        "id": mt.id, "transfer_no": mt.transfer_no,
        "source_campus": mt.source_campus, "dest_campus": mt.dest_campus,
        "application_id": mt.application_id,
        "student_name": mt.student_name, "father_name": mt.father_name,
        "course": mt.course, "source_roll": mt.source_roll,
        "dest_roll": mt.dest_roll, "amount": mt.amount,
        "remarks": mt.remarks, "reject_reason": mt.reject_reason,
        "status": mt.status,
        "requested_by": mt.requested_by_name,
        "requested_at": str(mt.requested_at) if mt.requested_at else "",
        "decided_by": mt.decided_by_name,
        "approved_at": str(mt.approved_at) if mt.approved_at else "",
        "rejected_at": str(mt.rejected_at) if mt.rejected_at else "",
        "direction": direction,
        "can_decide": (not viewer_campus or viewer_campus == mt.dest_campus)
                      and mt.status == "pending",
    }


def net_ledger_adjustment(db: Session, campus: str,
                          on: date | None = None) -> float:
    """The net effect of approved transfers on a campus's collection figure.

    Money transferred IN adds; money transferred OUT subtracts. The dashboard
    budget adds this to the campus's own collections so the day's numbers move
    correctly between campuses.
    """
    q = db.query(MoneyTransfer).filter(MoneyTransfer.status == "approved")
    if on is not None:
        q = q.filter(func.date(MoneyTransfer.approved_at) == on.isoformat())
    incoming = sum(m.amount for m in q if m.dest_campus == campus)
    outgoing = sum(m.amount for m in q if m.source_campus == campus)
    return round(incoming - outgoing, 2)
