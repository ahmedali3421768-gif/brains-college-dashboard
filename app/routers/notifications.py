"""Dashboard notifications (Part 12) — campus-scoped."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.auth.dependencies import admin_campus, any_staff
from app.database import get_db
from app.models import Admin, Notification
from app.schemas.serialize import notification_to_dict
from app.utils.pagination import paginate

router = APIRouter(prefix="/api/admin/notifications", tags=["notifications"])


def _scope(query, admin: Admin):
    """Limit notifications to the admin's campus. A campus admin sees only
    their own campus's notifications; the super admin sees all of them."""
    campus = admin_campus(admin)
    if campus:
        query = query.filter(Notification.campus == campus)
    return query


@router.get("")
def list_notifications(unread_only: bool = False,
                       category: str | None = None,
                       priority: str | None = None,
                       page: int = Query(1, ge=1),
                       page_size: int = Query(20, ge=1, le=100),
                       admin: Admin = Depends(any_staff),
                       db: Session = Depends(get_db)):
    query = _scope(db.query(Notification), admin).order_by(
        desc(Notification.created_at))
    if unread_only:
        query = query.filter(Notification.is_read.is_(False))
    if category:
        query = query.filter(Notification.category == category)
    if priority:
        query = query.filter(Notification.priority == priority)
    result = paginate(query, page, page_size)
    result["items"] = [notification_to_dict(n) for n in result["items"]]
    result["unread"] = _scope(db.query(Notification), admin).filter(
        Notification.is_read.is_(False)).count()
    return result


@router.get("/unread-count")
def unread_count(admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    return {"unread": _scope(db.query(Notification), admin).filter(
        Notification.is_read.is_(False)).count()}


@router.patch("/{notification_id}/read")
def mark_read(notification_id: int, admin: Admin = Depends(any_staff),
              db: Session = Depends(get_db)):
    n = db.get(Notification, notification_id)
    if not n:
        raise HTTPException(status_code=404, detail="Notification not found")
    _c = admin_campus(admin)
    if _c and (n.campus or "") != _c:
        raise HTTPException(status_code=404, detail="Notification not found")
    n.is_read = True
    from app.utils.timeutil import now
    n.read_at = now()
    db.commit()
    return {"success": True}


@router.post("/read-all")
def mark_all_read(admin: Admin = Depends(any_staff),
                  db: Session = Depends(get_db)):
    _scope(db.query(Notification), admin).filter(
        Notification.is_read.is_(False)).update(
        {Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"success": True}


@router.get("/analytics")
def notification_analytics(admin: Admin = Depends(any_staff),
                           db: Session = Depends(get_db)):
    """Module 4 dashboard: sent / read / unread / duplicates prevented."""
    base = lambda: _scope(db.query(Notification), admin)

    total = base().count()
    read = base().filter(Notification.is_read.is_(True)).count()
    dup_prevented = base().with_entities(
        func.coalesce(func.sum(Notification.occurrences - 1), 0)).scalar() or 0
    by_category = (base().with_entities(
        Notification.category, func.count(Notification.id))
        .group_by(Notification.category).all())
    by_priority = (base().with_entities(
        Notification.priority, func.count(Notification.id))
        .group_by(Notification.priority).all())
    return {
        "sent": total,
        "delivered": total,          # in-app: delivered == stored
        "read": read,
        "unread": total - read,
        "duplicates_prevented": int(dup_prevented),
        "open_rate": round(read / total * 100, 1) if total else 0.0,
        "by_category": [{"category": c, "count": n} for c, n in by_category],
        "by_priority": [{"priority": p_, "count": n} for p_, n in by_priority],
    }
