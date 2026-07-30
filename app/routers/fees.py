"""Fee management for the admission office (all-new, minimum clicks).

GET    /api/admin/applications/{id}/fees          full fee summary + installments
PATCH  /api/admin/applications/{id}/fee           set total fee / category
POST   /api/admin/applications/{id}/installments  add installment
PATCH  /api/admin/installments/{iid}              edit amount / extend due date
DELETE /api/admin/installments/{iid}              remove an unpaid installment
POST   /api/admin/installments/{iid}/pay          mark paid (records payment)
POST   /api/admin/installments/{iid}/unpay        undo a mistaken payment
POST   /api/admin/applications/{id}/payments      record a received amount
                                                  (auto-fills oldest installments)
Every change re-runs the fee engine, so statuses, eligibility, challan and
dashboards update instantly and never disagree.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import any_staff, managers, admin_campus
from app.database import get_db
from app.models import Admin, Application, Installment, InstallmentStatus
from app.services import fee_service
from app.services.notification_service import notify
from app.utils.timeutil import now

router = APIRouter(prefix="/api/admin", tags=["fees"])


@router.get("/receipts/check")
def check_receipt_number(receipt_number: str,
                         admin: Admin = Depends(managers),
                         db: Session = Depends(get_db)):
    """Real-time uniqueness check used by the payment forms as the admin types.
    Returns {available: bool, message: str}."""
    from app.services import receipt_service
    rn = receipt_service.normalize(receipt_number)
    if not rn:
        return {"available": False, "message": "Receipt Number is required."}
    taken = receipt_service.is_taken(db, rn)
    return {
        "available": not taken,
        "message": (f'Receipt Number "{rn}" already exists. '
                    "Please enter a unique receipt number." if taken
                    else "Receipt number is available."),
    }


@router.get("/installments-due")
def installments_due(date: str | None = None,
                     q: str | None = None,
                     course: str | None = None,
                     campus: str | None = None,
                     status: str | None = None,
                     admin: Admin = Depends(any_staff),
                     db: Session = Depends(get_db)):
    """All students whose CURRENT (next unpaid) installment is due on the
    selected date. Campus-scoped like everything else."""
    from datetime import date as _date
    from sqlalchemy.orm import joinedload
    from app.services import fee_service, receipt_service

    target = None
    if date:
        try:
            target = _date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date.")

    query = (db.query(Application)
             .join(Application.installments)
             .options(joinedload(Application.student),
                      joinedload(Application.installments),
                      joinedload(Application.payments))
             .filter(Installment.status == InstallmentStatus.PENDING))

    scope = admin_campus(admin)
    if scope:
        query = query.filter(Application.campus == scope)
    elif campus:
        query = query.filter(Application.campus == campus)
    if target is not None:
        query = query.filter(Installment.due_date == target)
    if course:
        query = query.filter(Application.course_name == course)

    rows = []
    seen = set()
    for app_obj in query.all():
        if app_obj.id in seen:
            continue
        seen.add(app_obj.id)
        s = app_obj.student
        pend = sorted([i for i in app_obj.installments
                       if i.status == InstallmentStatus.PENDING],
                      key=lambda i: (i.number, i.id))
        if not pend:
            continue
        # Which pending installment does this row represent?
        #  • with a date filter → the pending installment due on that date
        #  • without one       → the current (oldest pending) installment
        if target is not None:
            match = next((i for i in pend if i.due_date == target), None)
            if match is None:
                continue
            cur = match
        else:
            cur = pend[0]
        summ = fee_service.summary(app_obj)
        pay_status = summ.get("payment_status", "unpaid")
        if status and pay_status != status:
            continue
        if q:
            ql = q.strip().lower()
            if ql not in (s.full_name if s else "").lower() and \
               ql not in (s.roll_number if s else "").lower():
                continue
        rows.append({
            "id": app_obj.id,
            "roll_number": s.roll_number if s else "",
            "student_name": s.full_name if s else "",
            "phone": s.phone if s else "",
            "guardian_phone": (getattr(s, "guardian_phone", "") or "") if s else "",
            "course": (getattr(app_obj, "course_name", "") or
                       (app_obj.course.name if app_obj.course else "")) or "—",
            "campus": app_obj.campus or "",
            "total_fee": summ.get("total_fee", 0),
            "paid_fee": summ.get("paid", 0),
            "pending_fee": summ.get("remaining", 0),
            "current_installment": cur.label or f"Installment {cur.number}",
            "installment_amount": cur.amount or 0,
            "due_date": str(cur.due_date) if cur.due_date else "",
            "payment_status": pay_status,
            "student_status": app_obj.application_status,
            "latest_receipt": receipt_service.latest_for_application(db, app_obj.id),
        })
    rows.sort(key=lambda r: (r["due_date"] or "", r["roll_number"]))
    return {"items": rows, "total": len(rows),
            "date": date or "", "campus": scope or campus or "All campuses"}



def _who(a) -> str:
    s = a.student
    return f"{s.full_name} ({s.roll_number})" if s else "Student"


def _app(db: Session, app_id: int, admin: Admin = None) -> Application:
    a = db.get(Application, app_id)
    if not a:
        raise HTTPException(status_code=404, detail="Application not found")
    if admin is not None:
        campus = admin_campus(admin)
        if campus and (a.campus or "") != campus:
            raise HTTPException(status_code=404, detail="Application not found")
    return a


def _inst(db: Session, inst_id: int, admin: Admin = None) -> Installment:
    i = db.get(Installment, inst_id)
    if not i:
        raise HTTPException(status_code=404, detail="Installment not found")
    if admin is not None:
        campus = admin_campus(admin)
        app_obj = i.application
        if campus and app_obj and (app_obj.campus or "") != campus:
            raise HTTPException(status_code=404, detail="Installment not found")
    return i


def _parse_date(v: str):
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise HTTPException(status_code=400,
                            detail="Date must be YYYY-MM-DD")


@router.get("/applications/{app_id}/fees")
def fees(app_id: int, admin: Admin = Depends(any_staff),
         db: Session = Depends(get_db)):
    return fee_service.summary(_app(db, app_id, admin))


class FeeUpdate(BaseModel):
    total_fee: float | None = Field(default=None, ge=0)
    fee_category: str | None = Field(default=None, max_length=60)


@router.patch("/applications/{app_id}/fee")
async def update_fee(app_id: int, payload: FeeUpdate,
               admin: Admin = Depends(managers),
               db: Session = Depends(get_db)):
    a = _app(db, app_id, admin)
    if payload.total_fee is not None:
        a.total_fee = payload.total_fee
    if payload.fee_category is not None:
        a.fee_category = payload.fee_category.strip() or "Admission Fee"
    db.commit()
    fee_service.recompute(db, a)
    await notify(db, "system", "Fee updated",
                 f"{_who(a)} — total fee set to Rs {a.total_fee:,.0f} by "
                 f"{admin.name} at {a.campus or '—'}.",
                 related_id=a.id, priority="normal", category="admission",
                 campus=a.campus or "")
    return fee_service.summary(a)


class InstallmentCreate(BaseModel):
    amount: float = Field(gt=0)
    due_date: str
    label: str | None = Field(default=None, max_length=60)


@router.post("/applications/{app_id}/installments", status_code=201)
async def add_installment(app_id: int, payload: InstallmentCreate,
                    admin: Admin = Depends(managers),
                    db: Session = Depends(get_db)):
    a = _app(db, app_id, admin)
    number = max((i.number for i in a.installments), default=0) + 1
    inst = Installment(application_id=a.id, number=number,
                       label=(payload.label or f"Installment {number}").strip(),
                       amount=payload.amount,
                       due_date=_parse_date(payload.due_date))
    db.add(inst)
    db.commit()
    fee_service.recompute(db, a)
    await notify(db, "system", "Installment added",
                 f"{_who(a)} — {inst.label} of Rs {inst.amount:,.0f} "
                 f"(due {inst.due_date}) added by {admin.name} at "
                 f"{a.campus or '—'}.",
                 related_id=a.id, priority="normal", category="admission",
                 campus=a.campus or "")
    return fee_service.summary(a)


class InstallmentUpdate(BaseModel):
    amount: float | None = Field(default=None, gt=0)
    due_date: str | None = None   # ← due-date extension happens here
    label: str | None = Field(default=None, max_length=60)


@router.patch("/installments/{inst_id}")
def edit_installment(inst_id: int, payload: InstallmentUpdate,
                     admin: Admin = Depends(managers),
                     db: Session = Depends(get_db)):
    i = _inst(db, inst_id, admin)
    if payload.amount is not None:
        if i.status == InstallmentStatus.PAID:
            raise HTTPException(status_code=400,
                                detail="A paid installment's amount "
                                       "cannot be changed.")
        i.amount = payload.amount
    if payload.due_date is not None:
        i.due_date = _parse_date(payload.due_date)
    if payload.label is not None:
        i.label = payload.label.strip() or i.label
    db.commit()
    fee_service.recompute(db, i.application)
    return fee_service.summary(i.application)


@router.delete("/installments/{inst_id}")
def delete_installment(inst_id: int, admin: Admin = Depends(managers),
                       db: Session = Depends(get_db)):
    i = _inst(db, inst_id, admin)
    if i.status == InstallmentStatus.PAID or (i.paid_amount or 0) > 0:
        raise HTTPException(status_code=400,
                            detail="Paid installments cannot be deleted.")
    a = i.application
    db.delete(i)
    db.commit()
    fee_service.recompute(db, a)
    return fee_service.summary(a)


class PayBody(BaseModel):
    method: str = Field(default="cash", pattern=r"^(cash|jazzcash|bank|other)$")
    amount: float | None = Field(default=None, gt=0)  # default: full amount
    receipt_number: str = Field(min_length=1, max_length=60)


@router.post("/installments/{inst_id}/pay")
async def pay_installment(inst_id: int, payload: PayBody,
                          admin: Admin = Depends(managers),
                          db: Session = Depends(get_db)):
    i = _inst(db, inst_id, admin)
    if i.status == InstallmentStatus.PAID:
        raise HTTPException(status_code=400, detail="Already paid.")
    from app.services import receipt_service
    receipt_no = receipt_service.ensure_unique(
        db, payload.receipt_number, exclude_installment_id=i.id)
    a = i.application
    _pay_amt = payload.amount if payload.amount else i.amount
    fee_service.ensure_not_overdue(a, i)
    fee_service.ensure_within_total(a, _pay_amt, exclude_installment_id=i.id)
    i.paid_amount = _pay_amt
    i.status = InstallmentStatus.PAID if i.paid_amount >= i.amount \
        else InstallmentStatus.PENDING
    i.paid_at = now()
    i.paid_method = payload.method
    i.receipt_number = receipt_no
    i.recorded_by_name = admin.name
    # log which schedule stage this money landed on, and on what day
    fee_service.record_allocation(db, a, i, _pay_amt, payload.method,
                                  receipt_no, admin.name, campus=a.campus or "")
    # permanent payment record with the receipt number
    from app.models import Payment
    db.add(Payment(application_id=a.id, amount=i.paid_amount,
                   method=payload.method,
                   receipt_number=receipt_no,
                   reference=f"Installment #{i.number}",
                   campus=a.campus or "",
                   status="verified", verified_by=admin.id, verified_at=now()))
    db.commit()
    fee_service.recompute(db, a)
    student = a.student
    await notify(db, "payment_verified", "Installment paid",
                 f"{student.full_name if student else 'Student'} paid "
                 f"Rs {i.paid_amount:,.0f} ({payload.method}) — installment "
                 f"#{i.number}. Receipt {receipt_no}.",
                 related_id=a.id, priority="normal", category="payment",
                 campus=a.campus or "")
    return fee_service.summary(a)


@router.post("/installments/{inst_id}/unpay")
def unpay_installment(inst_id: int, admin: Admin = Depends(managers),
                      db: Session = Depends(get_db)):
    i = _inst(db, inst_id, admin)
    i.paid_amount = 0
    i.status = InstallmentStatus.PENDING
    i.paid_at = None
    i.paid_method = ""
    i.recorded_by_name = admin.name
    db.commit()
    fee_service.recompute(db, i.application)
    return fee_service.summary(i.application)


class PaymentRecord(BaseModel):
    amount: float = Field(gt=0)
    method: str = Field(default="cash", pattern=r"^(cash|jazzcash|bank|other)$")
    receipt_number: str = Field(min_length=1, max_length=60)


@router.post("/applications/{app_id}/payments")
async def record_payment(app_id: int, payload: PaymentRecord,
                         admin: Admin = Depends(managers),
                         db: Session = Depends(get_db)):
    """Record any received amount — auto-applies to oldest unpaid installments.
    A Receipt Number is required and stored permanently."""
    a = _app(db, app_id, admin)
    if not a.installments:
        raise HTTPException(status_code=400,
                            detail="Create an installment first.")
    from app.services import receipt_service
    receipt = receipt_service.ensure_unique(db, payload.receipt_number)
    # A payment can't be taken once its due date has gone by — the admin must
    # extend the schedule first.
    fee_service.ensure_not_overdue(a)
    # Admission fee + installments can never exceed the total course fee.
    fee_service.ensure_within_total(a, payload.amount)
    touched = fee_service.apply_payment(db, a, payload.amount, payload.method,
                                        admin.name, receipt_number=receipt,
                                        campus=a.campus or "")
    from app.models import Payment
    db.add(Payment(application_id=a.id, amount=payload.amount,
                   method=payload.method, receipt_number=receipt,
                   reference="Payment", campus=a.campus or "", status="verified",
                   verified_by=admin.id, verified_at=now()))
    db.commit()
    student = a.student
    await notify(db, "payment_verified", "Payment recorded",
                 f"Rs {payload.amount:,.0f} ({payload.method}) recorded for "
                 f"{student.full_name if student else 'student'} "
                 f"(Roll {student.roll_number if student else '—'}) by "
                 f"{admin.name}. Receipt {receipt}.",
                 related_id=a.id, category="payment", campus=a.campus or "")
    return fee_service.summary(a)


@router.get("/applications/{app_id}/receipt", include_in_schema=False)
def download_receipt(app_id: int, admin: Admin = Depends(any_staff),
                     db: Session = Depends(get_db)):
    """Professional printable payment receipt (Module 15). Print with Ctrl+P."""
    from fastapi.responses import HTMLResponse

    from app.config import settings
    from app.services.fee_service import summary
    a = _app(db, app_id, admin)
    s = a.student
    fee = summary(a)
    import html as _h

    def e(v):
        return _h.escape(str(v if v is not None else "—"))

    # latest receipt number from payments/installments
    receipt_no = "—"
    for p in sorted(a.payments, key=lambda x: x.id, reverse=True):
        if getattr(p, "receipt_number", ""):
            receipt_no = p.receipt_number
            break

    # ── Payments Received: every recorded payment with ITS OWN receipt number
    def _pay_label(p):
        ref = (getattr(p, "reference", "") or "").strip()
        if ref:
            return ref                       # e.g. "Installment #2"
        return "Admission Fee"

    pay_rows = "".join(
        f"<tr><td>{e(_pay_label(p))}</td>"
        f"<td>Rs {(p.amount or 0):,.0f}</td>"
        f"<td><b>{e(getattr(p, 'receipt_number', '') or '—')}</b></td>"
        f"<td>{e((p.method or '').title())}</td>"
        f"<td>{e(p.created_at.strftime('%d-%m-%Y') if p.created_at else '—')}</td></tr>"
        for p in sorted(a.payments, key=lambda x: x.id)
        if getattr(p, "receipt_number", ""))

    inst_rows = "".join(
        f"<tr><td>#{i['number']} {e(i['label'])}</td>"
        f"<td>Rs {i['amount']:,.0f}</td>"
        f"<td>{e(i['due_date'])}</td>"
        f"<td>Rs {i['paid_amount']:,.0f}</td>"
        f"<td>{e(i['status'])}</td>"
        f"<td>{e(i.get('receipt_number') or '—')}</td></tr>"
        for i in fee["installments"])

    pstatus = fee["payment_status"].replace("_", " ").upper()
    pcls = {"UNPAID": "#a5281c", "PARTIALLY PAID": "#8a5a00",
            "FULLY PAID": "#1f6b3f"}.get(pstatus, "#333")

    return HTMLResponse(f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Receipt — {e(s.roll_number if s else '')}</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#f4f5f7;color:#2a2f2d;padding:24px}}
  .sheet{{max-width:760px;margin:0 auto;background:#fff;border-radius:16px;
    overflow:hidden;box-shadow:0 8px 34px rgba(184,29,36,.13)}}
  .band{{background:linear-gradient(120deg,#b81d24 0%,#9a1620 100%);
    color:#fff;padding:26px 40px;display:flex;align-items:center;gap:16px;position:relative}}
  .band::after{{content:"";position:absolute;right:-40px;top:-40px;width:180px;height:180px;
    background:rgba(255,255,255,.07);border-radius:50%}}
  .band img{{height:58px;position:relative;z-index:1}}
  .band .fb{{width:56px;height:56px;border-radius:14px;background:#fff;color:#b81d24;
    font-weight:800;font-size:28px;display:grid;place-items:center;position:relative;z-index:1;
    box-shadow:0 4px 12px rgba(0,0,0,.18)}}
  .band h1{{font-size:23px;font-weight:800;letter-spacing:.2px;position:relative;z-index:1}}
  .band p{{font-size:12px;color:rgba(255,255,255,.85);margin-top:2px;position:relative;z-index:1}}
  .rc{{margin-left:auto;text-align:right;position:relative;z-index:1}}
  .rc small{{font-size:10.5px;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.8)}}
  .rc b{{display:block;font-size:20px;font-weight:800;color:#fff;margin-top:2px}}
  .rc span{{font-size:11.5px;color:rgba(255,255,255,.8)}}
  .body{{padding:28px 40px 34px}}
  h2{{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:#b81d24;
    font-weight:800;margin:22px 0 10px;padding-bottom:6px;border-bottom:2px solid #f3d9db;
    display:flex;align-items:center;gap:8px}}
  h2::before{{content:"";width:9px;height:9px;border-radius:2px;background:#b81d24}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px 24px;font-size:13.5px}}
  .grid div{{padding:3px 0}} .grid b{{color:#8a9089;font-weight:600}}
  table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:6px;
    border-radius:9px;overflow:hidden;box-shadow:0 1px 0 #eee}}
  th,td{{text-align:left;padding:9px 11px;border-bottom:1px solid #f0f0f0}}
  th{{background:#fdeceD;background:#fdecee;text-transform:uppercase;font-size:10.5px;
    letter-spacing:.05em;color:#b81d24;font-weight:800}}
  tbody tr:nth-child(even){{background:#fcfafa}}
  tbody tr:last-child td{{border-bottom:0}}
  .tot{{display:flex;justify-content:flex-end;gap:30px;margin-top:18px;font-size:14px;
    background:#fdf4f4;border-radius:11px;padding:14px 20px}}
  .tot b{{color:#b81d24;font-weight:800}}
  .status{{display:inline-block;padding:5px 16px;border-radius:999px;font-weight:800;
    font-size:12px;color:#fff;background:{pcls};box-shadow:0 2px 8px rgba(0,0,0,.12)}}
  .foot{{margin-top:28px;border-top:1px solid #f0e0e1;padding-top:14px;font-size:11px;
    color:#9a9a9a;text-align:center}}
  .bar{{text-align:center;margin-bottom:18px}}
  .bar button{{font:inherit;font-weight:800;padding:12px 32px;border:0;border-radius:11px;
    background:linear-gradient(120deg,#b81d24,#9a1620);color:#fff;cursor:pointer;
    box-shadow:0 6px 18px rgba(184,29,36,.32);transition:transform .1s,box-shadow .15s;
    display:inline-flex;align-items:center;gap:9px}}
  .bar button:hover{{transform:translateY(-1px);box-shadow:0 9px 24px rgba(184,29,36,.4)}}
  .bar button:active{{transform:translateY(0)}}
  @media print{{body{{background:#fff;padding:0}}.sheet{{box-shadow:none;border-radius:0;max-width:100%}}.bar{{display:none}}
    .band{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}}}
</style></head><body>
<div class="bar"><button onclick="window.print()"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v8H6z"/></svg> Print / Save as PDF</button></div>
<div class="sheet">
  <div class="band">
    <img src="/static/img/logo.png" onerror="this.replaceWith(Object.assign(document.createElement('div'),{{className:'fb',textContent:'B'}}))">
    <div><h1>{e(settings.COLLEGE_NAME)}</h1><p>{e(settings.COLLEGE_ADDRESS)}</p></div>
    <div class="rc"><small>Payment Receipt</small><b>{e(receipt_no)}</b><span>{now().strftime('%d %b %Y')}</span></div>
  </div>
  <div class="body">

  <h2>Student details</h2>
  <div class="grid">
    <div><b>Name:</b> {e(s.full_name if s else '')}</div>
    <div><b>Roll Number:</b> {e(s.roll_number if s else '')}</div>
    <div><b>Programme:</b> {e(a.programme_category)}</div>
    <div><b>Course:</b> {e(a.course_name)}</div>
    <div><b>Guardian Phone:</b> {e(getattr(s, 'guardian_phone', '') or '—') if s else '—'}</div>
    <div><b>Receipt No:</b> {e(receipt_no)}</div>
  </div>

  <h2>Payments received</h2>
  <table><thead><tr><th>Payment</th><th>Amount</th><th>Receipt No</th><th>Method</th><th>Date</th></tr></thead>
  <tbody>{pay_rows or '<tr><td colspan=5>No payments recorded yet</td></tr>'}</tbody></table>

  <h2>Instalment schedule</h2>
  <table><thead><tr><th>Installment</th><th>Amount</th><th>Due</th><th>Paid</th><th>Status</th><th>Receipt</th></tr></thead>
  <tbody>{inst_rows or '<tr><td colspan=6>No installments</td></tr>'}</tbody></table>

  <div class="tot"><span>Total Fee: <b>Rs {fee['total_fee']:,.0f}</b></span>
    <span>Paid: <b>Rs {fee['paid']:,.0f}</b></span>
    <span>Balance: <b>Rs {fee['remaining']:,.0f}</b></span></div>
  <div style="text-align:right;margin-top:10px"><span class="status">{e(pstatus)}</span></div>

  <div class="foot">This is a system-generated receipt from {e(settings.COLLEGE_NAME)}.
  Roll {e(s.roll_number if s else '')} · Generated {now().strftime('%d %b %Y, %I:%M %p')}</div>
  </div>
</div></body></html>""")


