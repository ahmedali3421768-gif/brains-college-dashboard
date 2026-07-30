"""Persist every chatbot conversation to the database, grouped into sessions."""
import uuid
from datetime import timedelta

from fastapi import Request
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ChatMessage, ChatSession, Student
from app.utils.request_meta import get_client_ip, parse_user_agent, visitor_fingerprint
from app.utils.timeutil import now


def get_or_create_session(
    db: Session, session_id: str | None, request: Request,
    page_url: str | None = None,
) -> tuple[ChatSession, bool]:
    """Return (session, created). If the widget sent a session_id we reuse it;
    otherwise we reuse the visitor's most recent session if it was active in the
    last SESSION_REUSE_MINUTES, so old widgets without session support still
    produce coherent conversations."""
    ip = get_client_ip(request)
    ua = request.headers.get("user-agent", "")
    fingerprint = visitor_fingerprint(ip, ua)

    if session_id:
        existing = db.get(ChatSession, session_id)
        if existing:
            return existing, False

    cutoff = now() - timedelta(minutes=settings.SESSION_REUSE_MINUTES)
    recent = (
        db.query(ChatSession)
        .filter(ChatSession.visitor_id == fingerprint,
                ChatSession.last_activity_at >= cutoff)
        .order_by(desc(ChatSession.last_activity_at))
        .first()
    )
    if recent:
        return recent, False

    meta = parse_user_agent(ua)
    session = ChatSession(
        id=uuid.uuid4().hex,
        visitor_id=fingerprint,
        ip_address=ip,
        browser=meta["browser"],
        os=meta["os"],
        device=meta["device"],
        country=request.headers.get("cf-ipcountry")
        or request.headers.get("x-vercel-ip-country"),
        page_url=(page_url or request.headers.get("referer") or "")[:500] or None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, True


def log_message(
    db: Session, session: ChatSession, role: str, content: str,
    response_time_ms: int | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        session_id=session.id, role=role, content=content,
        response_time_ms=response_time_ms,
    )
    db.add(msg)
    session.message_count = (session.message_count or 0) + 1
    session.last_activity_at = now()
    if role == "user" and session.title in (None, "", "New conversation"):
        session.title = content.strip()[:140] or "New conversation"
    db.commit()
    db.refresh(msg)
    return msg


def attach_contact(db: Session, session: ChatSession, name: str, phone: str):
    """Called when a lead form is submitted inside the chat — remembers who the
    visitor is and links the session to an existing student if the phone matches."""
    session.visitor_name = name
    session.visitor_phone = phone
    student = db.query(Student).filter(Student.phone == phone).first()
    if student:
        session.student_id = student.id
    db.commit()


def link_sessions_to_student(db: Session, student: Student):
    """When an application arrives, adopt any chat sessions that share the
    student's phone number (Part 9: admission + chat integration)."""
    db.query(ChatSession).filter(
        ChatSession.visitor_phone == student.phone,
        ChatSession.student_id.is_(None),
    ).update({ChatSession.student_id: student.id}, synchronize_session=False)
    db.commit()
