"""Admission applications — public submission + admin management (Parts 2–4, 9)."""
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import any_staff, managers, scope_query, admin_campus
from app.database import get_db
from app.models import (
    ActivityLog, Admin, AdmissionStatus, Application, ApplicationNote,
    ApplicationStatus, ChatSession, Payment, PaymentStatus, Student,
)
from app.schemas.application import (
    ApplicationSubmit, ApplicationUpdate, NoteCreate, StatusUpdate,
)
from app.schemas.serialize import application_to_dict, note_to_dict, session_to_dict
from app.services import challan_service, chat_logger, fee_service
from app.services.export_service import application_pdf
from app.services.notification_service import notify
from app.services.ws_manager import manager
from app.utils.pagination import paginate
from app.utils.rate_limit import rate_limit
from app.utils.timeutil import now

logger = logging.getLogger(__name__)
router = APIRouter(tags=["applications"])


def _parse_dob(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="date_of_birth must be YYYY-MM-DD")


# ── PUBLIC: website admission form ───────────────────────────────────────
@router.post("/api/applications", status_code=201,
             dependencies=[Depends(rate_limit("apply", limit=5, window_seconds=60))])
async def submit_application(payload: ApplicationSubmit,
                             db: Session = Depends(get_db)):
    return await _create_application(db, payload)


async def _create_application(db: Session, payload: ApplicationSubmit,
                              created_by: str = "",
                              enforce_roll: bool = False):
    from app.catalog import is_valid_course

    roll = payload.roll_number.strip()
    # ── Campus roll-number rules (admin portal admissions) ──────────────
    # Fixed prefix per campus + strict sequence, no gaps.
    if enforce_roll:
        from app.services import roll_service
        roll = roll_service.validate(db, roll, payload.campus)

    # ── Roll Number uniqueness (primary identifier) ─────────────────────
    existing = db.query(Student).filter(Student.roll_number == roll).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"An application with Roll Number {roll} already exists.")

    if not is_valid_course(payload.programme_category, payload.course_name):
        raise HTTPException(
            status_code=422,
            detail=f"'{payload.course_name}' is not a valid course under "
                   f"{payload.programme_category}.")

    dob = _parse_dob(payload.date_of_birth)
    student = Student(
        roll_number=roll,
        full_name=payload.full_name.strip(),
        father_name=payload.father_name.strip(),
        cnic=payload.cnic, phone=payload.phone, email=payload.email,
        guardian_phone=(payload.guardian_phone or "").strip(),
        gender=payload.gender, date_of_birth=dob,
        address=payload.address, city=payload.city,
    )
    db.add(student)
    db.flush()

    admission_dt = _parse_dob(payload.admission_date) or now().date()
    extra = {**payload.extra_fields}
    if payload.semester:
        extra["semester"] = payload.semester
    if payload.class_timing:
        extra["class_timing"] = payload.class_timing
    if payload.duration:
        extra["duration"] = payload.duration
    if payload.marks is not None:
        extra["marks"] = payload.marks
    if admission_dt:
        extra["admission_date"] = str(admission_dt)

    application = Application(
        student_id=student.id,
        department_id=payload.department_id,
        course_id=payload.course_id,
        programme_category=payload.programme_category,
        course_name=payload.course_name.strip(),
        session=payload.session,
        lead_source=payload.lead_source,
        lead_source_detail=(payload.lead_source_detail or "").strip(),
        campus=payload.campus,
        previous_qualification=payload.previous_qualification,
        percentage=payload.percentage,
        class_time=(payload.class_time or "").strip(),
        lab_time=(payload.lab_time or "").strip(),
        instructor_name=(payload.instructor_name or "").strip(),
        course_duration_months=payload.course_duration_months or 3,
        documents=json.dumps(payload.documents),
        extra_fields=json.dumps(extra),
    )
    db.add(application)
    db.flush()
    application.application_no = f"APP-{now().year}-{application.id:05d}"
    db.commit()
    db.refresh(application)

    # Part 9 — adopt chat sessions with the same phone number
    chat_logger.link_sessions_to_student(db, student)

    # Module 3 — auto-convert matching leads (same phone or email)
    from app.models import Lead, LeadStatus
    matches = [Lead.phone == student.phone]
    if student.email:
        matches.append(Lead.email == student.email)
    db.query(Lead).filter(
        or_(*matches),
        Lead.status.notin_([LeadStatus.CONVERTED])
    ).update({Lead.status: LeadStatus.CONVERTED,
              Lead.student_id: student.id}, synchronize_session=False)
    db.commit()

    # Module 1 — set fee, create the advance installment (PKR 1,000), challan
    challan = challan_service.create_challan(db, application)
    application.total_fee = challan.amount
    application.fee_category = "Admission Fee"
    fee_service.create_advance_installment(
        db, application, challan.amount, challan.due_date)
    db.refresh(application)
    db.add(ActivityLog(action="challan_created",
                       detail=f"{challan.challan_no} created for "
                              f"{roll} (Rs {challan.amount:,.0f})"))
    db.commit()

    await notify(db, "new_application", "New application received",
                 f"{student.full_name} (Roll {roll}) applied for "
                 f"{application.course_name}.",
                 related_id=application.id, campus=application.campus or "")
    await manager.broadcast("new_application",
                            application_to_dict(application))
    logger.info("Application saved: %s (Roll %s)",
                application.application_no, roll)
    return {"success": True,
            "id": application.id,
            "roll_number": roll,
            "student_name": student.full_name,
            "course_name": application.course_name,
            "application_no": application.application_no,
            "challan": {
                "challan_no": challan.challan_no,
                "amount": challan.amount,
                "due_date": str(challan.due_date) if challan.due_date else None,
                "print_url": f"/challan/{challan.challan_no}"
                             f"?token={challan.access_token}",
                "access_token": challan.access_token,
            },
            "portal_url": "/portal",
            "message": f"Your application for {student.full_name} in "
                       f"{application.course_name} has been generated "
                       f"successfully."}