# ── Four-stage payment schedule ──────────────────────────────────────────
@router.get("/applications/{app_id}/schedule")
def get_schedule(app_id: int, admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    """The student's payment schedule — Admission Fee, 1st Installment,
    2nd Installment, Test Session. All four rows always exist."""
    from app.services import schedule_service
    a = _app(db, app_id, admin)
    return schedule_service.get_schedule(db, a)


@router.put("/applications/{app_id}/schedule")
async def save_schedule(app_id: int, payload: dict,
                        admin: Admin = Depends(managers),
                        db: Session = Depends(get_db)):
    """Save amounts and due dates for the four stages.

    The combined amount can never exceed the finalised course fee. Every
    due-date change raises its own notification.
    """
    from app.services import schedule_service
    a = _app(db, app_id, admin)
    rows = payload.get("rows") or []
    schedule, changes = schedule_service.save_schedule(db, a, rows, admin.name)

    s = a.student
    who = f"{s.full_name} ({s.roll_number})" if s else "Student"
    for ch in changes:
        await notify(
            db, "system", "Installment due date updated",
            f"{who} — {ch['schedule']} due date changed from {ch['old']} to "
            f"{ch['new']} at {a.campus or '—'}. Changed by {admin.name}.",
            related_id=a.id, priority="normal", category="admission",
            campus=a.campus or "")
    if not changes:
        await notify(
            db, "system", "Payment schedule updated",
            f"{who} — payment schedule updated by {admin.name} at "
            f"{a.campus or '—'}.",
            related_id=a.id, priority="normal", category="admission",
            campus=a.campus or "")
    return schedule
