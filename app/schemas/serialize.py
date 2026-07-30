"""ORM → dict serializers shared by routers and exports."""
import json


def _paid_fee(app) -> float:
    """Total paid across installments (works on already-loaded rows)."""
    try:
        return round(sum(i.paid_amount or 0 for i in app.installments), 2)
    except Exception:
        return 0.0


def _pending_payment(app) -> float:
    """Remaining amount the student still has to pay = total − paid."""
    total = getattr(app, "total_fee", 0) or 0
    return max(0.0, round(total - _paid_fee(app), 2))


def _latest_receipt(app) -> str:
    """Most recent receipt number issued to this student (installments +
    payments), newest first. Computed from loaded relationships."""
    best, best_when = "", None
    for i in getattr(app, "installments", []) or []:
        rn = getattr(i, "receipt_number", "") or ""
        if not rn:
            continue
        when = getattr(i, "paid_at", None) or getattr(i, "updated_at", None) \
            or getattr(i, "created_at", None)
        if best_when is None or (when and when > best_when):
            best, best_when = rn, when
    for p in getattr(app, "payments", []) or []:
        rn = getattr(p, "receipt_number", "") or ""
        if not rn:
            continue
        when = getattr(p, "created_at", None)
        if best_when is None or (when and when > best_when):
            best, best_when = rn, when
    return best


def admin_to_dict(a) -> dict:
    return {
        "id": a.id, "name": a.name, "email": a.email, "role": a.role,
        "campus": getattr(a, "campus", "") or "",
        "is_active": a.is_active, "created_at": a.created_at,
        "last_login": a.last_login,
    }


def application_to_dict(app, include_detail: bool = False) -> dict:
    s = app.student
    d = {
        "id": app.id,
        "application_no": app.application_no,
        "roll_number": s.roll_number if s else "",
        "full_name": s.full_name if s else "",
        "father_name": s.father_name if s else "",
        "cnic": s.cnic if s else "",
        "phone": s.phone if s else "",
        "guardian_phone": (getattr(s, "guardian_phone", "") or "") if s else "",
        "email": s.email if s else "",
        "gender": s.gender if s else "",
        "city": s.city if s else "",
        "programme_category": getattr(app, "programme_category", "") or "",
        "course_name": getattr(app, "course_name", "") or (
            app.course.name if app.course else ""),
        "course": app.course.name if app.course else (
            getattr(app, "course_name", "") or ""),
        "course_id": app.course_id,
        "department": app.department.name if app.department else "",
        "department_id": app.department_id,
        "session": getattr(app, "session", "") or "",
        "lead_source": getattr(app, "lead_source", "") or "",
        "lead_source_detail": getattr(app, "lead_source_detail", "") or "",
        "campus": app.campus,
        "percentage": app.percentage,
        "application_status": app.application_status,
        "payment_status": app.payment_status,
        "is_referral": bool(getattr(app, "is_referral", False)),
        "referral_status": getattr(app, "referral_status", "") or "",
        "eligibility_status": getattr(app, "eligibility_status", "not_eligible"),
        "admission_status": app.admission_status,
        "total_fee": getattr(app, "total_fee", 0),
        "paid_fee": _paid_fee(app),
        "pending_payment": _pending_payment(app),
        "latest_receipt": _latest_receipt(app),
        "fee_category": getattr(app, "fee_category", "Admission Fee"),
        "class_time": getattr(app, "class_time", "") or "",
        "lab_time": getattr(app, "lab_time", "") or "",
        "instructor_name": getattr(app, "instructor_name", "") or "",
        "course_duration_months": getattr(app, "course_duration_months", 3) or 3,
        "card_print_count": getattr(app, "card_print_count", 0) or 0,
        "card_last_printed_at": getattr(app, "card_last_printed_at", None),
        "assigned_staff_id": getattr(app, "assigned_staff_id", None),
        "assigned_staff_name": getattr(app, "assigned_staff_name", "") or "",
        "transferred_from": getattr(app, "transferred_from", "") or "",
        "previous_roll_number": getattr(app, "previous_roll_number", "") or "",
        "transferred_at": getattr(app, "transferred_at", None),
        "current_campus": app.campus,
        "original_campus": getattr(app, "transferred_from", "") or app.campus,
        "is_transferred": bool(getattr(app, "transferred_from", "")),
        "submitted_at": app.submitted_at,
        "updated_at": app.updated_at,
    }
    if include_detail:
        try:
            docs = json.loads(app.documents or "[]")
        except json.JSONDecodeError:
            docs = []
        try:
            extra = json.loads(app.extra_fields or "{}")
        except json.JSONDecodeError:
            extra = {}
        d.update({
            "student_id": app.student_id,
            "date_of_birth": str(s.date_of_birth) if s and s.date_of_birth else None,
            "address": s.address if s else "",
            "class_timing": extra.get("class_timing", ""),
            "admission_date": extra.get("admission_date", ""),
            "duration": extra.get("duration", ""),
            "remarks": getattr(app, "remarks", "") or "",
            "previous_qualification": app.previous_qualification,
            "documents": docs,
            "extra_fields": extra,
            "notes": [note_to_dict(n) for n in app.notes],
            "payments": [payment_to_dict(p) for p in app.payments],
        })
    return d


