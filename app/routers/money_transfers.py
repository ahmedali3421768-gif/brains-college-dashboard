"""Inter-campus money-transfer endpoints.

Source campus raises a request; the destination campus verifies the roll number
and approves, or rejects with a reason. Everything is campus-scoped and audited.
"""
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.auth.dependencies import admin_campus, any_staff, managers
from app.database import get_db
from app.models import ActivityLog, Admin, MoneyTransfer
from app.services import money_transfer_service as svc
from app.services.notification_service import notify

router = APIRouter(prefix="/api/admin/money-transfers", tags=["money-transfers"])


def _log(db, admin, action, ref, req: Request | None = None):
    ip = ""
    if req is not None:
        ip = (req.headers.get("x-forwarded-for") or
              (req.client.host if req.client else "")) or ""
    db.add(ActivityLog(admin_id=admin.id, action=action,
                       detail=f"[{ref}] by {admin.name} ({admin.campus or 'HQ'})"
                              + (f" ip={ip}" if ip else "")))
    db.commit()


@router.get("/lookup")
def lookup_student(roll: str = Query(...),
                   admin: Admin = Depends(managers),
                   db: Session = Depends(get_db)):
    """Look up a student in the current user's campus for the transfer form."""
    campus = admin_campus(admin) or admin.campus or ""
    if not campus:
        raise HTTPException(status_code=422,
                            detail="Select a campus context first.")
    return svc.lookup(db, campus, roll)


@router.post("")
async def create_transfer(payload: dict, request: Request,
                          admin: Admin = Depends(managers),
                          db: Session = Depends(get_db)):
    mt = svc.create_request(
        db, admin,
        dest_campus=(payload.get("dest_campus") or "").strip(),
        roll=(payload.get("roll") or payload.get("roll_number") or "").strip(),
        amount=payload.get("amount"),
        remarks=payload.get("remarks") or "")
    _log(db, admin, "money_transfer_created", mt.transfer_no, request)

    await notify(
        db, "system", "New money transfer request",
        f"{mt.source_campus} requested a transfer of Rs {mt.amount:,.0f} for "
        f"{mt.student_name} ({mt.source_roll}) to {mt.dest_campus}. "
        f"Reference {mt.transfer_no}, raised by {admin.name}.",
        priority="high", category="admission", campus=mt.dest_campus)
    await notify(
        db, "system", "Money transfer requested",
        f"Your transfer of Rs {mt.amount:,.0f} for {mt.student_name} "
        f"({mt.source_roll}) to {mt.dest_campus} is awaiting approval "
        f"({mt.transfer_no}).",
        priority="normal", category="admission", campus=mt.source_campus)
    return svc.to_dict(mt, admin_campus(admin))


@router.get("")
def list_transfers(status: str | None = None, q: str | None = None,
                   direction: str | None = None,
                   admin: Admin = Depends(any_staff),
                   db: Session = Depends(get_db)):
    query = db.query(MoneyTransfer).order_by(desc(MoneyTransfer.requested_at))
    scope = admin_campus(admin)
    if scope:
        query = query.filter(or_(MoneyTransfer.source_campus == scope,
                                 MoneyTransfer.dest_campus == scope))
    if status:
        query = query.filter(MoneyTransfer.status == status)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(
            MoneyTransfer.transfer_no.ilike(like),
            MoneyTransfer.student_name.ilike(like),
            MoneyTransfer.source_roll.ilike(like),
            MoneyTransfer.source_campus.ilike(like),
            MoneyTransfer.dest_campus.ilike(like)))

    items = [svc.to_dict(m, scope) for m in query.limit(1000).all()]
    if direction in ("incoming", "outgoing"):
        items = [i for i in items if i["direction"] == direction]

    counts = {
        "pending": sum(1 for i in items if i["status"] == "pending"),
        "approved": sum(1 for i in items if i["status"] == "approved"),
        "rejected": sum(1 for i in items if i["status"] == "rejected"),
        "incoming_pending": sum(1 for i in items
                                if i["status"] == "pending" and i["can_decide"]),
        "incoming_amount": round(sum(i["amount"] for i in items
                                     if i["direction"] == "incoming"
                                     and i["status"] == "approved"), 2),
        "outgoing_amount": round(sum(i["amount"] for i in items
                                     if i["direction"] == "outgoing"
                                     and i["status"] == "approved"), 2),
        "total_amount": round(sum(i["amount"] for i in items
                                  if i["status"] == "approved"), 2),
    }
    today = date.today().isoformat()
    counts["today"] = sum(1 for i in items
                          if (i["requested_at"] or "")[:10] == today)
    return {"items": items, "total": len(items), "counts": counts}


