"""Fee payment & challan management (Module 1).

PUBLIC (student portal — no account needed, secured by challan access token
or application-no + CNIC/phone lookup):
    GET  /api/portal/lookup                → application + challans + receipts
    GET  /api/challans/{challan_no}/pdf    → download challan (token required)
    POST /api/challans/{challan_no}/receipt→ upload paid receipt (token required)

ADMIN:
    GET   /api/admin/payments              → verification queue
    GET   /api/admin/challans              → all challans (search/filters)
    GET   /api/admin/challans/{id}/pdf     → download challan
    PATCH /api/admin/challans/{id}/cash    → received/approve/reject/pending
    GET   /api/admin/receipts/{id}/file    → view/download uploaded receipt
    PATCH /api/admin/receipts/{id}         → approve / reject / request re-upload
"""
import logging
from datetime import datetime

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session, joinedload

from app.auth.dependencies import any_staff, managers, admin_campus
from app.database import get_db
from app.models import (
    ActivityLog, Admin, Application, ApplicationStatus, Challan,
    ChallanStatus, Payment, PaymentReceipt, PaymentStatus, ReceiptStatus,
    Student,
)
from app.schemas.serialize import (
    application_to_dict, challan_to_dict, receipt_to_dict,
)
from app.services import challan_service
from app.services.notification_service import notify
from app.services.ws_manager import manager
from app.utils.pagination import paginate
from app.utils.rate_limit import rate_limit
from app.utils.request_meta import get_client_ip
from app.utils.timeutil import now
from app.utils.uploads import save_receipt_upload

logger = logging.getLogger(__name__)
router = APIRouter(tags=["payments"])


def _guard_campus(app_obj, admin):
    """Block a campus admin from acting on another campus's record."""
    campus = admin_campus(admin)
    if campus and app_obj is not None and (app_obj.campus or "") != campus:
        raise HTTPException(status_code=404, detail="Not found")


def _audit(db: Session, action: str, detail: str, admin_id=None):
    db.add(ActivityLog(admin_id=admin_id, action=action, detail=detail[:1900]))
    db.commit()


def _get_challan_by_no(db: Session, challan_no: str, token: str) -> Challan:
    ch = (db.query(Challan)
          .options(joinedload(Challan.application)
                   .joinedload(Application.student))
          .filter(Challan.challan_no == challan_no).first())
    if not ch or ch.access_token != token:
        raise HTTPException(status_code=404, detail="Challan not found")
    return ch


# ═════════════════════════ PUBLIC (student portal) ══════════════════════
@router.get("/api/portal/lookup",
            dependencies=[Depends(rate_limit("portal", limit=15,
                                             window_seconds=60))])
def portal_lookup(application_no: str = Query(min_length=5, max_length=30),
                  cnic_or_phone: str = Query(min_length=4, max_length=25),
                  db: Session = Depends(get_db)):
    """Student self-service: application number + CNIC (or phone) →
    their application status, challans and receipt history."""
    app_obj = (db.query(Application)
               .options(joinedload(Application.student))
               .filter(Application.application_no ==
                       application_no.strip().upper()).first())
    key = cnic_or_phone.strip().replace(" ", "")
    if not app_obj or not app_obj.student:
        raise HTTPException(status_code=404,
                            detail="No application found. Check the details.")
    s = app_obj.student
    ok = (s.cnic and key.replace("-", "") == (s.cnic or "").replace("-", "")) \
        or (s.phone and key.replace("-", "") == (s.phone or "").replace("-", ""))
    if not ok:
        raise HTTPException(status_code=404,
                            detail="No application found. Check the details.")

    challans = (db.query(Challan)
                .filter(Challan.application_id == app_obj.id)
                .order_by(desc(Challan.created_at)).all())
    out = []
    for ch in challans:
        d = challan_to_dict(ch, include_receipts=True)
        d["print_url"] = (f"/challan/{ch.challan_no}"
                          f"?token={ch.access_token}")
        d["upload_url"] = (f"/api/challans/{ch.challan_no}/receipt"
                           f"?token={ch.access_token}")
        d["access_token"] = ch.access_token
        out.append(d)
    return {"application": application_to_dict(app_obj), "challans": out}


@router.get("/challan/{challan_no}", response_class=HTMLResponse,
            include_in_schema=False)
def challan_print_view(challan_no: str, token: str = Query(default=""),
                       request: Request = None,
                       db: Session = Depends(get_db)):
    """Print-friendly POS/thermal receipt — open and press Ctrl+P."""
    ch = _get_challan_by_no(db, challan_no, token)
    _audit(db, "challan_opened",
           f"{ch.challan_no} opened for printing "
           f"(IP {get_client_ip(request) if request else '?'})")
    return HTMLResponse(challan_service.render_print_view(ch))


