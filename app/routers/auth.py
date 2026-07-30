"""Authentication and admin-account management."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_admin, super_only
from app.auth.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import ActivityLog, Admin, Role
from app.schemas.auth import AdminCreate, AdminUpdate, ChangePassword, LoginRequest, TokenResponse
from app.schemas.serialize import admin_to_dict
from app.utils.rate_limit import rate_limit
from app.utils.timeutil import now

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse,
             dependencies=[Depends(rate_limit("login", limit=8, window_seconds=60))])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    admin = db.query(Admin).filter(Admin.email == payload.email.lower().strip()).first()
    if not admin or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not admin.is_active:
        raise HTTPException(status_code=403, detail="This account has been disabled")

    admin.last_login = now()
    db.add(ActivityLog(admin_id=admin.id, action="login",
                       detail=f"{admin.email} signed in"))
    db.commit()

    token = create_access_token(admin.id, admin.role)
    return TokenResponse(access_token=token, admin=admin_to_dict(admin))


@router.get("/me")
def me(admin: Admin = Depends(get_current_admin)):
    return admin_to_dict(admin)


@router.post("/change-password")
def change_password(payload: ChangePassword,
                    admin: Admin = Depends(get_current_admin),
                    db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    admin.password_hash = hash_password(payload.new_password)
    db.add(ActivityLog(admin_id=admin.id, action="password_change",
                       detail=f"{admin.email} changed their password"))
    db.commit()
    return {"success": True, "message": "Password updated"}


# ── Admin management (super admin only) ──────────────────────────────────
@router.get("/admins")
def list_admins(admin: Admin = Depends(super_only), db: Session = Depends(get_db)):
    admins = db.query(Admin).order_by(Admin.created_at).all()
    return {"items": [admin_to_dict(a) for a in admins]}


@router.post("/admins", status_code=201)
def create_admin(payload: AdminCreate, admin: Admin = Depends(super_only),
                 db: Session = Depends(get_db)):
    email = payload.email.lower().strip()
    if db.query(Admin).filter(Admin.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    new_admin = Admin(name=payload.name.strip(), email=email,
                      password_hash=hash_password(payload.password),
                      role=payload.role)
    db.add(new_admin)
    db.add(ActivityLog(admin_id=admin.id, action="admin_created",
                       detail=f"Created {payload.role} account for {email}"))
    db.commit()
    db.refresh(new_admin)
    return admin_to_dict(new_admin)


@router.patch("/admins/{admin_id}")
def update_admin(admin_id: int, payload: AdminUpdate,
                 admin: Admin = Depends(super_only), db: Session = Depends(get_db)):
    target = db.get(Admin, admin_id)
    if not target:
        raise HTTPException(status_code=404, detail="Admin not found")
    if target.id == admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You can't disable your own account")
    if payload.name is not None:
        target.name = payload.name.strip()
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.password:
        target.password_hash = hash_password(payload.password)
    db.add(ActivityLog(admin_id=admin.id, action="admin_updated",
                       detail=f"Updated account {target.email}"))
    db.commit()
    return admin_to_dict(target)
