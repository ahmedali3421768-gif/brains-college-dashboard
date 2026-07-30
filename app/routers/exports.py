"""Exports — professional applications, expense, chat and analytics reports."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import admin_campus, any_staff, managers
from app.database import get_db
from app.models import ActivityLog, Admin, Application, ChatSession, Lead, Student
from app.services import analytics_service as stats
from app.services.export_service import to_csv, to_pdf, to_xlsx
from app.utils.timeutil import now

router = APIRouter(prefix="/api/admin/exports", tags=["exports"])

MEDIA = {
    "csv": ("text/csv", "csv"),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "pdf": ("application/pdf", "pdf"),
}


def _build(fmt: str, headers: list, rows: list, title: str) -> Response:
    if fmt not in MEDIA:
        raise HTTPException(status_code=400, detail="format must be csv, xlsx or pdf")
    if fmt == "csv":
        body = to_csv(headers, rows)
    elif fmt == "xlsx":
        body = to_xlsx(headers, rows, title)
    else:
        body = to_pdf(headers, rows, title)
    media_type, ext = MEDIA[fmt]
    filename = f"{title.lower().replace(' ', '_')}_{now():%Y%m%d_%H%M}.{ext}"
    return Response(body, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/applications")
def export_applications(format: str = Query("csv"),
                        date: str | None = None,
                        q: str | None = None,
                        status: str | None = None,
                        payment_status: str | None = None,
                        admission_status: str | None = None,
                        campus: str | None = None,
                        course: str | None = None,
                        lead_source: str | None = None,
                        date_from: str | None = None,
                        date_to: str | None = None,
                        admin: Admin = Depends(any_staff),
                        db: Session = Depends(get_db)):
    """Two-section workbook.

    RECOVERIES  — students who actually took money on the selected date, with the
                  amount shown under the stage(s) it settled that day.
    ADMISSIONS  — applications created on the selected date, with the payment
                  plan (amount + due date) agreed at admission.

    Every filter from the Applications page is honoured, so the export always
    matches what the user is looking at.
    """
    from datetime import date as _date, datetime as _dt

    from app.models import PaymentAllocation
    from app.services import report_service
    from app.services.schedule_service import (STAGES, STAGE_KEYS, stage_of)

    sel: _date | None = None
    if date:
        try:
            sel = _date.fromisoformat(date[:10])
        except ValueError:
            raise HTTPException(status_code=422,
                                detail="Invalid date. Use YYYY-MM-DD.")

    # ── The Applications-page filters, applied identically ──
    query = (db.query(Application).join(Student)
             .options(joinedload(Application.student),
                      joinedload(Application.course),
                      joinedload(Application.installments),
                      joinedload(Application.payments))
             .order_by(desc(Application.submitted_at)))
    _campus = admin_campus(admin)
    if _campus:
        query = query.filter(Application.campus == _campus)
    elif campus:
        query = query.filter(Application.campus == campus)
    if status:
        query = query.filter(Application.application_status == status)
    if payment_status:
        query = query.filter(Application.payment_status == payment_status)
    if admission_status:
        query = query.filter(Application.admission_status == admission_status)
    if course:
        query = query.filter(Application.course_name == course)
    if lead_source:
        query = query.filter(Application.lead_source == lead_source)
    if date_from:
        query = query.filter(Application.submitted_at >= date_from)
    if date_to:
        query = query.filter(Application.submitted_at <= f"{date_to} 23:59:59")
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Student.full_name.ilike(like),
                                 Student.roll_number.ilike(like),
                                 Student.phone.ilike(like),
                                 Application.application_no.ilike(like)))
    apps = query.limit(10000).all()
    app_ids = [a.id for a in apps]
    by_id = {a.id: a for a in apps}

    def _paid(a):
        return round(sum(i.paid_amount or 0 for i in a.installments), 2)

    def _sched(a):
        """stage → (amount, due_date) for this student."""
        out = {}
        for i in a.installments:
            k = stage_of(i)
            if k:
                out[k] = (i.amount or 0, i.due_date)
        return out

    # ── SECTION 1: RECOVERIES — money actually taken on the selected date ──
    rec_headers = ["Receipt Number", "Roll Number", "Student Name", "Total Fee",
                   "Pending Fee", "Admission Fee", "1st Installment",
                   "2nd Installment", "Test Session"]
    rec_rows = []
    exp_campus = _campus or campus
    aq = db.query(PaymentAllocation)
    if exp_campus:
        from sqlalchemy import and_, or_
        aq = aq.filter(
            or_(
                PaymentAllocation.campus == exp_campus,
                and_(
                    or_(PaymentAllocation.campus == "", PaymentAllocation.campus.is_(None)),
                    PaymentAllocation.application_id.in_(
                        db.query(Application.id).filter(
                            or_(
                                and_(Application.transferred_from == exp_campus, Application.transferred_from != ""),
                                and_(or_(Application.transferred_from == "", Application.transferred_from.is_(None)), Application.campus == exp_campus)
                            )
                        )
                    )
                )
            )
        )
    if sel is not None:
        aq = aq.filter(PaymentAllocation.paid_on == sel)
    allocs = aq.all()

    # one row per student per receipt, stage columns filled only where money
    # landed that day
    buckets: dict[tuple, dict] = {}
    for al in allocs:
        key = (al.application_id, al.receipt_number or "")
        b = buckets.get(key)
        if b is None:
            b = buckets[key] = {k: 0.0 for k in STAGE_KEYS}
            b["_receipt"] = al.receipt_number or ""
            b["_app"] = al.application_id
        if al.stage in b:
            b[al.stage] = round(b[al.stage] + (al.amount or 0), 2)

    for (app_id, _rc), b in sorted(buckets.items()):
        a = by_id.get(app_id) or db.get(Application, app_id)
        if not a:
            continue
        total = getattr(a, "total_fee", 0) or 0
        rec_rows.append([
            b["_receipt"],
            a.student.roll_number if a.student else "",
            a.student.full_name if a.student else "",
            total,
            max(0.0, round(total - _paid(a), 2)),
            b["admission_fee"] or "",
            b["first_installment"] or "",
            b["second_installment"] or "",
            b["test_session"] or "",
        ])

    # ── SECTION 2: ADMISSIONS — applications created on the selected date ──
    adm_headers = ["Receipt Number", "Roll Number", "Student Name",
                   "Admission Fee Amount", "Admission Fee Due Date",
                   "First Installment Amount", "First Installment Due Date",
                   "Second Installment Amount", "Second Installment Due Date",
                   "Test Session Amount", "Test Session Due Date"]
    adm_rows = []
    for a in apps:
        if sel is not None:
            created = a.submitted_at.date() if a.submitted_at else None
            if created != sel:
                continue
        sc = _sched(a)
        first_receipt = ""
        for p in sorted(a.payments or [], key=lambda x: x.id):
            if p.receipt_number:
                first_receipt = p.receipt_number
                break
        row = [first_receipt,
               a.student.roll_number if a.student else "",
               a.student.full_name if a.student else ""]
        for key, _label in STAGES:
            amt, due = sc.get(key, (0, None))
            row.append(amt or "")
            row.append(report_service._fmt_date(due) if due else "")
        adm_rows.append(row)

    when = report_service._fmt_date(sel) if sel else "All dates"
    meta = {
        "Report Generated": report_service.stamp(),
        "Generated By": admin.name,
        "Campus": _campus or campus or "All campuses",
        "Report Date": when,
    }
    summary = [
        ("Report Date", when),
        ("Recoveries (payments taken)", len(rec_rows)),
        ("Recovered Amount", round(sum(
            sum(v for v in r[5:9] if isinstance(v, (int, float)))
            for r in rec_rows), 2)),
        ("Admissions (created)", len(adm_rows)),
    ]
    sections = [
        {"title": "RECOVERIES", "headers": rec_headers, "rows": rec_rows,
         "money_cols": [3, 4, 5, 6, 7, 8]},
        {"title": "ADMISSIONS", "headers": adm_headers, "rows": adm_rows,
         "money_cols": [3, 5, 7, 9]},
    ]

    body, media, ext = report_service.build(
        format, "Applications Report", meta, summary, sections)
    db.add(ActivityLog(admin_id=admin.id, action="export",
                       detail=f"Exported {len(rec_rows)} recoveries and "
                              f"{len(adm_rows)} admissions as {format}"))
    db.commit()
    fname = f"applications-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}"
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/expenses")
def export_expenses(format: str = Query("csv"),
                    date_from: str | None = None, date_to: str | None = None,
                    category: str | None = None, campus: str | None = None,
                    payment_method: str | None = None,
                    recorded_by: str | None = None,
                    admin: Admin = Depends(managers),
                    db: Session = Depends(get_db)):
    """Accounting-quality expense report (Admin / Super Admin only)."""
    from app.models import Expense
    from app.services import report_service

    q = db.query(Expense).order_by(desc(Expense.purchase_date), desc(Expense.id))
    _campus = admin_campus(admin)
    if _campus:
        q = q.filter(Expense.campus == _campus)
    elif campus:
        q = q.filter(Expense.campus == campus)
    if date_from:
        q = q.filter(Expense.purchase_date >= date_from)
    if date_to:
        q = q.filter(Expense.purchase_date <= date_to)
    if category:
        q = q.filter(Expense.category == category)
    if payment_method:
        q = q.filter(Expense.payment_method == payment_method)
    if recorded_by:
        q = q.filter(Expense.recorded_by_name.ilike(f"%{recorded_by}%"))
    rows_db = q.limit(20000).all()

    headers = ["Expense ID", "Expense Date", "Category", "Title", "Description",
               "Amount", "Payment Method", "Vendor / Paid To", "Campus",
               "Recorded By", "Created Date", "Remarks"]
    rows = [[
        e.id, report_service._fmt_date(e.purchase_date), e.category or "",
        e.title or "", (e.description or "")[:300], e.amount or 0,
        (getattr(e, "payment_method", "") or "cash").title(),
        e.vendor or "", e.campus or "", e.recorded_by_name or "",
        report_service._fmt_date(e.created_at), (e.remarks or "")[:300],
    ] for e in rows_db]

    def _sum_method(m):
        return sum(e.amount or 0 for e in rows_db
                   if (getattr(e, "payment_method", "") or "cash").lower() == m)

    total = sum(e.amount or 0 for e in rows_db)
    rng = (f"{date_from or '—'} to {date_to or '—'}"
           if (date_from or date_to) else "All time")
    meta = {
        "Report Generated": report_service.stamp(),
        "Generated By": admin.name,
        "Date Range": rng,
        "Campus": _campus or campus or "All campuses",
    }
    summary = [
        ("Total Number of Expenses", len(rows_db)),
        ("Total Expense Amount", total),
        ("Total Cash Expenses", _sum_method("cash")),
        ("Total Bank Transfer Expenses", _sum_method("bank")),
        ("Total JazzCash / EasyPaisa Expenses", _sum_method("jazzcash")),
        ("Date Range", rng),
    ]
    sections = [{"title": "EXPENSES", "headers": headers, "rows": rows,
                 "money_cols": [5], "total_col": 5}]

    body, media, ext = report_service.build(
        format, "Expense Report", meta, summary, sections)
    db.add(ActivityLog(admin_id=admin.id, action="export",
                       detail=f"Exported {len(rows_db)} expenses as {format}"))
    db.commit()
    fname = f"expenses-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}"
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/chats")
def export_chats(format: str = Query("csv"), admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    sessions = (db.query(ChatSession)
                .order_by(desc(ChatSession.started_at)).limit(10000).all())
    headers = ["Session ID", "Title", "Visitor", "Phone", "Linked Student ID",
               "Messages", "Device", "Browser", "OS", "IP", "Country",
               "Started", "Last Activity"]
    rows = [[s.id, s.title, s.visitor_name, s.visitor_phone, s.student_id,
             s.message_count, s.device, s.browser, s.os, s.ip_address,
             s.country, str(s.started_at), str(s.last_activity_at)]
            for s in sessions]
    db.add(ActivityLog(admin_id=admin.id, action="export",
                       detail=f"Exported {len(rows)} chat sessions as {format}"))
    db.commit()
    return _build(format, headers, rows, "Chat Sessions")


@router.get("/leads")
def export_leads(format: str = Query("csv"), admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    _lq = db.query(Lead).order_by(desc(Lead.created_at))
    _campus = admin_campus(admin)
    if _campus:
        _lq = _lq.filter(Lead.campus == _campus)
    leads = _lq.limit(10000).all()
    headers = ["ID", "Name", "Phone", "Campus", "Status", "Created At"]
    rows = [[l.id, l.name, l.phone, l.campus, l.status, str(l.created_at)]
            for l in leads]
    return _build(format, headers, rows, "Leads")


@router.get("/analytics")
def export_analytics(format: str = Query("csv"),
                     admin: Admin = Depends(any_staff),
                     db: Session = Depends(get_db)):
    o = stats.overview(db)
    c = stats.chat_stats(db)
    headers = ["Metric", "Value"]
    rows = [[k.replace("_", " ").title(), v] for k, v in {**o, **c}.items()]
    return _build(format, headers, rows, "Analytics Summary")


@router.get("/challans")
def export_challans(format: str = Query("csv"),
                    admin: Admin = Depends(any_staff),
                    db: Session = Depends(get_db)):
    from app.models import Challan
    from app.schemas.serialize import challan_to_dict
    _campus = admin_campus(admin)
    _cq = db.query(Challan).order_by(Challan.created_at.desc())
    if _campus:
        _cq = _cq.join(Application, Challan.application_id == Application.id).filter(
            Application.campus == _campus)
    rows_q = _cq.limit(10000).all()
    headers = ["Challan No", "Application No", "Student", "CNIC", "Phone",
               "Course", "Department", "Amount", "Due Date", "Method",
               "Status", "Created"]
    rows = []
    for c in rows_q:
        d = challan_to_dict(c)
        rows.append([d["challan_no"], d["application_no"], d["student_name"],
                     d["cnic"], d["phone"], d["course"], d["department"],
                     d["amount"], d["due_date"], d["payment_method"],
                     d["status"], str(d["created_at"])])
    db.add(ActivityLog(admin_id=admin.id, action="export",
                       detail=f"Exported {len(rows)} challans as {format}"))
    db.commit()
    return _build(format, headers, rows, "Challans")
