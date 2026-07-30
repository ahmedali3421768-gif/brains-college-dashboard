"""Brains College — Admission Management & Chatbot Monitoring Portal.

The public chatbot endpoints (/api/chat, /api/lead) keep the exact contracts
of the original deployment, so the existing website widget works unchanged.
Google Sheets has been fully removed — the database is the permanent storage
and /admin is the control panel.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import money_transfers  # inter-campus money transfer
from app.routers import (
    analytics, applications, auth, chats_admin, exports, expenses, fees,
    meta, notifications, payments, public_chat, reception, ws, referral,)
from app.seed import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
static_dir = BASE_DIR / "static"
static_dir.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    import os

    from app.config import settings as _s
    os.makedirs(os.path.join(_s.UPLOADS_DIR, "challans"), exist_ok=True)
    os.makedirs(os.path.join(_s.UPLOADS_DIR, "receipts"), exist_ok=True)
    init_db()
    from app.services.reminder_service import reminder_loop
    reminder_task = asyncio.create_task(reminder_loop())
    logger.info("✅ Database ready (tables created / seeded).")
    if settings.GROQ_API_KEY:
        logger.info("✅ Groq API key detected — chatbot enabled.")
    else:
        logger.warning("⚠️  GROQ_API_KEY not set — /api/chat will return 503.")
    if settings.SECRET_KEY.startswith("insecure-dev-key"):
        logger.warning("⚠️  SECRET_KEY is the insecure default. Set it in .env!")
    yield
    reminder_task.cancel()


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routers ─────────────────────────────────────────────────────────
app.include_router(public_chat.router)     # /api/chat, /api/lead (unchanged)
app.include_router(auth.router)            # /api/auth/*
app.include_router(applications.router)    # /api/applications, /api/admin/applications
app.include_router(chats_admin.router)     # /api/admin/chats
app.include_router(analytics.router)       # /api/admin/analytics
app.include_router(exports.router)         # /api/admin/exports
app.include_router(notifications.router)   # /api/admin/notifications
app.include_router(meta.router)            # form options, leads, search, health
app.include_router(payments.router)        # challans, receipts, portal, verification
app.include_router(fees.router)            # installments, fee recording, due-date
app.include_router(money_transfers.router) # inter-campus money transfer
app.include_router(expenses.router)        # expense & budget management
app.include_router(reception.router)       # /api/reception/* (read-only fee lookup)
app.include_router(referral.router)        # /api/referral/* + /referral (referral portal)
app.include_router(ws.router)              # /ws/admin


# ── Pages ───────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
async def root():
    """Serve the existing website / chatbot page exactly as before."""
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return HTMLResponse(
        "<h1>Brains College API is running.</h1>"
        "<p>Place your website in <code>static/index.html</code>. "
        "The admin dashboard is at <a href='/admin'>/admin</a>.</p>"
    )


@app.get("/apply", include_in_schema=False)
async def apply_page():
    f = static_dir / "apply.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="apply.html not found")
    return FileResponse(str(f))


@app.get("/portal", include_in_schema=False)
async def portal_page():
    f = static_dir / "portal.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="portal.html not found")
    return FileResponse(str(f))


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
async def admin_page():
    f = static_dir / "admin" / "index.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Admin dashboard not found")
    return FileResponse(str(f))


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page():
    f = static_dir / "admin" / "login.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Login page not found")
    return FileResponse(str(f))


@app.get("/reception", include_in_schema=False)
@app.get("/reception/", include_in_schema=False)
async def reception_page():
    f = static_dir / "reception.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Reception page not found")
    return FileResponse(str(f))


app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