def note_to_dict(n) -> dict:
    return {"id": n.id, "admin_name": n.admin_name, "note": n.note,
            "created_at": n.created_at}


def payment_to_dict(p) -> dict:
    return {"id": p.id, "amount": p.amount, "method": p.method,
            "receipt_number": getattr(p, "receipt_number", "") or "",
            "reference": p.reference,
            "campus": getattr(p, "campus", "") or "",
            "status": p.status,
            "created_at": p.created_at, "verified_at": p.verified_at}


def session_to_dict(s, include_messages: bool = False) -> dict:
    duration = None
    if s.started_at and s.last_activity_at:
        duration = int((s.last_activity_at - s.started_at).total_seconds())
    d = {
        "id": s.id, "title": s.title,
        "visitor_name": s.visitor_name, "visitor_phone": s.visitor_phone,
        "visitor_id": s.visitor_id, "student_id": s.student_id,
        "student_name": s.student.full_name if s.student else None,
        "ip_address": s.ip_address, "browser": s.browser, "os": s.os,
        "device": s.device, "country": s.country,
        "page_url": s.page_url, "status": s.status,
        "visitor_email": s.visitor_email,
        "message_count": s.message_count,
        "started_at": s.started_at, "last_activity_at": s.last_activity_at,
        "duration_seconds": duration,
    }
    if include_messages:
        d["messages"] = [message_to_dict(m) for m in s.messages]
    return d


def message_to_dict(m) -> dict:
    return {"id": m.id, "role": m.role, "content": m.content,
            "response_time_ms": m.response_time_ms, "created_at": m.created_at}


def lead_to_dict(l, include_notes: bool = False) -> dict:
    d = {"id": l.id, "name": l.name, "phone": l.phone,
         "email": l.email, "city": l.city, "campus": l.campus,
         "interested_course": l.interested_course,
         "interested_department": l.interested_department,
         "source": l.source, "status": l.status,
         "assigned_to": l.assigned_to, "assigned_to_name": l.assigned_to_name,
         "follow_up_at": l.follow_up_at, "student_id": l.student_id,
         "session_id": l.session_id,
         "created_at": l.created_at, "updated_at": l.updated_at}
    if include_notes:
        d["notes"] = [{"id": n.id, "admin_name": n.admin_name, "note": n.note,
                       "created_at": n.created_at} for n in l.notes]
    return d


def challan_to_dict(c, include_receipts: bool = False) -> dict:
    app = c.application
    s = app.student if app else None
    d = {
        "id": c.id, "challan_no": c.challan_no,
        "application_id": c.application_id,
        "application_no": app.application_no if app else "",
        "roll_number": s.roll_number if s else "",
        "receipt_number": getattr(c, "receipt_number", "") or "",
        "campus": (app.campus if app else "") or "",
        "student_name": s.full_name if s else "",
        "cnic": s.cnic if s else "",
        "phone": s.phone if s else "",
        "guardian_phone": (getattr(s, "guardian_phone", "") or "") if s else "",
        "course": app.course.name if app and app.course else "",
        "department": app.department.name if app and app.department else "",
        "amount": c.amount,
        "due_date": str(c.due_date) if c.due_date else None,
        "payment_method": c.payment_method,
        "status": c.status,
        "created_at": c.created_at,
    }
    if include_receipts:
        d["receipts"] = [receipt_to_dict(r) for r in c.receipts]
    return d


def receipt_to_dict(r, include_paths: bool = False) -> dict:
    d = {"id": r.id, "challan_id": r.challan_id,
         "original_name": r.original_name, "content_type": r.content_type,
         "size_bytes": r.size_bytes,
         "transaction_id": r.transaction_id,
         "jazzcash_number": r.jazzcash_number,
         "payment_date": str(r.payment_date) if r.payment_date else None,
         "remarks": r.remarks, "status": r.status,
         "verified_by_name": r.verified_by_name,
         "verified_at": r.verified_at,
         "verification_remarks": r.verification_remarks,
         "created_at": r.created_at}
    if include_paths:
        d["file_path"] = r.file_path
    return d


def notification_to_dict(n) -> dict:
    return {"id": n.id, "type": n.type, "category": n.category,
            "priority": n.priority, "title": n.title, "message": n.message,
            "related_id": n.related_id, "is_read": n.is_read,
            "campus": getattr(n, "campus", "") or "",
            "occurrences": n.occurrences,
            "created_at": n.created_at, "updated_at": n.updated_at}