@router.post("/api/challans/{challan_no}/receipt", status_code=201,
             dependencies=[Depends(rate_limit("receipt", limit=6,
                                              window_seconds=60))])
async def upload_receipt(
    challan_no: str,
    request: Request,
    token: str = Query(default=""),
    payment_method: str = Form("jazzcash"),
    transaction_id: str = Form(""),
    jazzcash_number: str = Form(""),
    payment_date: str = Form(""),
    remarks: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Student uploads their JazzCash payment proof (PDF/JPG/PNG, ≤10 MB)."""
    ch = _get_challan_by_no(db, challan_no, token)

    if ch.status == ChallanStatus.PAID:
        raise HTTPException(
            status_code=400,
            detail="This challan is already paid and verified — the receipt "
                   "cannot be replaced.")
    if payment_method not in ("jazzcash", "cash"):
        raise HTTPException(status_code=400,
                            detail="payment_method must be jazzcash or cash")

    txn = transaction_id.strip() or None
    if txn and db.query(PaymentReceipt).filter(
            PaymentReceipt.transaction_id == txn).first():
        raise HTTPException(
            status_code=409,
            detail="This transaction ID has already been submitted.")

    pdate = None
    if payment_date.strip():
        try:
            pdate = datetime.strptime(payment_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400,
                                detail="payment_date must be YYYY-MM-DD")

    meta = await save_receipt_upload(file)
    receipt = PaymentReceipt(
        challan_id=ch.id, transaction_id=txn,
        jazzcash_number=jazzcash_number.strip()[:25],
        payment_date=pdate, remarks=remarks.strip()[:1000],
        ip_address=get_client_ip(request), **meta,
    )
    db.add(receipt)
    ch.payment_method = payment_method
    ch.status = ChallanStatus.PENDING_VERIFICATION
    db.commit()
    db.refresh(receipt)

    student = ch.application.student if ch.application else None
    await notify(db, "receipt_uploaded", "Payment receipt uploaded",
                 f"{student.full_name if student else 'A student'} uploaded a "
                 f"{payment_method} receipt for challan {ch.challan_no} "
                 f"(Rs {ch.amount:,.0f}).",
                 related_id=ch.application_id, priority="high",
                 category="verification",
                 campus=(ch.application.campus if ch.application else "") or "")
    await manager.broadcast("receipt_uploaded", {
        "challan_no": ch.challan_no, "application_id": ch.application_id,
        "amount": ch.amount, "method": payment_method,
        "campus": (ch.application.campus if ch.application else "") or "",
    })
    _audit(db, "receipt_uploaded",
           f"{ch.challan_no}: receipt #{receipt.id} uploaded "
           f"(txn {txn or '—'}, IP {receipt.ip_address})")
    return {"success": True,
            "message": "Receipt uploaded. The department will verify it soon.",
            "receipt": receipt_to_dict(receipt)}


# ═════════════════════════ ADMIN ════════════════════════════════════════
@router.get("/api/admin/receipts/{receipt_id}/file")
def receipt_file(receipt_id: int, admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    r = db.get(PaymentReceipt, receipt_id)
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found")
    _guard_campus(r.challan.application if r.challan else None, admin)
    import os
    if not os.path.exists(r.file_path):
        raise HTTPException(status_code=404,
                            detail="Receipt file missing from storage")
    _audit(db, "receipt_downloaded",
           f"Receipt #{r.id} viewed by {admin.email}", admin.id)
    return FileResponse(r.file_path, media_type=r.content_type or None,
                        filename=r.original_name or f"receipt-{r.id}")


@router.patch("/api/admin/receipts/{receipt_id}")
async def decide_receipt(receipt_id: int, payload: dict,
                         admin: Admin = Depends(managers),
                         db: Session = Depends(get_db)):
    """Approve / reject / request re-upload for an uploaded receipt."""
    action = (payload.get("action") or "").strip()
    remarks = (payload.get("remarks") or "").strip()[:1000]
    receipt_number = (payload.get("receipt_number") or "").strip()[:60]
    if action not in ("approve", "reject", "request_reupload"):
        raise HTTPException(
            status_code=400,
            detail="action must be approve, reject or request_reupload")
    if action == "approve" and not receipt_number:
        raise HTTPException(
            status_code=422,
            detail="Receipt Number is required before approval.")

    r = (db.query(PaymentReceipt)
         .options(joinedload(PaymentReceipt.challan)
                  .joinedload(Challan.application)
                  .joinedload(Application.student))
         .filter(PaymentReceipt.id == receipt_id).first())
    if not r:
        raise HTTPException(status_code=404, detail="Receipt not found")
    if r.status == ReceiptStatus.APPROVED:
        raise HTTPException(status_code=400,
                            detail="This receipt is already approved — "
                                   "approved receipts cannot be changed.")

    ch = r.challan
    app_obj = ch.application
    _guard_campus(app_obj, admin)
    student = app_obj.student if app_obj else None
    sname = student.full_name if student else "Student"

    # Same rule as cash: the challan is approved against the receipt number the
    # admin already issued for this student. Re-using it links the two; only a
    # different student's number is a conflict.
    already_recorded = False
    if action == "approve":
        from app.services import receipt_service
        receipt_number, already_recorded = receipt_service.resolve_for_challan(
            db, receipt_number, app_obj.id if app_obj else 0)

    r.verified_by = admin.id
    r.verified_by_name = admin.name
    r.verified_at = now()
    r.verification_remarks = remarks

    if action == "approve":
        r.status = ReceiptStatus.APPROVED
        ch.status = ChallanStatus.PAID
        ch.receipt_number = receipt_number
        db.commit()
        if app_obj and not already_recorded:
            from app.services import fee_service
            fee_service.ensure_not_overdue(app_obj)
            fee_service.ensure_within_total(app_obj, ch.amount)
            fee_service.apply_payment(db, app_obj, ch.amount,
                                      ch.payment_method or "jazzcash",
                                      admin.name, receipt_number=receipt_number)
            db.add(Payment(application_id=app_obj.id, amount=ch.amount,
                           method=ch.payment_method or "jazzcash",
                           receipt_number=receipt_number,
                           reference=r.transaction_id or ch.challan_no,
                           status="verified", verified_by=admin.id,
                           verified_at=now()))
            db.commit()
        await notify(db, "payment_verified", "Payment verified",
                     f"Challan {ch.challan_no} (Rs {ch.amount:,.0f}) for "
                     f"{sname} was verified by {admin.name}. The application "
                     f"is now eligible for the admission process.",
                     related_id=ch.application_id, priority="high",
                     category="payment",
                     campus=(ch.application.campus if ch.application else "") or "")
    elif action == "reject":
        r.status = ReceiptStatus.REJECTED
        ch.status = ChallanStatus.REJECTED
        db.commit()
        await notify(db, "receipt_rejected", "Payment receipt rejected",
                     f"The receipt for challan {ch.challan_no} ({sname}) was "
                     f"rejected. {('Reason: ' + remarks) if remarks else ''} "
                     f"The student can upload a new receipt.",
                     related_id=ch.application_id, priority="high",
                     category="payment",
                     campus=(ch.application.campus if ch.application else "") or "")
    else:  # request_reupload
        r.status = ReceiptStatus.REUPLOAD_REQUESTED
        ch.status = ChallanStatus.UNPAID
        db.commit()
        await notify(db, "reupload_requested", "Receipt re-upload requested",
                     f"A clearer receipt was requested for challan "
                     f"{ch.challan_no} ({sname}). "
                     f"{('Note: ' + remarks) if remarks else ''}",
                     related_id=ch.application_id, category="payment",
                     campus=(ch.application.campus if ch.application else "") or "")

    await manager.broadcast("payment_decision", {
        "challan_no": ch.challan_no, "action": action,
        "application_id": ch.application_id,
        "campus": (ch.application.campus if ch.application else "") or "",
    })
    _audit(db, f"receipt_{action}",
           f"{ch.challan_no}: receipt #{r.id} → {action} by {admin.email}. "
           f"{remarks}", admin.id)
    return {"success": True, "receipt": receipt_to_dict(r),
            "challan": challan_to_dict(ch)}


@router.patch("/api/admin/challans/{challan_id}/cash")
async def cash_decision(challan_id: int, payload: dict,
                        admin: Admin = Depends(managers),
                        db: Session = Depends(get_db)):
    """Cash payments: Received / Approve / Reject / Mark Pending."""
    action = (payload.get("action") or "").strip()
    receipt_number = (payload.get("receipt_number") or "").strip()[:60]
    if action not in ("received", "approve", "reject", "pending"):
        raise HTTPException(
            status_code=400,
            detail="action must be received, approve, reject or pending")
    if action == "approve" and not receipt_number:
        raise HTTPException(
            status_code=422,
            detail="Receipt Number is required before approval.")

    ch = (db.query(Challan)
          .options(joinedload(Challan.application)
                   .joinedload(Application.student))
          .filter(Challan.id == challan_id).first())
    if not ch:
        raise HTTPException(status_code=404, detail="Challan not found")
    app_obj = ch.application
    _guard_campus(app_obj, admin)

    # A challan is approved against the receipt number the admin already issued
    # for this student on the admissions page. Re-using that same number here is
    # correct and links the two; only another student's number is a conflict.
    already_recorded = False
    if action == "approve":
        from app.services import receipt_service
        receipt_number, already_recorded = receipt_service.resolve_for_challan(
            db, receipt_number, app_obj.id if app_obj else 0)
    student = app_obj.student if app_obj else None
    sname = student.full_name if student else "Student"

    ch.payment_method = ch.payment_method or "cash"
    if action == "received":
        ch.status = ChallanStatus.PENDING_VERIFICATION
    elif action == "approve":
        ch.status = ChallanStatus.PAID
        ch.receipt_number = receipt_number
        if app_obj and not already_recorded:
            # brand-new receipt → record the payment now
            from app.services import fee_service
            fee_service.ensure_not_overdue(app_obj)
            fee_service.ensure_within_total(app_obj, ch.amount)
            fee_service.apply_payment(db, app_obj, ch.amount, "cash",
                                      admin.name, receipt_number=receipt_number,
                                      campus=app_obj.campus or "")
            db.add(Payment(application_id=app_obj.id, amount=ch.amount,
                           method="cash", receipt_number=receipt_number,
                           reference=ch.challan_no, campus=app_obj.campus or "",
                           status="verified", verified_by=admin.id,
                           verified_at=now()))
    elif action == "reject":
        ch.status = ChallanStatus.REJECTED
    else:
        ch.status = ChallanStatus.UNPAID
    db.commit()

    if action == "approve":
        await notify(db, "payment_verified", "Cash payment approved",
                     f"Cash payment for challan {ch.challan_no} "
                     f"(Rs {ch.amount:,.0f}, {sname}) approved by "
                     f"{admin.name}.",
                     related_id=ch.application_id, priority="high",
                     category="payment",
                     campus=(ch.application.campus if ch.application else "") or "")
    _audit(db, f"cash_{action}",
           f"{ch.challan_no}: cash → {action} by {admin.email}", admin.id)
    return {"success": True, "challan": challan_to_dict(ch)}


@router.get("/api/admin/challans")
def all_challans(q: str | None = None, status: str | None = None,
                 method: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 page: int = Query(1, ge=1),
                 page_size: int = Query(20, ge=1, le=100),
                 admin: Admin = Depends(any_staff),
                 db: Session = Depends(get_db)):
    """All Challans — search by student / application id / CNIC / course /
    department / status / date / payment method."""
    query = (db.query(Challan)
             .join(Application, Challan.application_id == Application.id)
             .join(Student)
             .options(joinedload(Challan.application)
                      .joinedload(Application.student))
             .order_by(desc(Challan.created_at)))
    _campus = admin_campus(admin)
    if _campus:
        query = query.filter(Application.campus == _campus)
    if q:
        like = f"%{q.strip()}%"
        from app.models import Course, Department
        query = (query.outerjoin(Course, Application.course_id == Course.id)
                 .outerjoin(Department,
                            Application.department_id == Department.id)
                 .filter(or_(Student.full_name.ilike(like),
                             Student.cnic.ilike(like),
                             Student.phone.ilike(like),
                             Challan.challan_no.ilike(like),
                             Application.application_no.ilike(like),
                             Course.name.ilike(like),
                             Department.name.ilike(like))))
    if status:
        query = query.filter(Challan.status == status)
    if method:
        query = query.filter(Challan.payment_method == method)
    if date_from:
        query = query.filter(Challan.created_at >= f"{date_from} 00:00:00")
    if date_to:
        query = query.filter(Challan.created_at <= f"{date_to} 23:59:59")
    result = paginate(query, page, page_size)
    result["items"] = [challan_to_dict(c, include_receipts=True)
                       for c in result["items"]]
    return result


@router.get("/api/admin/challans/{challan_id}/print-url")
def challan_print_url(challan_id: int, admin: Admin = Depends(any_staff),
                      db: Session = Depends(get_db)):
    """Dashboard fetches this, then opens the print view in a new tab."""
    ch = db.get(Challan, challan_id)
    if not ch:
        raise HTTPException(status_code=404, detail="Challan not found")
    _guard_campus(ch.application, admin)
    return {"url": f"/challan/{ch.challan_no}?token={ch.access_token}"}
