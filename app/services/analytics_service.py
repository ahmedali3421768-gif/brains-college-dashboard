"""All aggregate queries powering the dashboard and analytics pages."""
import re
from collections import Counter
from datetime import timedelta

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import (
    Application, ApplicationStatus, ChatMessage, ChatSession, Course,
    Department, Lead, Student,
)
from app.utils.timeutil import days_ago, now, start_of_month, start_of_today, start_of_year


# ── Dashboard overview cards ─────────────────────────────────────────────
def _scope_apps(db: Session, campus: str | None = None,
                date_from: str | None = None, date_to: str | None = None):
    """A base Application query filtered by campus and/or submission date."""
    q = db.query(Application)
    if campus:
        q = q.filter(Application.campus == campus)
    if date_from:
        q = q.filter(Application.submitted_at >= f"{date_from} 00:00:00")
    if date_to:
        q = q.filter(Application.submitted_at <= f"{date_to} 23:59:59")
    return q


def overview(db: Session, campus: str | None = None,
             date_from: str | None = None, date_to: str | None = None) -> dict:
    apps = _scope_apps(db, campus, date_from, date_to)

    leads_q = db.query(Lead)
    chats_q = db.query(ChatSession)
    if campus:
        leads_q = leads_q.filter(Lead.campus == campus)
        chats_q = chats_q.filter(ChatSession.campus == campus)

    # When a custom range is given, "today/month/year" collapse to the range.
    ranged = bool(date_from or date_to)
    return {
        "total_applications": apps.count(),
        "applications_today": apps.count() if ranged else apps.filter(
            Application.submitted_at >= start_of_today()).count(),
        "applications_this_month": apps.count() if ranged else apps.filter(
            Application.submitted_at >= start_of_month()).count(),
        "applications_this_year": apps.count() if ranged else apps.filter(
            Application.submitted_at >= start_of_year()).count(),
        "pending": apps.filter(
            Application.application_status == ApplicationStatus.PENDING).count(),
        "approved": apps.filter(
            Application.application_status == ApplicationStatus.APPROVED).count(),
        "rejected": apps.filter(
            Application.application_status == ApplicationStatus.REJECTED).count(),
        "dropped_out": apps.filter(
            Application.application_status
            == ApplicationStatus.DROPPED_OUT).count(),
        "on_hold": apps.filter(
            Application.application_status == ApplicationStatus.ON_HOLD).count(),
        "total_students": apps.count(),
        "total_chat_sessions": chats_q.count(),
        "chats_today": chats_q.filter(
            ChatSession.started_at >= start_of_today()).count(),
        "total_chat_messages": db.query(ChatMessage).count(),
        "total_leads": leads_q.count(),
        "new_leads": leads_q.filter(Lead.status == "new").count(),
        "departments": db.query(Department).count(),
    }


# ── Time series helpers ──────────────────────────────────────────────────
def _daily_counts(db: Session, column, days: int, model=None,
                  campus: str | None = None) -> list[dict]:
    """Portable daily grouping (SQLite + PostgreSQL) via func.date()."""
    since = days_ago(days - 1)
    q = db.query(func.date(column).label("d"), func.count().label("c")).filter(
        column >= since)
    if campus and model is not None and hasattr(model, "campus"):
        q = q.filter(model.campus == campus)
    rows = q.group_by("d").order_by("d").all()
    counts = {str(r.d): r.c for r in rows}
    out = []
    for i in range(days):
        day = (since + timedelta(days=i)).date()
        out.append({"date": str(day), "count": counts.get(str(day), 0)})
    return out


def application_growth(db: Session, days: int = 30,
                       campus: str | None = None) -> list[dict]:
    return _daily_counts(db, Application.submitted_at, days,
                         model=Application, campus=campus)


def chat_daily(db: Session, days: int = 30) -> list[dict]:
    return _daily_counts(db, ChatSession.started_at, days)


def chat_weekly(db: Session, weeks: int = 12) -> list[dict]:
    daily = _daily_counts(db, ChatSession.started_at, weeks * 7)
    out = []
    for i in range(0, len(daily), 7):
        chunk = daily[i:i + 7]
        out.append({"week_of": chunk[0]["date"],
                    "count": sum(d["count"] for d in chunk)})
    return out


def chat_monthly(db: Session, days: int = 365) -> list[dict]:
    daily = _daily_counts(db, ChatSession.started_at, days)
    months: dict[str, int] = {}
    for d in daily:
        months[d["date"][:7]] = months.get(d["date"][:7], 0) + d["count"]
    return [{"month": m, "count": c} for m, c in sorted(months.items())]


