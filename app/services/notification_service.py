"""Smart notifications (Module 4).

Before creating any notification we compute a content hash. If an identical
notification already exists, we do NOT create it again — we bump its
`occurrences` counter and `updated_at` instead. When the underlying event
changes (e.g. a different status, a new reminder bucket), the hash changes,
so a fresh notification is correctly sent once.
"""
import hashlib

from sqlalchemy.orm import Session

from app.models import Notification, NotificationPriority
from app.services.ws_manager import manager
from app.utils.timeutil import now

# type → category mapping (spec: Admission, Application, Payment, …)
CATEGORY_MAP = {
    "new_application": "application",
    "application_approved": "admission",
    "application_rejected": "admission",
    "application_on_hold": "admission",
    "admission_approved": "admission",
    "payment_verified": "payment",
    "receipt_uploaded": "payment",
    "receipt_rejected": "payment",
    "reupload_requested": "payment",
    "fee_due_reminder": "deadline",
    "chat_started": "chatbot",
    "new_lead": "general",
    "documents_required": "documents",
}


def _hash(type_: str, related_id, title: str, message: str,
          campus: str = "") -> str:
    raw = f"{type_}|{related_id}|{title}|{message}|{campus}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def notify(
    db: Session, type_: str, title: str, message: str = "", related_id=None,
    priority: str = NotificationPriority.NORMAL, category: str | None = None,
    campus: str = "",
) -> Notification | None:
    """Create a notification exactly once. Returns None when a duplicate was
    prevented (the existing row is refreshed instead). `campus` scopes the
    notification so each campus only sees its own alerts."""
    campus = (campus or "").strip()
    h = _hash(type_, related_id, title, message, campus)

    existing = db.query(Notification).filter(Notification.hash == h).first()
    if existing:
        existing.occurrences = (existing.occurrences or 1) + 1
        existing.updated_at = now()
        db.commit()
        return None  # duplicate prevented — nothing broadcast

    n = Notification(
        type=type_,
        category=category or CATEGORY_MAP.get(type_, "general"),
        priority=priority,
        title=title,
        message=message,
        related_id=str(related_id) if related_id is not None else None,
        campus=campus,
        hash=h,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    await manager.broadcast("notification", {
        "id": n.id, "type": n.type, "category": n.category,
        "priority": n.priority, "title": n.title,
        "message": n.message, "related_id": n.related_id,
        "campus": n.campus,
        "created_at": n.created_at,
    })
    return n