# ── ADMIN: create an application from the panel ──────────────────────────
@router.post("/api/admin/applications", status_code=201)
async def admin_create_application(payload: ApplicationSubmit,
                                   admin: Admin = Depends(managers),
                                   db: Session = Depends(get_db)):
    # A campus admin's applications are always stamped with their own campus.
    campus = admin_campus(admin)
    if campus:
        payload.campus = campus
    result = await _create_application(db, payload, created_by=admin.name,
                                       enforce_roll=True)
    db.add(ActivityLog(admin_id=admin.id, action="application_created",
                       detail=f"Created application for Roll "
                              f"{result['roll_number']} by {admin.name}"))
    db.commit()
    return result


# ── ADMIN: list with search / filters / sorting / pagination ────────────
SORTABLE = {
    "submitted_at": Application.submitted_at,
    "updated_at": Application.updated_at,
    "percentage": Application.percentage,
    "application_status": Application.application_status,
    "full_name": Student.full_name,
    "city": Student.city,
}


@router.get("/api/admin/applications")
def list_applications(
    q: str | None = None,
    status: str | None = None,
    payment_status: str | None = None,
    admission_status: str | None = None,
    programme_category: str | None = None,
    session: str | None = None,
    lead_source: str | None = None,
    department_id: int | None = None,
    course_id: int | None = None,
    campus: str | None = None,
    city: str | None = None,
    transfer_filter: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str = "submitted_at",
    sort_dir: str = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: Admin = Depends(any_staff),
    db: Session = Depends(get_db),
):
    query = (db.query(Application).join(Student)
             # Referral applications live in the Referral Portal only — they must
             # never show up in a campus's normal Applications list.
             .filter(Application.is_referral.is_(False))
             .options(joinedload(Application.student),
                      joinedload(Application.course),
                      joinedload(Application.department)))
    query = scope_query(query, Application, admin)  # campus scoping
    if q:
        # Search by Roll Number, Previous Roll, Name, Phone, or App No
        roll = q.strip()
        query = query.filter(or_(
            Student.roll_number.ilike(f"%{roll}%"),
            Application.previous_roll_number.ilike(f"%{roll}%"),
            Student.full_name.ilike(f"%{roll}%"),
            Student.phone.ilike(f"%{roll}%"),
            Application.application_no.ilike(f"%{roll}%")
        ))
    if status:
        query = query.filter(Application.application_status == status)
    if payment_status:
        query = query.filter(Application.payment_status == payment_status)
    if admission_status:
        query = query.filter(Application.admission_status == admission_status)
    if programme_category:
        query = query.filter(
            Application.programme_category == programme_category)
    if session:
        query = query.filter(Application.session == session)
    if lead_source:
        query = query.filter(Application.lead_source == lead_source)
    if department_id:
        query = query.filter(Application.department_id == department_id)
    if course_id:
        query = query.filter(Application.course_id == course_id)
    if campus:
        query = query.filter(Application.campus == campus)
    if city:
        query = query.filter(Student.city.ilike(f"%{city}%"))
    campus_scope = admin_campus(admin)
    if transfer_filter and campus_scope:
        if transfer_filter == "active":
            query = query.filter(Application.campus == campus_scope)
        elif transfer_filter == "transferred_out":
            query = query.filter(Application.transferred_from == campus_scope, Application.campus != campus_scope)
        elif transfer_filter == "transferred_in":
            query = query.filter(Application.campus == campus_scope, Application.transferred_from.isnot(None), Application.transferred_from != "")
    if date_from:
        query = query.filter(Application.submitted_at
                             >= datetime.strptime(date_from, "%Y-%m-%d"))
    if date_to:
        query = query.filter(Application.submitted_at
                             < datetime.strptime(date_to, "%Y-%m-%d")
                             .replace(hour=23, minute=59, second=59))

    sort_col = SORTABLE.get(sort_by, Application.submitted_at)
    query = query.order_by(desc(sort_col) if sort_dir == "desc" else sort_col)

    result = paginate(query, page, page_size)
    result["items"] = [application_to_dict(a) for a in result["items"]]
    return result


def _get_or_404(db: Session, app_id: int, admin: Admin = None) -> Application:
    app_obj = db.get(Application, app_id)
    if not app_obj:
        raise HTTPException(status_code=404, detail="Application not found")
    # campus scoping: a campus admin can see current campus OR transferred-from campus
    if admin is not None:
        campus = admin_campus(admin)
        if campus and (app_obj.campus or "") != campus and (getattr(app_obj, "transferred_from", "") or "") != campus:
            raise HTTPException(status_code=404, detail="Application not found")
    return app_obj


@router.get("/api/admin/applications/{app_id}")
def get_application(app_id: int, admin: Admin = Depends(any_staff),
                    db: Session = Depends(get_db)):
    return application_to_dict(_get_or_404(db, app_id, admin), include_detail=True)