# ── Applications breakdowns ──────────────────────────────────────────────
def _apply_scope(q, campus, date_from, date_to):
    if campus:
        q = q.filter(Application.campus == campus)
    if date_from:
        q = q.filter(Application.submitted_at >= f"{date_from} 00:00:00")
    if date_to:
        q = q.filter(Application.submitted_at <= f"{date_to} 23:59:59")
    return q


def by_course(db: Session, limit: int = 10, campus: str | None = None,
              date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    # Uses the catalog course_name stored on the application.
    q = db.query(Application.course_name, func.count(Application.id).label("c")) \
        .filter(Application.course_name != "")
    q = _apply_scope(q, campus, date_from, date_to)
    rows = q.group_by(Application.course_name).order_by(desc("c")).limit(limit).all()
    return [{"course": r[0], "count": r[1]} for r in rows]


def by_department(db: Session, campus: str | None = None,
                  date_from: str | None = None, date_to: str | None = None) -> list[dict]:
    # Group by programme category (Intermediate / Short Courses).
    q = db.query(Application.programme_category, func.count(Application.id).label("c")) \
        .filter(Application.programme_category != "")
    q = _apply_scope(q, campus, date_from, date_to)
    rows = q.group_by(Application.programme_category).order_by(desc("c")).all()
    return [{"department": r[0], "count": r[1]} for r in rows]


# ── Chat analytics ───────────────────────────────────────────────────────
STOPWORDS = {"the", "a", "an", "is", "are", "of", "to", "in", "for", "and",
             "or", "what", "how", "i", "you", "me", "my", "can", "do", "about",
             "please", "tell", "kya", "hai", "ka", "ki", "ke", "mein", "se"}

TOPIC_KEYWORDS = {
    "Fees & payments": ["fee", "fees", "payment", "installment", "cost", "price", "scholarship"],
    "Admissions": ["admission", "apply", "application", "form", "merit", "eligib", "requirement", "deadline", "last date"],
    "Courses & programs": ["course", "program", "fsc", "ics", "icom", "i.com", "fa ", "subject", "pre-medical", "pre-engineering"],
    "Campuses & location": ["campus", "location", "address", "walton", "queen", "darogwala", "bhagbanpura", "branch"],
    "Timings & schedule": ["timing", "time", "schedule", "class", "shift", "morning", "evening"],
    "Contact & staff": ["contact", "phone", "number", "call", "email", "principal", "teacher"],
    "Results & exams": ["result", "exam", "test", "marks", "paper", "board"],
    "Hostel & transport": ["hostel", "transport", "bus", "van"],
}


def top_questions(db: Session, days: int = 30, limit: int = 10) -> list[dict]:
    rows = (
        db.query(ChatMessage.content)
        .filter(ChatMessage.role == "user",
                ChatMessage.created_at >= days_ago(days))
        .order_by(desc(ChatMessage.created_at)).limit(5000).all()
    )
    counter = Counter()
    for (content,) in rows:
        key = re.sub(r"\s+", " ", content.strip().lower())[:120]
        if len(key) >= 3:
            counter[key] += 1
    return [{"question": q, "count": c} for q, c in counter.most_common(limit)]


def topics(db: Session, days: int = 30) -> list[dict]:
    rows = (
        db.query(ChatMessage.content)
        .filter(ChatMessage.role == "user",
                ChatMessage.created_at >= days_ago(days))
        .order_by(desc(ChatMessage.created_at)).limit(5000).all()
    )
    counter = Counter()
    for (content,) in rows:
        text = content.lower()
        for topic, keywords in TOPIC_KEYWORDS.items():
            if any(k in text for k in keywords):
                counter[topic] += 1
    return [{"topic": t, "count": c} for t, c in counter.most_common()]


def peak_hours(db: Session, days: int = 30) -> list[dict]:
    rows = (
        db.query(ChatMessage.created_at)
        .filter(ChatMessage.created_at >= days_ago(days)).all()
    )
    counter = Counter(r[0].hour for r in rows if r[0])
    return [{"hour": h, "count": counter.get(h, 0)} for h in range(24)]


def chat_stats(db: Session) -> dict:
    avg_response = db.query(func.avg(ChatMessage.response_time_ms)).filter(
        ChatMessage.role == "assistant",
        ChatMessage.response_time_ms.isnot(None)).scalar()
    avg_length = db.query(func.avg(ChatSession.message_count)).scalar()

    week_ago = days_ago(7)
    active = db.query(func.count(func.distinct(ChatSession.visitor_id))).filter(
        ChatSession.last_activity_at >= week_ago).scalar()

    returning = (
        db.query(ChatSession.visitor_id)
        .group_by(ChatSession.visitor_id)
        .having(func.count(ChatSession.id) > 1).count()
    )
    return {
        "avg_response_time_ms": round(avg_response or 0),
        "avg_conversation_length": round(avg_length or 0, 1),
        "active_users_7d": active or 0,
        "returning_users": returning or 0,
    }


# ── Leads analytics (Module 3) ───────────────────────────────────────────
def lead_stats(db: Session, campus: str | None = None,
               date_from: str | None = None, date_to: str | None = None) -> dict:
    from app.models import Lead, LeadStatus  # local import to avoid cycles

    def _base():
        q = db.query(Lead)
        if campus:
            q = q.filter(Lead.campus == campus)
        if date_from:
            q = q.filter(Lead.created_at >= f"{date_from} 00:00:00")
        if date_to:
            q = q.filter(Lead.created_at <= f"{date_to} 23:59:59")
        return q

    leads = _base()
    total = leads.count()
    converted = _base().filter(Lead.status.in_(
        [LeadStatus.CONVERTED, LeadStatus.APPLICATION_SUBMITTED])).count()

    by_source = (_base()
        .with_entities(Lead.source, func.count(Lead.id))
        .group_by(Lead.source).order_by(desc(func.count(Lead.id))).all())
    by_status = (_base()
        .with_entities(Lead.status, func.count(Lead.id))
        .group_by(Lead.status).all())
    top_courses = (_base()
        .with_entities(Lead.interested_course, func.count(Lead.id).label("c"))
        .filter(Lead.interested_course != "")
        .group_by(Lead.interested_course).order_by(desc("c")).limit(8).all())
    ranged = bool(date_from or date_to)
    return {
        "total": total,
        "today": total if ranged else _base().filter(Lead.created_at >= start_of_today()).count(),
        "this_week": total if ranged else _base().filter(Lead.created_at >= days_ago(7)).count(),
        "this_month": total if ranged else _base().filter(Lead.created_at >= start_of_month()).count(),
        "conversion_rate": round(converted / total * 100, 1) if total else 0.0,
        "by_source": [{"source": s or "other", "count": c} for s, c in by_source],
        "by_status": [{"status": s, "count": c} for s, c in by_status],
        "top_courses": [{"course": n, "count": c} for n, c in top_courses],
        "growth": _daily_counts(db, Lead.created_at, 30, model=Lead, campus=campus),
    }


# ── Unanswered / problem questions (Module 2) ────────────────────────────
_UNANSWERED_MARKERS = [
    "i don't know", "i do not know", "i'm not sure", "i am not sure",
    "sorry", "apolog", "don't have that information",
    "do not have that information", "contact the office",
    "contact the admissions", "cannot help with", "can't help with",
    "maloom nahi", "maazrat",
]


def unanswered_questions(db: Session, days: int = 30, limit: int = 10) -> list[dict]:
    """User questions whose AI reply looked like a non-answer."""
    rows = (
        db.query(ChatMessage.session_id, ChatMessage.role, ChatMessage.content,
                 ChatMessage.created_at)
        .filter(ChatMessage.created_at >= days_ago(days))
        .order_by(ChatMessage.session_id, ChatMessage.created_at)
        .limit(10000).all()
    )
    counter = Counter()
    prev_user: dict[str, str] = {}
    for session_id, role, content, _ in rows:
        if role == "user":
            prev_user[session_id] = content
        elif role == "assistant":
            text = (content or "").lower()
            if any(m in text for m in _UNANSWERED_MARKERS):
                q = prev_user.get(session_id, "").strip()
                if len(q) >= 3:
                    key = re.sub(r"\s+", " ", q.lower())[:120]
                    counter[key] += 1
    return [{"question": q, "count": c} for q, c in counter.most_common(limit)]


# ── Fee & eligibility dashboard (redesign) ───────────────────────────────
def fee_overview(db: Session, campus: str | None = None,
                 date_from: str | None = None,
                 date_to: str | None = None) -> dict:
    from app.models import (Application, EligibilityStatus, Installment,
                            InstallmentStatus, PaymentAllocation, PaymentStatus)
    from sqlalchemy import and_, or_
    today = now().date()

    def _apps():
        q = db.query(Application)
        if campus:
            q = q.filter(Application.campus == campus)
        if date_from:
            q = q.filter(Application.submitted_at >= f"{date_from} 00:00:00")
        if date_to:
            q = q.filter(Application.submitted_at <= f"{date_to} 23:59:59")
        return q

    def _insts():
        q = db.query(Installment)
        if campus or date_from or date_to:
            q = q.join(Application, Installment.application_id == Application.id)
            if campus:
                q = q.filter(Application.campus == campus)
            if date_from:
                q = q.filter(Application.submitted_at >= f"{date_from} 00:00:00")
            if date_to:
                q = q.filter(Application.submitted_at <= f"{date_to} 23:59:59")
        return q

    def _count(status):
        return _apps().filter(Application.payment_status == status).count()

    total_fee = _apps().with_entities(
        func.coalesce(func.sum(Application.total_fee), 0)).scalar() or 0

    alloc_q = db.query(PaymentAllocation)
    if campus:
        alloc_q = alloc_q.filter(
            or_(
                PaymentAllocation.campus == campus,
                and_(
                    or_(PaymentAllocation.campus == "", PaymentAllocation.campus.is_(None)),
                    PaymentAllocation.application_id.in_(
                        db.query(Application.id).filter(
                            or_(
                                and_(Application.transferred_from == campus, Application.transferred_from != ""),
                                and_(or_(Application.transferred_from == "", Application.transferred_from.is_(None)), Application.campus == campus)
                            )
                        )
                    )
                )
            )
        )
    if date_from:
        alloc_q = alloc_q.filter(PaymentAllocation.created_at >= f"{date_from} 00:00:00")
    if date_to:
        alloc_q = alloc_q.filter(PaymentAllocation.created_at <= f"{date_to} 23:59:59")

    collected = alloc_q.with_entities(
        func.coalesce(func.sum(PaymentAllocation.amount), 0)).scalar() or 0
    outstanding = max(0.0, round(total_fee - collected, 2))

    installments_due = _insts().filter(
        Installment.status == InstallmentStatus.PENDING).count()
    overdue = _insts().filter(
        Installment.status == InstallmentStatus.PENDING,
        Installment.due_date.isnot(None),
        Installment.due_date < today).count()

    return {
        "total_fee": round(total_fee, 2),
        "collected": round(collected, 2),
        "net_transfer_adjustment": 0.0,
        "collected_with_transfers": round(collected, 2),
        "outstanding": outstanding,
        "collection_rate": round(collected / total_fee * 100, 1) if total_fee else 0.0,
        "fully_paid": _count(PaymentStatus.FULLY_PAID),
        "partially_paid": _count(PaymentStatus.PARTIALLY_PAID),
        "unpaid": _count(PaymentStatus.UNPAID),
        "eligible": _apps().filter(
            Application.eligibility_status == EligibilityStatus.ELIGIBLE).count(),
        "not_eligible": _apps().filter(
            Application.eligibility_status == EligibilityStatus.NOT_ELIGIBLE).count(),
        "installments_due": installments_due,
        "installments_overdue": overdue,
    }


# ── Lead source / marketing analytics (Module 21) ────────────────────────
def lead_source_stats(db: Session, campus: str | None = None,
                      date_from: str | None = None,
                      date_to: str | None = None) -> dict:
    from app.catalog import LEAD_SOURCES
    from app.models import Application
    q = db.query(Application.lead_source, func.count(Application.id))
    if campus:
        q = q.filter(Application.campus == campus)
    if date_from:
        q = q.filter(Application.submitted_at >= f"{date_from} 00:00:00")
    if date_to:
        q = q.filter(Application.submitted_at <= f"{date_to} 23:59:59")
    rows = q.group_by(Application.lead_source).all()
    counts = {src or "Unknown": n for src, n in rows}
    total = sum(counts.values())
    ordered = []
    for src in LEAD_SOURCES:
        ordered.append({"source": src, "count": counts.get(src, 0),
                        "percent": round(counts.get(src, 0) / total * 100, 1)
                        if total else 0.0})
    for src, n in counts.items():
        if src not in LEAD_SOURCES and src != "":
            ordered.append({"source": src, "count": n,
                            "percent": round(n / total * 100, 1) if total else 0.0})
    return {"total": total, "by_source": ordered}
