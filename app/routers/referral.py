"""Referral Portal — a separate portal with its own login.

Referral partners sign in here (never the admin portal), pick one of the two
referral campuses, and submit admissions using the same application form. Their
students get F- roll numbers, stay out of the campus's normal Applications list,
and the campus admin is notified the moment a referral arrives.
"""
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from app.auth.security import verify_password
from app.config import settings
from app.database import get_db
from app.models import Application, ReferralUser, Student
from app.schemas.application import ApplicationSubmit
from app.schemas.serialize import application_to_dict
from app.services.notification_service import notify
from app.utils.timeutil import now

router = APIRouter(tags=["referral"])
_bearer = HTTPBearer(auto_error=False)

REFERRAL_CAMPUSES = ["Darogwala", "Bhagbanpura"]


# ── Auth ────────────────────────────────────────────────────────────────
class ReferralLogin(BaseModel):
    email: str = Field(min_length=3, max_length=160)
    password: str = Field(min_length=1)


def current_referral_user(
        creds: HTTPAuthorizationCredentials = Depends(_bearer),
        db: Session = Depends(get_db)) -> ReferralUser:
    """Referral tokens carry scope='referral' so an admin token can never be
    used here, and a referral token can never be used on admin routes."""
    if not creds:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(creds.credentials, settings.SECRET_KEY,
                             algorithms=[settings.JWT_ALGORITHM])
        if payload.get("scope") != "referral":
            raise HTTPException(status_code=401, detail="Not authenticated")
        uid = int(payload.get("sub"))
    except (jwt.PyJWTError, TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = db.get(ReferralUser, uid)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account is disabled.")
    return user


@router.post("/api/referral/login")
def referral_login(payload: ReferralLogin, db: Session = Depends(get_db)):
    user = (db.query(ReferralUser)
            .filter(ReferralUser.email == payload.email.lower()).first())
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401,
                            detail="Incorrect email or password.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled.")
    user.last_login = now()
    db.commit()
    token = jwt.encode(
        {"sub": str(user.id), "scope": "referral",
         "exp": now() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)},
        settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return {"access_token": token, "token_type": "bearer",
            "user": {"id": user.id, "name": user.name, "email": user.email}}


@router.get("/api/referral/me")
def referral_me(user: ReferralUser = Depends(current_referral_user)):
    return {"id": user.id, "name": user.name, "email": user.email,
            "campuses": REFERRAL_CAMPUSES}


# ── Dashboard ───────────────────────────────────────────────────────────
@router.get("/api/referral/stats")
def referral_stats(user: ReferralUser = Depends(current_referral_user),
                   db: Session = Depends(get_db)):
    q = db.query(Application).filter(Application.is_referral.is_(True),
                                     Application.referral_user_id == user.id)
    total = q.count()
    enrolled = q.filter(Application.referral_enrolled.is_(True)).count()
    return {"total_referrals": total,
            "enrolled_referrals": enrolled,
            "pending_referrals": total - enrolled}


# ── Applications ────────────────────────────────────────────────────────
@router.get("/api/referral/next-roll")
def referral_next_roll(campus: str,
                       user: ReferralUser = Depends(current_referral_user),
                       db: Session = Depends(get_db)):
    from app.services import roll_service
    if campus not in REFERRAL_CAMPUSES:
        raise HTTPException(status_code=422,
                            detail="Referrals are only for Darogwala and Bhagbanpura.")
    return {"campus": campus,
            "next_roll": roll_service.next_referral_roll(db, campus)}


@router.get("/api/referral/applications")
def referral_applications(user: ReferralUser = Depends(current_referral_user),
                          db: Session = Depends(get_db)):
    rows = (db.query(Application)
            .options(joinedload(Application.student))
            .filter(Application.is_referral.is_(True),
                    Application.referral_user_id == user.id)
            .order_by(Application.submitted_at.desc())
            .limit(500).all())
    return {"items": [application_to_dict(a) for a in rows],
            "total": len(rows)}


class ReferralSubmit(ApplicationSubmit):
    """Same admission form as the admin portal, except the roll number is not
    supplied — the server assigns the next F- number itself."""
    roll_number: str = Field(default="AUTO")


@router.post("/api/referral/applications", status_code=201)
async def create_referral_application(
        payload: ReferralSubmit,
        user: ReferralUser = Depends(current_referral_user),
        db: Session = Depends(get_db)):
    """Same admission form as the admin portal — only the roll number series
    and the visibility rules differ."""
    from app.routers.applications import _create_application
    from app.services import roll_service

    campus = (payload.campus or "").strip()
    if campus not in REFERRAL_CAMPUSES:
        raise HTTPException(
            status_code=422,
            detail="Referral admissions are only open for Darogwala and "
                   "Bhagbanpura.")

    # F- roll number, kept in step with the campus numbering.
    payload.roll_number = roll_service.next_referral_roll(db, campus)

    result = await _create_application(db, payload,
                                       created_by=f"Referral: {user.name}")

    app_obj = db.get(Application, result["id"])
    app_obj.is_referral = True
    app_obj.referral_user_id = user.id
    db.commit()

    # The campus admin must know immediately — but the application stays out of
    # their normal Applications list.
    s = app_obj.student
    await notify(db, "system", "Referral application created",
                 f"{s.full_name} ({s.roll_number}) was referred to {campus} "
                 f"by {user.name} for {app_obj.course_name or '—'}.",
                 related_id=app_obj.id, priority="high",
                 category="referral", campus=campus)

    return application_to_dict(app_obj, include_detail=True)


@router.get("/referral", response_class=HTMLResponse, include_in_schema=False)
def referral_page():
    from pathlib import Path
    f = Path("static/referral.html")
    if not f.exists():
        raise HTTPException(status_code=404, detail="Referral portal not found")
    return HTMLResponse(f.read_text(encoding="utf-8"))
