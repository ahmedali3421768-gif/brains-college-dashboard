"""Expense Management — record, list, search, filter, report and export.

Budget Allocation has been removed; this is now a clean expense tracker."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import any_staff, managers, admin_campus
from app.database import get_db
from app.models import Admin, Expense
from app.utils.pagination import paginate
from app.utils.timeutil import days_ago, now, start_of_month

router = APIRouter(prefix="/api/admin", tags=["expenses"])


# ── Expenses ─────────────────────────────────────────────────────────────
class ExpenseIn(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=2000)
    category: str = Field(default="", max_length=80)
    purchase_date: str | None = None  # YYYY-MM-DD
    vendor: str = Field(default="", max_length=150)
    amount: float = Field(gt=0)
    payment_method: str = Field(default="cash", max_length=30)
    remarks: str = Field(default="", max_length=1000)


def _pdate(v):
    if not v:
        return now().date()
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="purchase_date must be YYYY-MM-DD")


@router.get("/expenses")
def list_expenses(q: str | None = None, category: str | None = None,
                  date_from: str | None = None, date_to: str | None = None,
                  payment_method: str | None = None, campus: str | None = None,
                  recorded_by: str | None = None,
                  page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                  admin: Admin = Depends(any_staff), db: Session = Depends(get_db)):
    query = db.query(Expense).order_by(desc(Expense.purchase_date),
                                       desc(Expense.id))
    _campus = admin_campus(admin)
    if _campus:
        query = query.filter(Expense.campus == _campus)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Expense.title.ilike(like),
                                 Expense.vendor.ilike(like),
                                 Expense.description.ilike(like)))
    if category:
        query = query.filter(Expense.category == category)
    if date_from:
        query = query.filter(Expense.purchase_date >= date_from)
    if date_to:
        query = query.filter(Expense.purchase_date <= date_to)
    if payment_method:
        query = query.filter(Expense.payment_method == payment_method)
    if campus and not _campus:          # super admin may filter by campus
        query = query.filter(Expense.campus == campus)
    if recorded_by:
        query = query.filter(Expense.recorded_by_name.ilike(f"%{recorded_by}%"))
    result = paginate(query, page, page_size)
    result["items"] = [_expense_dict(e) for e in result["items"]]
    return result


def _expense_dict(e) -> dict:
    return {"id": e.id, "title": e.title, "description": e.description,
            "category": e.category, "campus": e.campus,
            "purchase_date": str(e.purchase_date) if e.purchase_date else None,
            "vendor": e.vendor, "amount": e.amount,
            "payment_method": getattr(e, "payment_method", "") or "cash",
            "remarks": e.remarks,
            "recorded_by": e.recorded_by_name, "created_at": e.created_at}


@router.post("/expenses", status_code=201)
def create_expense(payload: ExpenseIn, admin: Admin = Depends(managers),
                   db: Session = Depends(get_db)):
    e = Expense(title=payload.title.strip(), description=payload.description,
                category=payload.category.strip(),
                campus=admin_campus(admin) or "",
                purchase_date=_pdate(payload.purchase_date),
                vendor=payload.vendor.strip(), amount=payload.amount,
                payment_method=(payload.payment_method or "cash").strip(),
                remarks=payload.remarks, recorded_by_name=admin.name)
    db.add(e)
    db.commit()
    db.refresh(e)
    return _expense_dict(e)


@router.patch("/expenses/{expense_id}")
def update_expense(expense_id: int, payload: ExpenseIn,
                   admin: Admin = Depends(managers), db: Session = Depends(get_db)):
    e = db.get(Expense, expense_id)
    if not e:
        raise HTTPException(status_code=404, detail="Expense not found")
    _c = admin_campus(admin)
    if _c and (e.campus or "") != _c:
        raise HTTPException(status_code=404, detail="Expense not found")
    e.title = payload.title.strip()
    e.description = payload.description
    e.category = payload.category.strip()
    e.purchase_date = _pdate(payload.purchase_date)
    e.vendor = payload.vendor.strip()
    e.amount = payload.amount
    e.payment_method = (payload.payment_method or "cash").strip()
    e.remarks = payload.remarks
    db.commit()
    return _expense_dict(e)


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, admin: Admin = Depends(managers),
                   db: Session = Depends(get_db)):
    e = db.get(Expense, expense_id)
    if not e:
        raise HTTPException(status_code=404, detail="Expense not found")
    _c = admin_campus(admin)
    if _c and (e.campus or "") != _c:
        raise HTTPException(status_code=404, detail="Expense not found")
    db.delete(e)
    db.commit()
    return {"success": True}


# ── Expense dashboard ────────────────────────────────────────────────────
@router.get("/expenses-dashboard")
def expense_dashboard(date_from: str | None = None, date_to: str | None = None,
                      admin: Admin = Depends(any_staff),
                      db: Session = Depends(get_db)):
    """Expense dashboard. Optional date_from / date_to (YYYY-MM-DD) restrict
    the expense figures to that window. Budget allocation has been removed —
    this is now a pure expense tracker."""
    _campus = admin_campus(admin)

    def _exp_q():
        q = db.query(Expense)
        if _campus:
            q = q.filter(Expense.campus == _campus)
        if date_from:
            q = q.filter(Expense.purchase_date >= date_from)
        if date_to:
            q = q.filter(Expense.purchase_date <= date_to)
        return q

    total_expenses = _exp_q().with_entities(
        func.coalesce(func.sum(Expense.amount), 0)).scalar() or 0

    mq = db.query(func.coalesce(func.sum(Expense.amount), 0)).filter(
        Expense.created_at >= start_of_month())
    if _campus:
        mq = mq.filter(Expense.campus == _campus)
    monthly = mq.scalar() or 0

    recent = _exp_q().order_by(desc(Expense.created_at)).limit(8).all()

    # by-category within the same window/campus
    cat_rows = (_exp_q().with_entities(
        Expense.category, func.coalesce(func.sum(Expense.amount), 0))
        .group_by(Expense.category).all())
    by_category = sorted(
        [{"category": c or "Uncategorized", "amount": round(float(v), 2)}
         for c, v in cat_rows],
        key=lambda x: x["amount"], reverse=True)

    trend = _monthly_trend(db, _campus, date_from, date_to)

    return {
        "total_expenses": round(total_expenses, 2),
        "monthly_expenses": round(monthly, 2),
        "expense_count": _exp_q().count(),
        "recent": [_expense_dict(e) for e in recent],
        "by_category": by_category,
        "trend": trend,
        "date_from": date_from, "date_to": date_to,
    }


def _monthly_trend(db: Session, campus: str | None = None,
                   date_from: str | None = None,
                   date_to: str | None = None) -> list[dict]:
    q = db.query(func.strftime("%Y-%m", Expense.created_at).label("m"),
                 func.coalesce(func.sum(Expense.amount), 0))
    if campus:
        q = q.filter(Expense.campus == campus)
    if date_from:
        q = q.filter(Expense.purchase_date >= date_from)
    if date_to:
        q = q.filter(Expense.purchase_date <= date_to)
    rows = q.group_by("m").order_by("m").all()
    # SQLite strftime; for Postgres fall back to to_char handled by ORM dialect
    return [{"month": m, "amount": round(float(v), 2)} for m, v in rows][-6:]
