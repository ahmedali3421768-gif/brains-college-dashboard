"""Chat monitoring (Parts 5 & 7) — session list and ChatGPT-style viewer."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import any_staff, managers, super_only, admin_campus
from app.database import get_db
from app.models import Admin, ChatMessage, ChatSession
from app.schemas.serialize import session_to_dict
from app.utils.pagination import paginate

router = APIRouter(prefix="/api/admin/chats", tags=["chats"])


@router.get("")
def list_sessions(
    q: str | None = None,
    device: str | None = None,
    linked: bool | None = None,   # only sessions linked to a student
    status: str | None = None,    # active | archived
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    admin: Admin = Depends(any_staff),
    db: Session = Depends(get_db),
):
    query = (db.query(ChatSession)
             .options(joinedload(ChatSession.student))
             .order_by(desc(ChatSession.last_activity_at)))
    _campus = admin_campus(admin)
    if _campus:
        query = query.filter(ChatSession.campus == _campus)
    if q:
        like = f"%{q.strip()}%"
        message_match = (db.query(ChatMessage.session_id)
                         .filter(ChatMessage.content.ilike(like)).subquery())
        query = query.filter(or_(
            ChatSession.title.ilike(like),
            ChatSession.visitor_name.ilike(like),
            ChatSession.visitor_phone.ilike(like),
            ChatSession.ip_address.ilike(like),
            ChatSession.id.in_(message_match.select()),
        ))
    if device:
        query = query.filter(ChatSession.device == device)
    if status:
        query = query.filter(ChatSession.status == status)
    if linked is True:
        query = query.filter(ChatSession.student_id.isnot(None))
    if date_from:
        query = query.filter(ChatSession.started_at >= f"{date_from} 00:00:00")
    if date_to:
        query = query.filter(ChatSession.started_at <= f"{date_to} 23:59:59")

    result = paginate(query, page, page_size)
    result["items"] = [session_to_dict(s) for s in result["items"]]
    return result


@router.get("/{session_id}")
def get_session(session_id: str, admin: Admin = Depends(any_staff),
                db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _c = admin_campus(admin)
    if _c and (getattr(session, "campus", "") or "") != _c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return session_to_dict(session, include_messages=True)


@router.delete("/{session_id}")
def delete_session(session_id: str, admin: Admin = Depends(super_only),
                   db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _c = admin_campus(admin)
    if _c and (getattr(session, "campus", "") or "") != _c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"success": True, "message": "Conversation deleted"}


@router.patch("/{session_id}/archive")
def archive_session(session_id: str, admin: Admin = Depends(managers),
                    db: Session = Depends(get_db)):
    """Toggle a conversation between active and archived (Module 2)."""
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _c = admin_campus(admin)
    if _c and (getattr(session, "campus", "") or "") != _c:
        raise HTTPException(status_code=404, detail="Conversation not found")
    session.status = "active" if session.status == "archived" else "archived"
    db.commit()
    return {"success": True, "status": session.status}


@router.get("/{session_id}/pdf")
def conversation_pdf(session_id: str, admin: Admin = Depends(any_staff),
                     db: Session = Depends(get_db)):
    """Download the full conversation as a printable PDF (Module 2)."""
    from io import BytesIO

    from fastapi.responses import Response
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _c = admin_campus(admin)
    if _c and (getattr(session, "campus", "") or "") != _c:
        raise HTTPException(status_code=404, detail="Conversation not found")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm,
                            rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm,
                            title=f"Conversation {session.id}")
    brand = colors.HexColor("#123D33")
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=15,
                       textColor=brand, spaceAfter=2)
    meta = ParagraphStyle("m", fontName="Helvetica", fontSize=8.5,
                          textColor=colors.HexColor("#5B6B64"))
    user_style = ParagraphStyle("u", fontName="Helvetica-Bold", fontSize=9.5,
                                textColor=colors.white, leading=13)
    bot_style = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5,
                               textColor=colors.black, leading=13)
    time_style = ParagraphStyle("t", fontName="Helvetica", fontSize=7,
                                textColor=colors.HexColor("#8A968F"))

    def _esc(t):
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [Paragraph(_esc(session.title or "Untitled conversation"), h),
             Paragraph(
                 f"Visitor: {_esc(session.visitor_name) or 'Anonymous'} · "
                 f"Phone: {_esc(session.visitor_phone) or '—'} · "
                 f"Device: {_esc(session.device)} / {_esc(session.browser)} / "
                 f"{_esc(session.os)} · IP: {_esc(session.ip_address)} · "
                 f"Started: {session.started_at} · "
                 f"Messages: {session.message_count}", meta),
             Spacer(1, 8)]

    for m in session.messages:
        who = "Visitor" if m.role == "user" else "AI Assistant"
        style = user_style if m.role == "user" else bot_style
        bg = brand if m.role == "user" else colors.HexColor("#F5F3EC")
        rt = (f" · replied in {m.response_time_ms/1000:.1f}s"
              if m.response_time_ms else "")
        cell = [Paragraph(f"<b>{who}</b><br/>{_esc(m.content)}", style),
                Paragraph(f"{m.created_at}{rt}", time_style)]
        t = Table([[cell]], colWidths=[178 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDD8CA")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story += [t, Spacer(1, 5)]

    doc.build(story)
    return Response(
        buf.getvalue(), media_type="application/pdf",
        headers={"Content-Disposition":
                 f'attachment; filename="conversation-{session.id[:8]}.pdf"'})