@router.patch("/api/admin/applications/{app_id}/status")
async def update_status(app_id: int, payload: StatusUpdate,
                        admin: Admin = Depends(managers),
                        db: Session = Depends(get_db)):
    app_obj = _get_or_404(db, app_id, admin)
    changes = []
    if payload.application_status:
        app_obj.application_status = payload.application_status
        changes.append(f"status → {payload.application_status}")
    if payload.admission_status:
        app_obj.admission_status = payload.admission_status
        changes.append(f"admission → {payload.admission_status}")
    if payload.referral_status:
        app_obj.referral_status = payload.referral_status
        changes.append(f"referral_status → {payload.referral_status}")
    if payload.referral_remarks is not None:
        app_obj.referral_remarks = payload.referral_remarks

    # Keep referral_status, referral_enrolled, and application_status synchronized
    if app_obj.is_referral or payload.referral_status:
        target_st = (payload.referral_status or payload.application_status or app_obj.application_status or "").lower()
        if target_st in ("approved", "accepted", "enrolled"):
            app_obj.referral_status = "accepted"
            app_obj.referral_enrolled = True
            if not app_obj.referral_enrolled_at:
                app_obj.referral_enrolled_at = now()
            app_obj.application_status = ApplicationStatus.APPROVED
            app_obj.admission_status = AdmissionStatus.ADMITTED
        elif target_st in ("rejected", "cancelled"):
            app_obj.referral_status = "rejected"
            app_obj.referral_enrolled = False
            app_obj.application_status = ApplicationStatus.REJECTED
        elif target_st in ("pending", "under_review", "contacted", "on_hold"):
            app_obj.referral_status = "pending"
            app_obj.referral_enrolled = False
            if target_st == "on_hold":
                app_obj.application_status = ApplicationStatus.ON_HOLD
            else:
                app_obj.application_status = ApplicationStatus.PENDING

    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to update")

    app_obj.updated_at = now()
    db.add(ActivityLog(admin_id=admin.id, action="status_change",
                       detail=f"{app_obj.application_no}: {', '.join(changes)}"))
    db.commit()
    db.refresh(app_obj)

    if payload.application_status == ApplicationStatus.APPROVED or (app_obj.is_referral and app_obj.referral_status == "accepted"):
        await notify(db, "admission_approved", "Application approved",
                     f"{app_obj.student.full_name}'s application "
                     f"{app_obj.application_no} was approved by {admin.name}.",
                     related_id=app_obj.id, campus=app_obj.campus or "")

    await manager.broadcast("application_updated", application_to_dict(app_obj))
    return application_to_dict(app_obj, include_detail=True)


@router.patch("/api/admin/applications/{app_id}")
async def update_application(app_id: int, payload: ApplicationUpdate,
                             admin: Admin = Depends(managers),
                             db: Session = Depends(get_db)):
    app_obj = _get_or_404(db, app_id, admin)
    student = app_obj.student
    _old_roll = student.roll_number if student else ""

    if payload.roll_number is not None:
        roll = payload.roll_number.strip()
        clash = (db.query(Student)
                 .filter(Student.roll_number == roll, Student.id != student.id)
                 .first())
        if clash:
            raise HTTPException(
                status_code=409,
                detail=f"An application with Roll Number {roll} already exists.")
        student.roll_number = roll

    for field in ("full_name", "father_name", "cnic", "phone", "guardian_phone", "email",
                  "gender", "address", "city"):
        value = getattr(payload, field)
        if value is not None:
            setattr(student, field, value.strip() if isinstance(value, str) else value)
    if payload.date_of_birth is not None:
        student.date_of_birth = _parse_dob(payload.date_of_birth)

    for field in ("course_id", "department_id", "campus",
                  "previous_qualification", "percentage",
                  "programme_category", "course_name", "session",
                  "lead_source", "lead_source_detail", "remarks",
                  "class_time", "lab_time", "instructor_name",
                  "course_duration_months"):
        value = getattr(payload, field)
        if value is not None:
            setattr(app_obj, field,
                    value.strip() if isinstance(value, str) else value)
    if payload.class_timing is not None:
        try:
            extra = json.loads(app_obj.extra_fields or "{}")
        except json.JSONDecodeError:
            extra = {}
        extra["class_timing"] = payload.class_timing
        app_obj.extra_fields = json.dumps(extra)
    if payload.assigned_staff_id is not None:
        if payload.assigned_staff_id == 0:
            app_obj.assigned_staff_id = None
            app_obj.assigned_staff_name = ""
        else:
            staff = db.get(Admin, payload.assigned_staff_id)
            if not staff:
                raise HTTPException(status_code=404, detail="Staff not found")
            app_obj.assigned_staff_id = staff.id
            app_obj.assigned_staff_name = staff.name

    db.add(ActivityLog(admin_id=admin.id, action="application_edited",
                       detail=f"Edited {student.roll_number or app_obj.application_no}"))
    db.commit()
    db.refresh(app_obj)

    who = f"{student.full_name} ({student.roll_number})" if student else "Student"
    if _old_roll and student and student.roll_number != _old_roll:
        await notify(db, "system", "Roll number changed",
                     f"{admin.name} changed the roll number of "
                     f"{student.full_name} from {_old_roll} to "
                     f"{student.roll_number} at {app_obj.campus or '—'}.",
                     related_id=app_obj.id, priority="high",
                     category="admission", campus=app_obj.campus or "")
    else:
        await notify(db, "system", "Admission updated",
                     f"{who} was updated by {admin.name} at "
                     f"{app_obj.campus or '—'}.",
                     related_id=app_obj.id, priority="normal",
                     category="admission", campus=app_obj.campus or "")
    return application_to_dict(app_obj, include_detail=True)


