"""Reminder engine (Module 4) — a scheduled job that runs inside the app.

Every hour it looks for unpaid challans whose due date is 7 / 3 / 1 day(s)
away (or overdue) and creates ONE reminder notification per bucket. The
notification hash includes the bucket, so each reminder can only ever be
sent once per challan; when the challan gets paid the reminders stop.
"""
import asyncio
import logging
from datetime import timedelta

from app.database import SessionLocal
from app.models import Challan, ChallanStatus, NotificationPriority
from app.services.notification_service import notify
from app.utils.timeutil import now

logger = logging.getLogger(__name__)

CHECK_EVERY_SECONDS = 3600  # hourly

BUCKETS = [
    (7, "Fee due in 7 days", NotificationPriority.LOW),
    (3, "Fee due in 3 days", NotificationPriority.NORMAL),
    (1, "Fee due tomorrow", NotificationPriority.HIGH),
    (0, "Fee due today", NotificationPriority.HIGH),
    (-1, "Fee overdue", NotificationPriority.CRITICAL),
]


async def run_fee_reminders_once() -> int:
    """One pass over unpaid challans. Returns how many reminders were sent."""
    sent = 0
    db = SessionLocal()
    try:
        today = now().date()
        open_challans = (
            db.query(Challan)
            .filter(Challan.status.in_([ChallanStatus.UNPAID,
                                        ChallanStatus.REJECTED]),
                    Challan.due_date.isnot(None))
            .all()
        )
        for ch in open_challans:
            days_left = (ch.due_date - today).days
            for bucket_days, label, priority in BUCKETS:
                hit = (days_left == bucket_days if bucket_days >= 0
                       else days_left < 0)
                if not hit:
                    continue
                student = ch.application.student if ch.application else None
                name = student.full_name if student else "Student"
                phone = f" ({student.phone})" if student else ""
                # bucket is part of the message → part of the hash → sent once
                n = await notify(
                    db, "fee_due_reminder", label,
                    f"{label}: challan {ch.challan_no} of Rs {ch.amount:,.0f} "
                    f"for {name}{phone} — due "
                    f"{ch.due_date.strftime('%d %b %Y')}. [{label}]",
                    related_id=ch.application_id, priority=priority,
                    category="deadline",
                    campus=(ch.application.campus if ch.application else "") or "",
                )
                if n:
                    sent += 1
                break  # only the most relevant bucket per pass
    except Exception:  # pragma: no cover
        logger.exception("Fee reminder pass failed")
    finally:
        db.close()
    if sent:
        logger.info("Reminder engine: sent %d fee reminder(s)", sent)
    return sent


async def reminder_loop():
    """Background task started from the app lifespan."""
    await asyncio.sleep(20)  # let the app finish booting
    while True:
        await run_fee_reminders_once()
        await asyncio.sleep(CHECK_EVERY_SECONDS)
