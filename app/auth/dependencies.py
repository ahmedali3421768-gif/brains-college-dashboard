"""FastAPI dependencies protecting the admin APIs (JWT + role based access)."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_token
from app.database import get_db
from app.models import Admin, Role

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Admin:
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(creds.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    # A referral-portal token must never authenticate an admin request. Its
    # "sub" is a ReferralUser id, which would otherwise be looked up against the
    # admins table and could match an unrelated admin account.
    if payload.get("scope") not in (None, "admin"):
        raise HTTPException(status_code=401, detail="Invalid token for this portal")
    admin = db.get(Admin, int(payload.get("sub", 0)))
    if not admin or not admin.is_active:
        raise HTTPException(status_code=401, detail="Account not found or disabled")
    return admin


def require_roles(*roles: str):
    """Role guard. super_admin always passes."""
    def dependency(admin: Admin = Depends(get_current_admin)) -> Admin:
        if admin.role == Role.SUPER_ADMIN or admin.role in roles:
            return admin
        raise HTTPException(
            status_code=403, detail="You don't have permission for this action"
        )
    return dependency


# Convenience guards used across routers
any_staff = require_roles(Role.STAFF, Role.ADMIN)   # read access
managers = require_roles(Role.ADMIN)                # write access
super_only = require_roles()                        # super_admin only


def receptionist_only(admin: Admin = Depends(get_current_admin)) -> Admin:
    """Guard for the reception fee-lookup API. Allows receptionists (and, for
    convenience, super admins) — but NOT regular admins/staff, keeping the
    reception surface tightly scoped."""
    if admin.role in (Role.RECEPTIONIST, Role.SUPER_ADMIN):
        return admin
    raise HTTPException(
        status_code=403, detail="You don't have permission for this action")


# ── Campus scoping (multi-campus) ────────────────────────────────────────
def admin_campus(admin: Admin) -> str | None:
    """The campus an admin is limited to, or None for college-wide access.

    Super admins (and any admin with no campus set) see every campus.
    Everyone else is limited to their own campus.
    """
    if admin.role == Role.SUPER_ADMIN:
        return None
    return (admin.campus or "").strip() or None


def scope_query(query, model, admin: Admin):
    """Filter a SQLAlchemy query to the admin's campus when the model has a
    `campus` column. For applications, includes both current campus and source
    campus (transferred_from) so source campus retains historical access."""
    from sqlalchemy import or_
    campus = admin_campus(admin)
    if campus and hasattr(model, "campus"):
        if hasattr(model, "transferred_from"):
            query = query.filter(or_(model.campus == campus, model.transferred_from == campus))
        else:
            query = query.filter(model.campus == campus)
    return query