@router.delete("/api/admin/applications/{app_id}")
def delete_application(app_id: int, admin: Admin = Depends(managers),
                       db: Session = Depends(get_db)):
    """Permanently remove a mistakenly created application and its fee records.
    The student's chat history is preserved (unlinked, not deleted)."""
    app_obj = _get_or_404(db, app_id, admin)
    student = app_obj.student
    roll = student.roll_number if student else app_obj.application_no

    from app.models import (ApplicationNote, Challan, Installment, Payment,
                            PaymentReceipt)
    # remove receipts, then challans, then installments, notes, payments
    challan_ids = [c.id for c in db.query(Challan)
                   .filter(Challan.application_id == app_obj.id).all()]
    if challan_ids:
        db.query(PaymentReceipt).filter(
            PaymentReceipt.challan_id.in_(challan_ids)).delete(
            synchronize_session=False)
        db.query(Challan).filter(
            Challan.application_id == app_obj.id).delete(
            synchronize_session=False)
    db.query(Installment).filter(
        Installment.application_id == app_obj.id).delete(
        synchronize_session=False)
    db.query(ApplicationNote).filter(
        ApplicationNote.application_id == app_obj.id).delete(
        synchronize_session=False)
    db.query(Payment).filter(
        Payment.application_id == app_obj.id).delete(
        synchronize_session=False)
    db.delete(app_obj)
    db.commit()

    # remove the student row only if they have no other applications
    if student and not db.query(Application).filter(
            Application.student_id == student.id).count():
        db.delete(student)
        db.commit()

    db.add(ActivityLog(admin_id=admin.id, action="application_deleted",
                       detail=f"Deleted application Roll {roll} by {admin.name}"))
    db.commit()
    return {"success": True, "message": f"Application {roll} deleted."}


