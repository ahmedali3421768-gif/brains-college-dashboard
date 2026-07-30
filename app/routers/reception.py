"""Receptionist fee-lookup API (read-only).

A deliberately tiny, locked-down surface: receptionists can ONLY search
students and read fee status for their own campus. There are no write
endpoints here, and every response is limited to the whitelisted fields
(name, roll number, campus, course, total/paid/pending fee, due date and
status). No CNIC, phone, address, documents, history, etc. is ever exposed.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import admin_campus, receptionist_only
from app.database import get_db
from app.models import Admin, Application, Student
from app.services import fee_service
from app.utils.pagination import paginate

router = APIRouter(prefix="/api/reception", tags=["reception"])

# Payment status → simple three-state label used by the reception UI.
_STATUS = {
    "fully_paid": "Paid",
    "partially_paid": "Half Paid",
    "unpaid": "Pending",
}


def _fee_row(app_obj: Application) -> dict:
    """Whitelist-only projection of an application for the reception view."""
    s = app_obj.student
    fee = fee_service.summary(app_obj)
    course = (getattr(app_obj, "course_name", "") or "").strip()
    if not course and app_obj.course:
        course = app_obj.course.name
    raw_status = fee.get("payment_status") or "unpaid"
    return {
        "id": app_obj.id,
        "student_name": s.full_name if s else "",
        "roll_number": s.roll_number if s else "",
        "campus": app_obj.campus or "",
        "course": course or "—",
        "batch": getattr(app_obj, "session", "") or "",
        "total_fee": fee.get("total_fee", 0) or 0,
        "paid_fee": fee.get("paid", 0) or 0,
        "pending_fee": fee.get("remaining", 0) or 0,
        "due_date": fee.get("next_due_date") or "",
        "fee_status": _STATUS.get(raw_status, "Pending"),
        "fee_status_key": raw_status,
        "latest_receipt": _latest_receipt_from_loaded(app_obj),
    }


def _latest_receipt_from_loaded(app_obj) -> str:
    """Newest receipt number issued to this student (installments + payments)."""
    best, best_when = "", None
    for i in getattr(app_obj, "installments", []) or []:
        rn = getattr(i, "receipt_number", "") or ""
        if rn:
            when = getattr(i, "paid_at", None) or getattr(i, "created_at", None)
            if best_when is None or (when and when > best_when):
                best, best_when = rn, when
    for p in getattr(app_obj, "payments", []) or []:
        rn = getattr(p, "receipt_number", "") or ""
        if rn:
            when = getattr(p, "created_at", None)
            if best_when is None or (when and when > best_when):
                best, best_when = rn, when
    return best


@router.get("/me")
def reception_me(admin: Admin = Depends(receptionist_only)):
    """Minimal identity for the reception header."""
    return {
        "name": admin.name,
        "campus": admin.campus or "",
        "role": admin.role,
    }


@router.get("/courses")
def reception_courses(admin: Admin = Depends(receptionist_only),
                      db: Session = Depends(get_db)):
    """Distinct course names available for the receptionist's campus filter."""
    campus = admin_campus(admin)
    q = db.query(Application.course_name).filter(Application.course_name != "")
    if campus:
        q = q.filter(Application.campus == campus)
    courses = sorted({c[0] for c in q.distinct().all() if c[0]})
    # batches (sessions) too, for the batch filter
    bq = db.query(Application.session).filter(Application.session != "")
    if campus:
        bq = bq.filter(Application.campus == campus)
    batches = sorted({b[0] for b in bq.distinct().all() if b[0]})
    return {"courses": courses, "batches": batches}


@router.get("/students")
def reception_students(
    q: str | None = None,
    course: str | None = None,
    batch: str | None = None,
    fee_status: str | None = Query(None, description="paid|partially_paid|unpaid"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: Admin = Depends(receptionist_only),
    db: Session = Depends(get_db),
):
    """Search students by name or roll number and read their fee status.
    Always hard-scoped to the receptionist's own campus."""
    campus = admin_campus(admin)   # None only for a super admin viewing
    query = (db.query(Application)
             .join(Student)
             .options(joinedload(Application.student),
                      joinedload(Application.course),
                      joinedload(Application.installments),
                      joinedload(Application.payments))
             .order_by(desc(Application.submitted_at)))

    if campus:
        query = query.filter(Application.campus == campus)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Student.full_name.ilike(like),
                                 Student.roll_number.ilike(like)))
    if course:
        query = query.filter(Application.course_name == course)
    if batch:
        query = query.filter(Application.session == batch)
    if fee_status:
        query = query.filter(Application.payment_status == fee_status)

    result = paginate(query, page, page_size)
    result["items"] = [_fee_row(a) for a in result["items"]]
    result["campus"] = campus or "All campuses"
    return result


@router.get("/students/{app_id}")
def reception_student_detail(app_id: int,
                             admin: Admin = Depends(receptionist_only),
                             db: Session = Depends(get_db)):
    """Fee detail for the student popup — whitelist fields only, campus-locked."""
    app_obj = db.get(Application, app_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="Student not found")
    campus = admin_campus(admin)
    if campus and (app_obj.campus or "") != campus:
        # Never reveal that a record exists on another campus.
        raise HTTPException(status_code=404, detail="Student not found")
    return _fee_row(app_obj)
