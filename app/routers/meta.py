"""Departments & courses, leads management, global search and health check."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import any_staff, managers, super_only, admin_campus
from app.config import VALID_CAMPUSES, settings
from app.database import get_db
from app.models import (
    Admin, Application, ChatMessage, ChatSession, Course, Department, Lead,
    Student,
)
from app.schemas.application import LeadStatusUpdate
from app.schemas.serialize import application_to_dict, lead_to_dict, session_to_dict
from app.utils.pagination import paginate

router = APIRouter(tags=["meta"])


# ── Public metadata for the website's admission form ─────────────────────
@router.get("/api/meta/form-options")
def form_options(db: Session = Depends(get_db)):
    from app.catalog import (LEAD_SOURCES, PROGRAMME_CATEGORIES, catalog_for_frontend)
    from app.config import settings
    departments = db.query(Department).filter(Department.is_active).all()
    courses = db.query(Course).filter(Course.is_active).all()
    return {
        "campuses": VALID_CAMPUSES,
        "departments": [{"id": d.id, "name": d.name, "code": d.code}
                        for d in departments],
        "courses": [{"id": c.id, "name": c.name, "code": c.code,
                     "department_id": c.department_id} for c in courses],
        "programme_categories": PROGRAMME_CATEGORIES,
        "programme_catalog": catalog_for_frontend(),
        "advance_amount": settings.CHALLAN_DEFAULT_AMOUNT,
        "lead_sources": LEAD_SOURCES,
        "sessions": _recent_sessions(),
    }


def _recent_sessions() -> list[str]:
    from app.utils.timeutil import now
    y = now().year
    return [f"Spring {y}", f"Fall {y}", f"Spring {y + 1}", f"Fall {y + 1}"]


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str = Field(min_length=1, max_length=20)


class CourseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    code: str = Field(min_length=1, max_length=30)
    department_id: int


@router.post("/api/admin/departments", status_code=201)
def create_department(payload: DepartmentCreate,
                      admin: Admin = Depends(super_only),
                      db: Session = Depends(get_db)):
    if db.query(Department).filter(or_(Department.name == payload.name,
                                       Department.code == payload.code)).first():
        raise HTTPException(status_code=409, detail="Department already exists")
    d = Department(name=payload.name, code=payload.code)
    db.add(d)
    db.commit()
    db.refresh(d)
    return {"id": d.id, "name": d.name, "code": d.code}


@router.post("/api/admin/courses", status_code=201)
def create_course(payload: CourseCreate, admin: Admin = Depends(super_only),
                  db: Session = Depends(get_db)):
    if not db.get(Department, payload.department_id):
        raise HTTPException(status_code=404, detail="Department not found")
    if db.query(Course).filter(Course.code == payload.code).first():
        raise HTTPException(status_code=409, detail="Course code already exists")
    c = Course(name=payload.name, code=payload.code,
               department_id=payload.department_id)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "name": c.name, "code": c.code,
            "department_id": c.department_id}


# ── Leads management ─────────────────────────────────────────────────────
@router.get("/api/admin/leads")
def list_leads(q: str | None = None, status: str | None = None,
               campus: str | None = None, source: str | None = None,
               assigned_to: int | None = None,
               follow_up_due: bool | None = None,
               date_from: str | None = None, date_to: str | None = None,
               page: int = Query(1, ge=1),
               page_size: int = Query(20, ge=1, le=100),
               admin: Admin = Depends(any_staff),
               db: Session = Depends(get_db)):
    query = db.query(Lead).order_by(desc(Lead.created_at))
    _campus = admin_campus(admin)
    if _campus:
        query = query.filter(Lead.campus == _campus)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            Lead.name.ilike(like), Lead.phone.ilike(like),
            Lead.email.ilike(like), Lead.city.ilike(like),
            Lead.interested_course.ilike(like)))
    if status:
        query = query.filter(Lead.status == status)
    if campus:
        query = query.filter(Lead.campus == campus)
    if source:
        query = query.filter(Lead.source == source)
    if assigned_to:
        query = query.filter(Lead.assigned_to == assigned_to)
    if follow_up_due:
        from app.utils.timeutil import now as _now
        query = query.filter(Lead.follow_up_at.isnot(None),
                             Lead.follow_up_at <= _now())
    if date_from:
        query = query.filter(Lead.created_at >= f"{date_from} 00:00:00")
    if date_to:
        query = query.filter(Lead.created_at <= f"{date_to} 23:59:59")
    result = paginate(query, page, page_size)
    result["items"] = [lead_to_dict(l) for l in result["items"]]
    return result


@router.get("/api/admin/leads/{lead_id}")
def lead_detail(lead_id: int, admin: Admin = Depends(any_staff),
                db: Session = Depends(get_db)):
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    _c = admin_campus(admin)
    if _c and (lead.campus or "") != _c:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead_to_dict(lead, include_notes=True)


class LeadUpdate(BaseModel):
    status: str | None = None
    assigned_to: int | None = None
    follow_up_at: str | None = None  # "YYYY-MM-DDTHH:MM" or "" to clear


@router.patch("/api/admin/leads/{lead_id}")
def update_lead(lead_id: int, payload: LeadUpdate,
                admin: Admin = Depends(managers), db: Session = Depends(get_db)):
    from datetime import datetime as _dt

    from app.models import LeadStatus
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    _c = admin_campus(admin)
    if _c and (lead.campus or "") != _c:
        raise HTTPException(status_code=404, detail="Lead not found")
    if payload.status is not None:
        if payload.status not in LeadStatus.ALL:
            raise HTTPException(
                status_code=400,
                detail=f"Status must be one of: {', '.join(LeadStatus.ALL)}")
        lead.status = payload.status
    if payload.assigned_to is not None:
        if payload.assigned_to == 0:
            lead.assigned_to = None
            lead.assigned_to_name = ""
        else:
            target = db.get(Admin, payload.assigned_to)
            if not target:
                raise HTTPException(status_code=404, detail="Admin not found")
            lead.assigned_to = target.id
            lead.assigned_to_name = target.name
    if payload.follow_up_at is not None:
        if payload.follow_up_at.strip() == "":
            lead.follow_up_at = None
        else:
            try:
                lead.follow_up_at = _dt.fromisoformat(payload.follow_up_at)
            except ValueError:
                raise HTTPException(status_code=400,
                                    detail="follow_up_at must be ISO datetime")
    db.commit()
    return lead_to_dict(lead)


class LeadNoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


@router.post("/api/admin/leads/{lead_id}/notes", status_code=201)
def add_lead_note(lead_id: int, payload: LeadNoteCreate,
                  admin: Admin = Depends(managers),
                  db: Session = Depends(get_db)):
    from app.models import LeadNote
    lead = db.get(Lead, lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    _c = admin_campus(admin)
    if _c and (lead.campus or "") != _c:
        raise HTTPException(status_code=404, detail="Lead not found")
    n = LeadNote(lead_id=lead.id, admin_id=admin.id, admin_name=admin.name,
                 note=payload.note.strip())
    db.add(n)
    db.commit()
    return {"success": True}


# ── Global search (Part 10) ──────────────────────────────────────────────
@router.get("/api/admin/search")
def global_search(q: str = Query(min_length=2, max_length=100),
                  admin: Admin = Depends(any_staff),
                  db: Session = Depends(get_db)):
    like = f"%{q.strip()}%"

    apps = (db.query(Application).join(Student)
            .filter(or_(Student.full_name.ilike(like),
                        Student.phone.ilike(like),
                        Student.email.ilike(like),
                        Student.cnic.ilike(like),
                        Application.application_no.ilike(like)))
            .order_by(desc(Application.submitted_at)).limit(5).all())

    message_match = (db.query(ChatMessage.session_id)
                     .filter(ChatMessage.content.ilike(like)).subquery())
    sessions = (db.query(ChatSession)
                .filter(or_(ChatSession.title.ilike(like),
                            ChatSession.visitor_name.ilike(like),
                            ChatSession.visitor_phone.ilike(like),
                            ChatSession.id.in_(message_match.select())))
                .order_by(desc(ChatSession.last_activity_at)).limit(5).all())

    leads = (db.query(Lead)
             .filter(or_(Lead.name.ilike(like), Lead.phone.ilike(like)))
             .order_by(desc(Lead.created_at)).limit(5).all())

    return {"applications": [application_to_dict(a) for a in apps],
            "chats": [session_to_dict(s) for s in sessions],
            "leads": [lead_to_dict(l) for l in leads]}


# ── Health check (kept from the original project, minus Google Sheets) ──
@router.get("/api/health")
def health(db: Session = Depends(get_db)):
    db_ok, db_msg = True, "connected"
    try:
        db.query(Department).first()
    except Exception as e:  # pragma: no cover
        db_ok, db_msg = False, str(e)
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "Brains College Chatbot",
        "version": settings.VERSION,
        "groq_key_set": bool(settings.GROQ_API_KEY),
        "database_status": db_msg,
        "database_ok": db_ok,
    }