@router.post("/api/admin/applications/{app_id}/notes", status_code=201)
def add_note(app_id: int, payload: NoteCreate,
             admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    app_obj = _get_or_404(db, app_id, admin)
    note = ApplicationNote(application_id=app_obj.id, admin_id=admin.id,
                           admin_name=admin.name, note=payload.note.strip())
    db.add(note)
    db.commit()
    db.refresh(note)
    return note_to_dict(note)


@router.get("/api/admin/applications/{app_id}/pdf")
def download_pdf(app_id: int, admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    app_obj = _get_or_404(db, app_id, admin)
    data = application_to_dict(app_obj, include_detail=True)
    pdf_bytes = application_pdf(data, data["notes"])
    filename = f"{app_obj.application_no or app_obj.id}.pdf"
    return Response(pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


# ── Part 9: student information + chat history on one screen ────────────
@router.get("/api/admin/applications/{app_id}/chats")
def application_chats(app_id: int, admin: Admin = Depends(any_staff),
                      db: Session = Depends(get_db)):
    app_obj = _get_or_404(db, app_id, admin)
    student = app_obj.student
    linked = (db.query(ChatSession)
              .filter(ChatSession.student_id == student.id)
              .order_by(desc(ChatSession.last_activity_at)).all())
    possible = []
    if student.phone:
        possible = (db.query(ChatSession)
                    .filter(ChatSession.student_id.is_(None),
                            ChatSession.visitor_phone == student.phone).all())
    return {"linked": [session_to_dict(s) for s in linked],
            "possible_matches": [session_to_dict(s) for s in possible]}


@router.post("/api/admin/chats/{session_id}/link/{student_id}")
def link_chat(session_id: str, student_id: int,
              admin: Admin = Depends(managers), db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    student = db.get(Student, student_id)
    if not session or not student:
        raise HTTPException(status_code=404, detail="Session or student not found")
    session.student_id = student.id
    db.commit()
    return {"success": True, "message": f"Chat linked to {student.full_name}"}


# ── Attendance Card ──────────────────────────────────────────────────────
@router.get("/api/admin/applications/{app_id}/attendance-card",
            response_class=HTMLResponse)
def attendance_card(app_id: int, admin: Admin = Depends(any_staff),
                    db: Session = Depends(get_db)):
    """Printable Attendance Card (Admin / Super Admin; receptionists preview
    only via the reception portal). Records print tracking."""
    from app.services import attendance_card_service
    a = _get_or_404(db, app_id, admin)
    if a.card_generated_at is None:
        a.card_generated_at = now()
    a.card_print_count = (a.card_print_count or 0) + 1
    a.card_last_printed_at = now()
    a.card_printed_by = admin.name
    db.commit()
    return HTMLResponse(attendance_card_service.render(a))


@router.get("/api/admin/applications/{app_id}/attendance-card/info")
def attendance_card_info(app_id: int, admin: Admin = Depends(any_staff),
                         db: Session = Depends(get_db)):
    """Metadata for the Attendance Card preview panel."""
    from app.services import attendance_card_service
    a = _get_or_404(db, app_id, admin)
    return {
        "months": attendance_card_service.course_months(
            a.submitted_at, getattr(a, "course_duration_months", 3)),
        "class_time": getattr(a, "class_time", "") or "",
        "lab_time": getattr(a, "lab_time", "") or "",
        "instructor_name": getattr(a, "instructor_name", "") or "",
        "course_duration_months": getattr(a, "course_duration_months", 3),
        "card_generated_at": a.card_generated_at,
        "card_last_printed_at": a.card_last_printed_at,
        "card_printed_by": a.card_printed_by or "",
        "card_print_count": a.card_print_count or 0,
    }


# ── Campus roll-number settings & next-roll suggestion ───────────────────
@router.get("/api/admin/roll-settings")
def roll_settings(admin: Admin = Depends(any_staff),
                  db: Session = Depends(get_db)):
    """Starting roll number per campus. A campus admin sees only their campus;
    the super admin sees all four."""
    from app.config import VALID_CAMPUSES
    from app.services import roll_service
    scope = admin_campus(admin)
    campuses = [scope] if scope else list(VALID_CAMPUSES)
    return {"items": [{
        "campus": c,
        "prefix": roll_service.prefix_for(c),
        "start_number": roll_service.start_number(db, c),
        "highest_assigned": roll_service.highest_number(db, c),
        "next_roll": roll_service.next_roll(db, c),
    } for c in campuses]}


@router.patch("/api/admin/roll-settings")
async def update_roll_settings(payload: dict,
                               admin: Admin = Depends(managers),
                               db: Session = Depends(get_db)):
    """Set the starting roll number for a campus (Admissions Settings)."""
    from app.config import VALID_CAMPUSES
    from app.services import roll_service
    campus = (payload.get("campus") or "").strip()
    scope = admin_campus(admin)
    if scope:
        campus = scope                       # campus admins can only set theirs
    if campus not in VALID_CAMPUSES:
        raise HTTPException(status_code=422, detail="Unknown campus.")
    try:
        number = int(payload.get("start_number"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422,
                            detail="Starting roll number must be a number.")

    highest = roll_service.highest_number(db, campus)
    if highest is not None and number <= highest:
        raise HTTPException(
            status_code=422,
            detail=f"{campus} already has roll numbers up to "
                   f"{roll_service.format_roll(roll_service.prefix_for(campus), highest)}. "
                   f"The starting number must be higher than {highest}.")

    row = roll_service.set_start_number(db, campus, number, admin.name)
    await notify(db, "system", "Starting roll number updated",
                 f"{admin.name} set the starting roll number for {campus} to "
                 f"{roll_service.format_roll(roll_service.prefix_for(campus), number)}.",
                 priority="normal", category="admission", campus=campus)
    db.add(ActivityLog(admin_id=admin.id, action="roll_settings",
                       detail=f"{campus} starting roll number → {number}"))
    db.commit()
    return {"campus": row.campus, "start_number": row.start_number,
            "next_roll": roll_service.next_roll(db, campus)}


@router.get("/api/admin/next-roll")
def next_roll_number(campus: str | None = None,
                     admin: Admin = Depends(any_staff),
                     db: Session = Depends(get_db)):
    """The roll number the next admission must use (auto-suggested in the form)."""
    from app.services import roll_service
    scope = admin_campus(admin)
    target = scope or (campus or "").strip()
    if not target:
        return {"campus": "", "next_roll": "", "prefix": ""}
    return {
        "campus": target,
        "prefix": roll_service.prefix_for(target),
        "next_roll": roll_service.next_roll(db, target),
        "highest_assigned": roll_service.highest_number(db, target),
    }


# ── Student Transfer (campus → campus) ───────────────────────────────────
@router.get("/api/admin/transfer/preview")
def transfer_preview(app_id: int, to_campus: str,
                     admin: Admin = Depends(managers),
                     db: Session = Depends(get_db)):
    """What roll number would this student get at the destination campus?"""
    from app.config import VALID_CAMPUSES
    from app.services import roll_service
    a = _get_or_404(db, app_id, admin)
    if to_campus not in VALID_CAMPUSES:
        raise HTTPException(status_code=422, detail="Unknown destination campus.")
    if (a.campus or "") == to_campus:
        raise HTTPException(status_code=422,
                            detail="The student is already at that campus.")
    s = a.student
    return {
        "application_id": a.id,
        "student_name": s.full_name if s else "",
        "current_campus": a.campus or "",
        "current_roll": s.roll_number if s else "",
        "to_campus": to_campus,
        "new_roll": roll_service.next_transfer_roll(db, to_campus),
    }


@router.post("/api/admin/transfer")
async def transfer_student(payload: dict,
                           admin: Admin = Depends(managers),
                           db: Session = Depends(get_db)):
    """Request a student transfer to another campus.

    This does NOT move the student. It creates a Pending transfer request that
    the destination campus must approve. The student stays fully active in the
    source campus, keeps their roll number, and no data moves until approval.
    """
    from app.config import VALID_CAMPUSES
    from app.models import TransferRequest
    from app.services import roll_service

    app_id = payload.get("application_id")
    to_campus = (payload.get("to_campus") or "").strip()
    reason = (payload.get("reason") or "").strip()[:500]

    a = _get_or_404(db, int(app_id or 0), admin)
    if to_campus not in VALID_CAMPUSES:
        raise HTTPException(status_code=422, detail="Unknown destination campus.")
    from_campus = a.campus or ""
    if from_campus == to_campus:
        raise HTTPException(status_code=422,
                            detail="The student is already at that campus.")

    # block a second pending request for the same student
    existing = (db.query(TransferRequest)
                .filter(TransferRequest.application_id == a.id,
                        TransferRequest.status == "pending").first())
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A transfer request for this student is already pending "
                   f"approval by {existing.to_campus}.")

    s = a.student
    who = s.full_name if s else "Student"
    cur_roll = s.roll_number if s else ""
    course = getattr(a, "course_name", "") or (a.course.name if a.course else "")

    req = TransferRequest(
        application_id=a.id, from_campus=from_campus, to_campus=to_campus,
        status="pending", reason=reason, student_name=who,
        current_roll=cur_roll, course=course,
        requested_by_id=admin.id, requested_by_name=admin.name)
    db.add(req)
    db.commit()
    db.refresh(req)

    db.add(ActivityLog(admin_id=admin.id, action="transfer_requested",
                       detail=f"{cur_roll} {from_campus} → {to_campus} (pending)"))
    db.commit()

    # notify BOTH campuses
    await notify(db, "system", "Transfer requested",
                 f"{from_campus} requested the transfer of {who} ({cur_roll}) "
                 f"to {to_campus}. Awaiting {to_campus}'s approval. "
                 f"Requested by {admin.name}." + (f" Reason: {reason}" if reason else ""),
                 related_id=a.id, priority="normal", category="admission",
                 campus=from_campus)
    await notify(db, "system", "New transfer request received",
                 f"{to_campus} received a transfer request from {from_campus} "
                 f"for {who} ({cur_roll}, {course}). Review it in "
                 f"Admissions → Transfer Students.",
                 related_id=a.id, priority="high", category="admission",
                 campus=to_campus)

    return {"request_id": req.id, "status": "pending",
            "application_id": a.id, "student_name": who,
            "from_campus": from_campus, "current_roll": cur_roll,
            "to_campus": to_campus,
            "message": f"Transfer request sent to {to_campus} for approval."}


@router.get("/api/admin/transfer-requests")
def transfer_requests(status: str | None = None,
                      admin: Admin = Depends(any_staff),
                      db: Session = Depends(get_db)):
    """Transfer requests visible to this admin.

    A campus admin sees requests they raised (outgoing) AND requests addressed
    to their campus (incoming). Super admin sees everything.
    """
    from app.models import TransferRequest

    q = db.query(TransferRequest).order_by(desc(TransferRequest.created_at))
    scope = admin_campus(admin)
    if scope:
        q = q.filter(or_(TransferRequest.to_campus == scope,
                         TransferRequest.from_campus == scope))
    if status:
        q = q.filter(TransferRequest.status == status)

    items = []
    for r in q.limit(500).all():
        a = db.get(Application, r.application_id)
        fee = None
        remaining = 0
        pay_status = ""
        if a:
            from app.services.fee_service import summary
            fee = summary(a)
            remaining = fee["remaining"]
            pay_status = a.payment_status
        items.append({
            "id": r.id, "application_id": r.application_id,
            "student_name": r.student_name, "current_roll": r.current_roll,
            "from_campus": r.from_campus, "to_campus": r.to_campus,
            "course": r.course, "status": r.status,
            "payment_status": pay_status, "remaining_fee": remaining,
            "reason": r.reason,
            "requested_by": r.requested_by_name,
            "requested_at": str(r.created_at) if r.created_at else "",
            "new_roll": r.new_roll,
            "decided_by": r.decided_by_name,
            "decided_at": str(r.decided_at) if r.decided_at else "",
            # can the current admin act on it? (incoming + pending)
            "can_decide": (not scope or scope == r.to_campus) and r.status == "pending",
            "direction": "incoming" if (scope and scope == r.to_campus)
                         else ("outgoing" if scope else "all"),
        })
    counts = {
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "incoming_pending": sum(1 for i in items
                                if i["status"] == "pending" and i["can_decide"]),
    }
    return {"items": items, "total": len(items), "counts": counts}


@router.post("/api/admin/transfer-requests/{req_id}/decide")
async def decide_transfer(req_id: int, payload: dict,
                          admin: Admin = Depends(managers),
                          db: Session = Depends(get_db)):
    """Approve or reject a pending transfer. Only the destination campus (or the
    super admin) may decide. Approval performs the actual move."""
    from app.models import TransferRequest
    from app.services import roll_service

    action = (payload.get("action") or "").strip().lower()
    if action not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="action must be approve or reject.")

    req = db.get(TransferRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Transfer request not found.")
    if req.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"This request was already {req.status}.")

    scope = admin_campus(admin)
    if scope and scope != req.to_campus:
        raise HTTPException(
            status_code=403,
            detail="Only the destination campus can decide this transfer.")

    a = db.get(Application, req.application_id)
    if not a:
        raise HTTPException(status_code=404, detail="Student application not found.")
    s = a.student
    who = s.full_name if s else "Student"

    # ── REJECT: student untouched ──
    if action == "reject":
        req.status = "rejected"
        req.decided_by_id = admin.id
        req.decided_by_name = admin.name
        req.decided_at = now()
        db.commit()
        db.add(ActivityLog(admin_id=admin.id, action="transfer_rejected",
                           detail=f"{req.current_roll} {req.from_campus} → "
                                  f"{req.to_campus}"))
        db.commit()
        await notify(db, "system", "Transfer rejected",
                     f"Transfer request for {who} ({req.current_roll}) was "
                     f"rejected by {req.to_campus}. The student remains at "
                     f"{req.from_campus}. Decided by {admin.name}.",
                     related_id=a.id, priority="high", category="admission",
                     campus=req.from_campus)
        return {"request_id": req.id, "status": "rejected",
                "message": f"Transfer rejected. {who} stays at {req.from_campus}."}

    # ── APPROVE: perform the move now ──
    from_campus = req.from_campus
    to_campus = req.to_campus
    old_roll = s.roll_number if s else req.current_roll
    new_roll = roll_service.next_transfer_roll(db, to_campus)

    a.previous_roll_number = old_roll
    a.transferred_from = from_campus
    a.transferred_at = now()
    a.campus = to_campus
    if s:
        s.roll_number = new_roll

    req.status = "approved"
    req.new_roll = new_roll
    req.decided_by_id = admin.id
    req.decided_by_name = admin.name
    req.decided_at = now()
    db.commit()
    db.refresh(a)

    db.add(ActivityLog(admin_id=admin.id, action="transfer_approved",
                       detail=f"{old_roll} ({from_campus}) → {new_roll} "
                              f"({to_campus})"))
    db.commit()

    await notify(db, "system", "Transfer approved",
                 f"Transfer approved by {to_campus}. {who} moved from "
                 f"{from_campus} ({old_roll}) to {to_campus} and assigned new "
                 f"roll number {new_roll}. Approved by {admin.name}.",
                 related_id=a.id, priority="high", category="admission",
                 campus=to_campus)
    await notify(db, "system", "Transfer approved — student moved",
                 f"{who} ({old_roll}) has been transferred to {to_campus} as "
                 f"{new_roll}. Approved by {admin.name}.",
                 related_id=a.id, priority="normal", category="admission",
                 campus=from_campus)

    return {"request_id": req.id, "status": "approved",
            "application_id": a.id, "student_name": who,
            "from_campus": from_campus, "old_roll": old_roll,
            "to_campus": to_campus, "new_roll": new_roll,
            "message": f"{who} transferred to {to_campus} as {new_roll}."}


# ── Referrals visible on admin / super-admin dashboards ──────────────────
@router.get("/api/admin/referrals")
def admin_referrals(enrolled_only: bool = False,
                    admin: Admin = Depends(any_staff),
                    db: Session = Depends(get_db)):
    """Referral students for the Referrals dashboard section. Campus-scoped."""
    q = (db.query(Application)
         .options(joinedload(Application.student))
         .filter(Application.is_referral.is_(True)))
    scope = admin_campus(admin)
    if scope:
        q = q.filter(Application.campus == scope)
    if enrolled_only:
        q = q.filter(Application.referral_enrolled.is_(True))
    rows = q.order_by(Application.submitted_at.desc()).limit(500).all()

    items = []
    for a in rows:
        s = a.student
        from app.services.fee_service import summary
        fee = summary(a)
        rstatus = a.referral_status or "pending"
        items.append({
            "id": a.id,
            "student_name": s.full_name if s else "",
            "roll_number": s.roll_number if s else "",
            "phone": s.phone if s else "",
            "campus": a.campus or "",
            "course": a.course_name or "",
            "referral_status": rstatus,
            "enrollment_status": ("Enrolled" if a.referral_enrolled
                                  else rstatus.title()),
            "enrolled": bool(a.referral_enrolled),
            "total_fee": fee["total_fee"],
            "paid": fee["paid"],
            "remaining_fee": fee["remaining"],
            "payment_status": a.payment_status,
            "enrollment_date": a.referral_enrolled_at or a.submitted_at,
        })
    return {"items": items, "total": len(items),
            "enrolled": sum(1 for i in items if i["enrolled"]),
            "pending": sum(1 for i in items
                           if i["referral_status"] == "pending"),
            "rejected": sum(1 for i in items
                            if i["referral_status"] == "rejected"),
            "total_fee": round(sum(i["total_fee"] for i in items), 2),
            "collected": round(sum(i["paid"] for i in items), 2)}


@router.post("/api/admin/referrals/{app_id}/enroll")
async def enroll_referral(app_id: int, admin: Admin = Depends(managers),
                          db: Session = Depends(get_db)):
    """Mark a referral student as enrolled."""
    a = _get_or_404(db, app_id, admin)
    if not a.is_referral:
        raise HTTPException(status_code=422,
                            detail="This is not a referral application.")
    a.referral_enrolled = True
    a.referral_enrolled_at = now()
    db.commit()
    s = a.student
    await notify(db, "system", "Referral student enrolled",
                 f"{s.full_name if s else 'Student'} "
                 f"({s.roll_number if s else ''}) was enrolled at "
                 f"{a.campus or '—'} by {admin.name}.",
                 related_id=a.id, priority="normal", category="referral",
                 campus=a.campus or "")
    return {"id": a.id, "enrolled": True}


# ── Referral Applications — the campus admin accepts or rejects them ─────
@router.get("/api/admin/referral-applications")
def referral_applications(status: str | None = None,
                          q: str | None = None,
                          admin: Admin = Depends(any_staff),
                          db: Session = Depends(get_db)):
    """Referral applications for this campus, kept out of the normal
    Applications list. A campus admin sees only their own campus's referrals."""
    from app.services.fee_service import summary

    query = (db.query(Application).join(Student)
             .options(joinedload(Application.student))
             .filter(Application.is_referral.is_(True))
             .order_by(desc(Application.submitted_at)))
    scope = admin_campus(admin)
    if scope:
        query = query.filter(Application.campus == scope)
    if status:
        query = query.filter(Application.referral_status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Student.full_name.ilike(like),
                                 Student.roll_number.ilike(like),
                                 Student.phone.ilike(like)))

    items = []
    for a in query.limit(500).all():
        s = a.student
        fee = summary(a)
        items.append({
            "id": a.id,
            "roll_number": s.roll_number if s else "",
            "student_name": s.full_name if s else "",
            "phone": s.phone if s else "",
            "guardian_phone": getattr(s, "guardian_phone", "") if s else "",
            "campus": a.campus or "",
            "course": a.course_name or "",
            "programme": a.programme_category or "",
            "lead_source": a.lead_source or "",
            "total_fee": fee["total_fee"],
            "paid": fee["paid"],
            "remaining_fee": fee["remaining"],
            "payment_status": a.payment_status,
            "referral_status": a.referral_status or "pending",
            "decided_by": a.referral_decided_by or "",
            "decided_at": a.referral_decided_at,
            "remarks": a.referral_remarks or "",
            "submitted_at": a.submitted_at,
        })

    counts = {
        "pending": sum(1 for i in items if i["referral_status"] == "pending"),
        "accepted": sum(1 for i in items if i["referral_status"] == "accepted"),
        "rejected": sum(1 for i in items if i["referral_status"] == "rejected"),
    }
    return {"items": items, "total": len(items), "counts": counts}


@router.post("/api/admin/referral-applications/{app_id}/decide")
async def decide_referral_application(app_id: int, payload: dict,
                                      admin: Admin = Depends(managers),
                                      db: Session = Depends(get_db)):
    """Accept or reject a referral application. Only the campus it was referred
    to may decide (the super admin may decide for any campus)."""
    action = (payload.get("action") or "").strip().lower()
    remarks = (payload.get("remarks") or "").strip()[:400]
    if action not in ("accept", "reject"):
        raise HTTPException(status_code=422,
                            detail="action must be accept or reject.")

    a = db.get(Application, app_id)
    if not a or not a.is_referral:
        raise HTTPException(status_code=404,
                            detail="Referral application not found.")
    scope = admin_campus(admin)
    if scope and scope != (a.campus or ""):
        raise HTTPException(
            status_code=403,
            detail="Only the campus this student was referred to can decide.")
    if (a.referral_status or "pending") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"This referral was already {a.referral_status}.")

    s = a.student
    who = s.full_name if s else "Student"
    roll = s.roll_number if s else ""

    if action == "accept":
        a.referral_status = "accepted"
        a.referral_enrolled = True
        a.referral_enrolled_at = now()
        a.application_status = ApplicationStatus.APPROVED
        title, msg = "Referral accepted", (
            f"{who} ({roll}) was accepted at {a.campus} by {admin.name}.")
    else:
        a.referral_status = "rejected"
        a.referral_enrolled = False
        a.application_status = ApplicationStatus.REJECTED
        title, msg = "Referral rejected", (
            f"{who} ({roll}) was rejected at {a.campus} by {admin.name}.")

    a.referral_decided_by = admin.name
    a.referral_decided_at = now()
    a.referral_remarks = remarks
    db.commit()
    db.refresh(a)

    db.add(ActivityLog(admin_id=admin.id, action=f"referral_{action}ed",
                       detail=f"{roll} ({a.campus})"))
    db.commit()

    await notify(db, "system", title,
                 msg + (f" Remarks: {remarks}" if remarks else ""),
                 related_id=a.id, priority="normal", category="admission",
                 campus=a.campus or "")

    return {"id": a.id, "referral_status": a.referral_status,
            "student_name": who, "roll_number": roll,
            "message": f"{who} ({roll}) {a.referral_status}."}


@router.delete("/api/admin/applications/{app_id}")
def delete_application(app_id: int, admin: Admin = Depends(managers),
                       db: Session = Depends(get_db)):
    """Delete an application and its associated payments, installments, allocations, and student record."""
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(status_code=404, detail="Application not found.")

    scope = admin_campus(admin)
    if scope and scope != (a.campus or ""):
        raise HTTPException(
            status_code=403,
            detail="You can only delete applications belonging to your campus.")

    student_id = a.student_id
    roll = a.student.roll_number if a.student else str(app_id)
    name = a.student.full_name if a.student else "Student"

    from app.models import (ApplicationNote, Challan, Installment, Payment,
                            PaymentAllocation)
    db.query(PaymentAllocation).filter(
        PaymentAllocation.application_id == app_id).delete(synchronize_session=False)
    db.query(Payment).filter(
        Payment.application_id == app_id).delete(synchronize_session=False)
    db.query(Installment).filter(
        Installment.application_id == app_id).delete(synchronize_session=False)
    db.query(Challan).filter(
        Challan.application_id == app_id).delete(synchronize_session=False)
    db.query(ApplicationNote).filter(
        ApplicationNote.application_id == app_id).delete(synchronize_session=False)

    db.delete(a)
    db.commit()

    if student_id:
        other_apps = db.query(Application).filter(
            Application.student_id == student_id).count()
        if other_apps == 0:
            st = db.get(Student, student_id)
            if st:
                db.delete(st)
                db.commit()

    db.add(ActivityLog(admin_id=admin.id, action="delete_application",
                       detail=f"{name} ({roll})"))
    db.commit()

    return {"message": f"Application {roll} ({name}) deleted successfully."}