@router.post("/{mt_id}/approve")
async def approve_transfer(mt_id: int, payload: dict, request: Request,
                           admin: Admin = Depends(managers),
                           db: Session = Depends(get_db)):
    mt = db.get(MoneyTransfer, mt_id)
    if not mt:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    scope = admin_campus(admin)
    if scope and scope != mt.dest_campus:
        raise HTTPException(
            status_code=403,
            detail="Only the destination campus can approve this transfer.")

    dest_roll = (payload.get("dest_roll") or payload.get("roll") or "").strip()
    _log(db, admin, "money_transfer_roll_verified", mt.transfer_no, request)
    svc.approve(db, admin, mt, dest_roll)
    _log(db, admin, "money_transfer_approved", mt.transfer_no, request)

    await notify(
        db, "system", "Money transfer approved",
        f"Transfer {mt.transfer_no} of Rs {mt.amount:,.0f} for "
        f"{mt.student_name} ({mt.source_roll}) was approved by {mt.dest_campus}. "
        f"Rs {mt.amount:,.0f} moved from {mt.source_campus} to {mt.dest_campus}.",
        priority="high", category="admission", campus=mt.source_campus)
    await notify(
        db, "system", "Money transfer completed",
        f"You approved {mt.transfer_no}: Rs {mt.amount:,.0f} for "
        f"{mt.student_name} received from {mt.source_campus}.",
        priority="normal", category="admission", campus=mt.dest_campus)
    return svc.to_dict(mt, scope)


@router.post("/{mt_id}/reject")
async def reject_transfer(mt_id: int, payload: dict, request: Request,
                          admin: Admin = Depends(managers),
                          db: Session = Depends(get_db)):
    mt = db.get(MoneyTransfer, mt_id)
    if not mt:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    scope = admin_campus(admin)
    if scope and scope != mt.dest_campus:
        raise HTTPException(
            status_code=403,
            detail="Only the destination campus can reject this transfer.")

    svc.reject(db, admin, mt, payload.get("reason") or payload.get("reject_reason"))
    _log(db, admin, "money_transfer_rejected", mt.transfer_no, request)

    await notify(
        db, "system", "Money transfer rejected",
        f"Transfer {mt.transfer_no} of Rs {mt.amount:,.0f} for "
        f"{mt.student_name} ({mt.source_roll}) was rejected by {mt.dest_campus}. "
        f"Reason: {mt.reject_reason}",
        priority="high", category="admission", campus=mt.source_campus)
    return svc.to_dict(mt, scope)


@router.post("/{mt_id}/cancel")
async def cancel_transfer(mt_id: int, request: Request,
                          admin: Admin = Depends(managers),
                          db: Session = Depends(get_db)):
    """The source campus (or a super admin) may cancel its own pending request."""
    mt = db.get(MoneyTransfer, mt_id)
    if not mt:
        raise HTTPException(status_code=404, detail="Transfer not found.")
    scope = admin_campus(admin)
    if scope and scope != mt.source_campus:
        raise HTTPException(status_code=403,
                            detail="Only the requesting campus can cancel this.")
    if mt.status != "pending":
        raise HTTPException(status_code=409,
                            detail=f"This transfer is already {mt.status}.")
    mt.status = "cancelled"
    mt.decided_by_name = admin.name
    db.commit()
    _log(db, admin, "money_transfer_cancelled", mt.transfer_no, request)
    return svc.to_dict(mt, scope)


@router.get("/export")
def export_transfers(format: str = Query("csv"),
                     status: str | None = None,
                     source_campus: str | None = None,
                     dest_campus: str | None = None,
                     admin: Admin = Depends(any_staff),
                     db: Session = Depends(get_db)):
    from app.services import report_service

    query = db.query(MoneyTransfer).order_by(desc(MoneyTransfer.requested_at))
    scope = admin_campus(admin)
    if scope:
        query = query.filter(or_(MoneyTransfer.source_campus == scope,
                                 MoneyTransfer.dest_campus == scope))
    if status:
        query = query.filter(MoneyTransfer.status == status)
    if source_campus:
        query = query.filter(MoneyTransfer.source_campus == source_campus)
    if dest_campus:
        query = query.filter(MoneyTransfer.dest_campus == dest_campus)

    rows = []
    for m in query.limit(10000).all():
        rows.append([
            m.transfer_no, m.source_campus, m.dest_campus, m.student_name,
            m.source_roll, m.course, m.amount, m.status.title(),
            m.requested_by_name,
            report_service._fmt_date(m.requested_at) if m.requested_at else "",
            m.decided_by_name,
            m.reject_reason or "",
        ])
    headers = ["Transfer No", "Source Campus", "Destination Campus",
               "Student", "Roll Number", "Course", "Amount", "Status",
               "Requested By", "Requested On", "Decided By", "Reject Reason"]
    meta = {"Report Generated": report_service.stamp(),
            "Generated By": admin.name,
            "Campus": scope or "All campuses"}
    summary = [
        ("Total transfers", len(rows)),
        ("Approved amount",
         round(sum(r[6] for r in rows if r[7] == "Approved"), 2)),
    ]
    sections = [{"title": "MONEY TRANSFERS", "headers": headers, "rows": rows,
                 "money_cols": [6]}]
    body, media, ext = report_service.build(
        format, "Money Transfer Report", meta, summary, sections)
    fname = f"money-transfers-{datetime.now().strftime('%Y%m%d-%H%M')}.{ext}"
    return Response(content=body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{fname}"'})
