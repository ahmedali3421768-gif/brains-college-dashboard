"""PUBLIC endpoints used by the existing website chatbot widget.

/api/chat and /api/lead keep the exact request/response shapes the deployed
widget already uses — the chatbot behaviour is unchanged. The only difference:
every message is now saved to the database (Part 5) and pushed live to the
admin dashboard (Part 6), and leads go to the DB instead of Google Sheets.
"""
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from groq import Groq
from sqlalchemy.orm import Session

from app.config import VALID_CAMPUSES, settings
from app.database import get_db
from app.models import ChatSession, Lead
from app.schemas.chat import ChatRequest, ChatResponse, LeadRequest, LeadResponse
from app.services import chat_logger
from app.services.notification_service import notify
from app.services.ws_manager import manager
from app.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["public"])

# Keep using the college's existing system prompt file untouched.
try:
    from prompt import SYSTEM_PROMPT
except ImportError:  # pragma: no cover — only if prompt.py is missing
    SYSTEM_PROMPT = "You are the helpful admissions assistant of Brains College."
    logger.warning("prompt.py not found — using a fallback system prompt.")

_groq_client: Groq | None = None


def get_groq_client() -> Groq:
    global _groq_client
    if _groq_client is None:
        if not settings.GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set in .env file")
        _groq_client = Groq(api_key=settings.GROQ_API_KEY)
    return _groq_client


@router.post("/api/chat", response_model=ChatResponse,
             dependencies=[Depends(rate_limit("chat", limit=20, window_seconds=60))])
async def chat(payload: ChatRequest, request: Request, db: Session = Depends(get_db)):
    try:
        groq_client = get_groq_client()
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # ── conversation logging (before the AI call, so nothing is lost) ──
    session, created = chat_logger.get_or_create_session(
        db, payload.session_id, request, page_url=payload.page_url
    )
    user_messages = [m for m in payload.messages if m.role == "user"]
    if user_messages:
        chat_logger.log_message(db, session, "user", user_messages[-1].content)

    if created:
        await notify(db, "chat_started", "New chatbot conversation",
                     f"A visitor started chatting on {session.device} "
                     f"({session.browser}).", related_id=session.id)
        await manager.broadcast("chat_session_started", {
            "session_id": session.id, "device": session.device,
            "browser": session.browser, "started_at": session.started_at,
        })
    if user_messages:
        await manager.broadcast("chat_message", {
            "session_id": session.id, "role": "user",
            "content": user_messages[-1].content,
            "title": session.title, "created_at": session.last_activity_at,
        })

    # ── AI call — identical behaviour to the previous deployment ──
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += [{"role": m.role, "content": m.content} for m in payload.messages]

    try:
        started = time.perf_counter()
        response = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        reply = response.choices[0].message.content
    except Exception:
        logger.exception("Chat API error")
        raise HTTPException(
            status_code=500,
            detail="The assistant is temporarily unavailable. Please try again.",
        )

    chat_logger.log_message(db, session, "assistant", reply,
                            response_time_ms=elapsed_ms)
    await manager.broadcast("chat_message", {
        "session_id": session.id, "role": "assistant", "content": reply,
        "title": session.title, "response_time_ms": elapsed_ms,
        "created_at": session.last_activity_at,
    })

    return ChatResponse(reply=reply, success=True, session_id=session.id)


@router.post("/api/lead", response_model=LeadResponse,
             dependencies=[Depends(rate_limit("lead", limit=10, window_seconds=60))])
async def submit_lead(payload: LeadRequest, db: Session = Depends(get_db)):
    """Save a lead (name, phone, campus) — now to the database, not Sheets."""
    name = payload.name.strip()
    phone = payload.phone.strip()
    campus = payload.campus.strip()

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if len(name) < 2:
        raise HTTPException(status_code=400,
                            detail="Name must be at least 2 characters")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number is required")
    if not campus:
        raise HTTPException(status_code=400, detail="Campus selection is required")
    if campus not in VALID_CAMPUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid campus. Choose from: {', '.join(VALID_CAMPUSES)}",
        )

    lead = Lead(name=name, phone=phone, campus=campus,
                session_id=payload.session_id,
                email=(payload.email or "").strip() or None,
                city=(payload.city or "").strip(),
                interested_course=(payload.interested_course or "").strip(),
                interested_department=(payload.interested_department or "").strip(),
                source=(payload.source or "chatbot").strip() or "chatbot")
    db.add(lead)
    # tag the originating chat session with the campus so conversations
    # split by campus for the campus admins.
    if payload.session_id:
        _sess = db.get(ChatSession, payload.session_id)
        if _sess is not None and not (_sess.campus or ""):
            _sess.campus = campus
    db.commit()
    db.refresh(lead)

    # Remember who this chat visitor is (enables admission ↔ chat linking)
    if payload.session_id:
        from app.models import ChatSession
        session = db.get(ChatSession, payload.session_id)
        if session:
            chat_logger.attach_contact(db, session, name, phone)

    # related_id = phone (not the row id) so an identical repeated enquiry
    # from the same person is merged instead of notifying again (Module 4)
    await notify(db, "new_lead", "New lead received",
                 f"{name} ({phone}) is interested in the {campus} campus.",
                 related_id=phone, campus=campus)
    await manager.broadcast("new_lead", {
        "id": lead.id, "name": name, "phone": phone, "campus": campus,
        "created_at": lead.created_at,
    })
    logger.info("Lead saved: %s | %s | %s", name, phone, campus)
    return LeadResponse(success=True, message="Thank you! We'll contact you soon.")
