"""Analytics APIs (Parts 3 & 8) — campus-scoped with optional date range."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import admin_campus, any_staff
from app.database import get_db
from app.models import Admin
from app.services import analytics_service as stats

router = APIRouter(prefix="/api/admin/analytics", tags=["analytics"])


@router.get("/overview")
def overview(date_from: str | None = None, date_to: str | None = None,
             admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    c = admin_campus(admin)
    return stats.overview(db, campus=c, date_from=date_from, date_to=date_to)


@router.get("/applications")
def applications(days: int = Query(30, ge=7, le=365),
                 date_from: str | None = None, date_to: str | None = None,
                 admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    c = admin_campus(admin)
    return {
        "growth": stats.application_growth(db, days, campus=c),
        "by_course": stats.by_course(db, campus=c, date_from=date_from, date_to=date_to),
        "by_department": stats.by_department(db, campus=c, date_from=date_from, date_to=date_to),
    }


@router.get("/chats")
def chats(days: int = Query(30, ge=7, le=365),
          admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    return {
        "daily": stats.chat_daily(db, days),
        "weekly": stats.chat_weekly(db),
        "monthly": stats.chat_monthly(db),
        "peak_hours": stats.peak_hours(db, days),
        "top_questions": stats.top_questions(db, days),
        "unanswered_questions": stats.unanswered_questions(db, days),
        "topics": stats.topics(db, days),
        **stats.chat_stats(db),
    }


@router.get("/leads")
def leads(date_from: str | None = None, date_to: str | None = None,
          admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    c = admin_campus(admin)
    return stats.lead_stats(db, campus=c, date_from=date_from, date_to=date_to)


@router.get("/fees")
def fees_overview(date_from: str | None = None, date_to: str | None = None,
                  admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    c = admin_campus(admin)
    return stats.fee_overview(db, campus=c, date_from=date_from, date_to=date_to)


@router.get("/lead-sources")
def lead_sources(date_from: str | None = None, date_to: str | None = None,
                 admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    c = admin_campus(admin)
    return stats.lead_source_stats(db, campus=c, date_from=date_from, date_to=date_to)
