"""Real-time channel for the admin dashboard (Part 6).

The dashboard connects to  ws(s)://host/ws/admin?token=<JWT>  and receives
JSON events: chat_message, chat_session_started, new_application,
application_updated, new_lead, notification.
"""
import logging

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.auth.security import decode_token
from app.database import SessionLocal
from app.models import Admin
from app.services.ws_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


def _authenticate(token: str) -> bool:
    payload = decode_token(token)
    if not payload:
        return False
    db = SessionLocal()
    try:
        admin = db.get(Admin, int(payload.get("sub", 0)))
        return bool(admin and admin.is_active)
    except (TypeError, ValueError):
        return False
    finally:
        db.close()


@router.websocket("/ws/admin")
async def admin_ws(websocket: WebSocket, token: str = Query(default="")):
    if not _authenticate(token):
        # 4401 = custom "unauthorized" close code
        await websocket.close(code=4401)
        return

    await manager.connect(websocket)
    logger.info("Admin dashboard connected (%d live)", len(manager.active))
    try:
        while True:
            # We don't expect messages from the dashboard; this keeps the
            # connection alive and lets us notice disconnects.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
        logger.info("Admin dashboard disconnected (%d live)", len(manager.active))
