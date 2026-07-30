"""Challans, redesigned (no files, no downloads).

A challan is now just a database row; opening it shows a print-friendly
POS/thermal-receipt page (80 mm) that the office prints with Ctrl+P.
Nothing is stored on disk and the page always shows the LATEST installment,
due date and payment status.
"""
import html
import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Application, Challan, ChallanStatus
from app.services import fee_service
from app.utils.timeutil import now


def create_challan(db: Session, application: Application) -> Challan:
    amount = settings.CHALLAN_DEFAULT_AMOUNT
    if application.course and application.course.admission_fee:
        amount = application.course.admission_fee

    challan = Challan(
        application_id=application.id,
        challan_no="TMP-" + uuid.uuid4().hex[:16],
        amount=amount,
        due_date=(now() + timedelta(days=settings.CHALLAN_DUE_DAYS)).date(),
        status=ChallanStatus.UNPAID,
    )
    db.add(challan)
    db.flush()
    challan.challan_no = f"CH-{now().year}-{challan.id:05d}"
    db.commit()
    db.refresh(challan)
    return challan


# ═════════════════════ thermal-receipt print view ════════════════════════
def _e(v) -> str:
    return html.escape(str(v if v is not None else "—"))


def _row(label: str, value, bold=False) -> str:
    w = "700" if bold else "600"
    return (f'<div class="r"><span>{_e(label)}</span>'
            f'<b style="font-weight:{w}">{_e(value)}</b></div>')


def render_print_view(challan: Challan) -> str:
    """Premium red-and-white fee challan. Shows only the essentials:
    receipt no, name, roll number, total fee, fee paying (current installment),
    paid, remaining, installment count and fee status. Prints with Ctrl+P."""
    app_obj = challan.application
    s = app_obj.student if app_obj else None
    fee = fee_service.summary(app_obj) if app_obj else {}
    cur = fee.get("current_installment") or {}

    total = fee.get("total_fee", challan.amount) or 0
    paid = fee.get("paid", 0) or 0
    remaining = fee.get("remaining", max(0, total - paid)) or 0
    inst_total = fee.get("installments_total", 0) or 0
    inst_done = fee.get("installments_completed", 0) or 0

    pay_status = (fee.get("payment_status") or "unpaid").replace("_", " ").upper()
    pay_class = {"UNPAID": "unpaid", "PARTIALLY PAID": "partial",
                 "FULLY PAID": "paid"}.get(pay_status, "unpaid")

    fee_paying = (f"Installment {cur.get('number')} — Rs {cur.get('amount', 0):,.0f}"
                  if cur else "All installments cleared")

    # Course / programme shown on the challan
    course_name = ""
    if app_obj:
        course_name = (getattr(app_obj, "course_name", "") or "").strip()
        if not course_name and getattr(app_obj, "course", None):
            course_name = app_obj.course.name
    course_name = course_name or "—"

    # Receipt number: latest one recorded on a paid installment, else the
    # challan's own number as the reference.
    receipt_no = ""
    if app_obj:
        for inst in sorted(app_obj.installments,
                           key=lambda i: (i.paid_at is not None, i.paid_at or 0,
                                          i.number), reverse=True):
            if getattr(inst, "receipt_number", ""):
                receipt_no = inst.receipt_number
                break
    if not receipt_no:
        receipt_no = f"RC-{challan.challan_no.replace('CH-', '')}"

    issue = (challan.created_at.strftime("%d %B %Y")
             if challan.created_at else now().strftime("%d %B %Y"))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fee Challan — {_e(s.full_name if s else '')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700;800;900&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --red:#b81d24; --red-deep:#8e1319; --red-dark:#6d0f14;
    --ink:#231416; --muted:#8a7275; --line:#f0dcdd;
    --gold:#d4af5a; --cream:#fff7f7; --paper:#ffffff;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  html,body {{ background:#efe9e9; font-family:'Inter',system-ui,Arial,sans-serif; color:var(--ink); -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .toolbar {{ text-align:center; padding:18px; }}
  .toolbar button {{ font:inherit; font-weight:700; font-size:14px; padding:12px 30px; border:0; border-radius:11px; background:var(--red); color:#fff; cursor:pointer; box-shadow:0 6px 18px rgba(184,29,36,.32); transition:.15s; }}
  .toolbar button:hover {{ background:var(--red-deep); transform:translateY(-1px); }}

  .challan {{ width:150mm; max-width:94vw; margin:0 auto 26px; background:var(--paper);
    border-radius:8px; overflow:hidden; position:relative;
    box-shadow:0 16px 48px rgba(109,15,20,.22); border:1px solid var(--line); }}
  /* thin gold inner frame */
  .challan::after {{ content:""; position:absolute; inset:5mm; border:1.2px solid var(--gold);
    border-radius:4px; pointer-events:none; opacity:.55; }}
  /* "Paid in full" watermark — shown only when fully paid */
  .wm {{ position:absolute; inset:0; display:flex; align-items:center; justify-content:center;
    pointer-events:none; z-index:0; }}
  .wm .stamp {{ transform:rotate(-15deg); text-align:center; opacity:.10;
    padding:6mm 14mm; border:3px double var(--red); border-radius:10px; }}
  .wm .stamp .big {{ font-family:'Playfair Display',serif; font-weight:900; font-style:italic;
    font-size:64px; line-height:.9; color:var(--red); letter-spacing:2px; white-space:nowrap; }}
  .wm .stamp .sub {{ font-family:'Inter',sans-serif; font-weight:800; font-size:15px;
    letter-spacing:.72em; text-transform:uppercase; color:var(--red); margin-top:3mm; padding-left:.72em; }}

  .head {{ position:relative; z-index:1; text-align:center; color:#fff5f5; padding:11mm 12mm 8mm;
    background:
      radial-gradient(130% 130% at 88% -25%, rgba(212,175,90,.28), transparent 55%),
      linear-gradient(135deg, var(--red) 0%, var(--red-deep) 62%, var(--red-dark) 100%); }}
  .crest {{ width:20mm; height:20mm; margin:0 auto 3mm; border-radius:50%;
    background:#fff; display:grid; place-items:center; overflow:hidden;
    box-shadow:0 0 0 2px var(--gold), 0 6px 16px rgba(0,0,0,.3); }}
  .crest img {{ width:100%; height:100%; object-fit:contain; padding:2mm; }}
  .crest .fb {{ font-family:'Playfair Display',serif; font-weight:800; font-size:30px; color:var(--red); }}
  .cname {{ font-family:'Playfair Display',serif; font-weight:800; font-size:28px; letter-spacing:.5px; line-height:1.08; text-shadow:0 1px 2px rgba(0,0,0,.18); }}
  .caddr {{ font-size:10px; color:#ffe0e0; margin-top:2mm; letter-spacing:.35px; }}
  .ribbon {{ display:inline-block; margin-top:5mm; padding:2.2mm 10mm; background:rgba(255,255,255,.10);
    border:1px solid var(--gold); color:#fff; font-size:11.5px; font-weight:800;
    letter-spacing:.45em; text-transform:uppercase; border-radius:3px; }}

  .meta {{ position:relative; z-index:1; display:flex; justify-content:space-between; flex-wrap:wrap; gap:4px;
    padding:5mm 12mm 0; font-size:10.5px; color:var(--muted); }}
  .meta .rcpt {{ background:var(--cream); border:1px solid var(--line); border-left:3px solid var(--red);
    padding:1.6mm 5mm; border-radius:4px; }}
  .meta b {{ color:var(--ink); font-weight:700; }}

  .body {{ position:relative; z-index:1; padding:5mm 12mm 4mm; }}
  .sect {{ font-size:10px; font-weight:800; letter-spacing:.28em; text-transform:uppercase;
    color:var(--red); margin:5mm 0 2.5mm; padding-bottom:2mm; border-bottom:1.5px solid var(--line); }}

  .r {{ display:flex; justify-content:space-between; align-items:baseline; gap:12px;
    padding:2.5mm 0; border-bottom:1px dotted var(--line); }}
  .r:last-child {{ border-bottom:0; }}
  .r span {{ color:var(--muted); font-size:11.5px; letter-spacing:.2px; }}
  .r b {{ font-size:13px; font-weight:700; text-align:right; }}
  .r.big b {{ font-family:'Playfair Display',serif; font-size:21px; font-weight:800; color:var(--red-deep); }}

  .totalcard {{ margin-top:4.5mm; background:linear-gradient(135deg,#fff,#fdeeee);
    border:1px solid var(--line); border-left:5px solid var(--red); border-radius:7px;
    padding:5mm 6mm; display:flex; justify-content:space-between; align-items:center; }}
  .totalcard .lbl {{ font-size:10px; font-weight:800; letter-spacing:.24em; text-transform:uppercase; color:var(--muted); }}
  .totalcard .amt {{ font-family:'Playfair Display',serif; font-size:31px; font-weight:800; color:var(--red); line-height:1; }}
  .totalcard .sub {{ font-size:10.5px; color:var(--muted); margin-top:1.8mm; }}

  .statuswrap {{ text-align:center; margin:5mm 0 2mm; }}
  .status {{ display:inline-block; padding:2.6mm 13mm; border-radius:999px; font-size:12px;
    font-weight:800; letter-spacing:.16em; text-transform:uppercase; }}
  .status.unpaid  {{ background:#fbe4e0; color:#a5281c; box-shadow:inset 0 0 0 1px #edb9b0; }}
  .status.partial {{ background:#fbf0d2; color:#8a5a00; box-shadow:inset 0 0 0 1px #e6cf94; }}
  .status.paid    {{ background:#dff1e5; color:#1f6b3f; box-shadow:inset 0 0 0 1px #a9d6ba; }}

  .notice {{ margin:5mm 0 0; text-align:center; background:var(--cream); border:1px dashed var(--red);
    border-radius:6px; padding:3mm 6mm; color:var(--red-deep); font-size:10.5px; font-weight:700;
    letter-spacing:.3px; }}

  .foot {{ position:relative; z-index:1; padding:4mm 12mm 8mm; text-align:center; color:var(--muted); font-size:9.5px; line-height:1.6; }}
  .foot .sign {{ display:flex; justify-content:space-between; margin:9mm 0 4mm; }}
  .foot .sign div {{ width:44%; border-top:1.5px solid var(--ink); padding-top:1.5mm; font-size:10px; color:var(--ink); font-weight:600; }}
  .foot .gen {{ font-style:italic; }}
  .foot .bar {{ height:3px; background:linear-gradient(90deg,var(--red),var(--gold),var(--red)); border-radius:3px; margin-bottom:4mm; }}

  @media print {{
    html,body {{ background:#fff; }}
    .toolbar {{ display:none; }}
    .challan {{ width:100%; max-width:100%; margin:0; box-shadow:none; border:0; border-radius:0; }}
    @page {{ size:A4; margin:12mm; }}
  }}
</style></head>
<body>
  <div class="toolbar"><button onclick="window.print()">🖨&nbsp;&nbsp;Print Challan</button></div>

  <div class="challan">
    <div class="wm">{'<div class="stamp"><div class="big">Paid in Full</div><div class="sub">Brains College</div></div>' if pay_class == 'paid' else ''}</div>

    <div class="head">
      <div class="crest">
        <img src="/static/img/logo.png" alt=""
             onerror="this.style.display='none';this.nextElementSibling.style.display='block'">
        <span class="fb" style="display:none">B</span>
      </div>
      <div class="cname">{_e(settings.COLLEGE_NAME)}</div>
      <div class="caddr">{_e(settings.COLLEGE_ADDRESS)}</div>
      {f'<div class="caddr">{_e(settings.COLLEGE_PHONE)}</div>' if settings.COLLEGE_PHONE else ''}
      <div class="ribbon">Fee Challan</div>
    </div>

    <div class="meta">
      <div class="rcpt">Receipt&nbsp;No:&nbsp;<b>{_e(receipt_no)}</b></div>
      <div>Challan&nbsp;No:&nbsp;<b>{_e(challan.challan_no)}</b></div>
      <div>Date:&nbsp;<b>{_e(issue)}</b></div>
    </div>

    <div class="body">
      <div class="sect">Student</div>
      <div class="r big"><span>Name</span><b>{_e(s.full_name if s else '—')}</b></div>
      <div class="r"><span>Roll Number</span><b>{_e(s.roll_number if s else '—')}</b></div>
      <div class="r"><span>Course</span><b>{_e(course_name)}</b></div>

      <div class="sect">Fee Details</div>
      <div class="r"><span>Total Fee</span><b>Rs {total:,.0f}</b></div>
      <div class="r"><span>Fee Paying (this challan)</span><b>{_e(fee_paying)}</b></div>
      <div class="r"><span>Paid</span><b>Rs {paid:,.0f}</b></div>
      <div class="r"><span>Installments</span><b>{inst_done} of {inst_total} paid</b></div>

      <div class="totalcard">
        <div>
          <div class="lbl">Remaining Balance</div>
          <div class="sub">{fee.get('percent_paid', 0)}% of total fee paid</div>
        </div>
        <div class="amt">Rs {remaining:,.0f}</div>
      </div>

      <div class="statuswrap">
        <span class="status {pay_class}">{_e(pay_status)}</span>
      </div>

      <div class="notice">Once paid, the fee is non-refundable and non-transferable.</div>
    </div>

    <div class="foot">
      <div class="sign">
        <div>Depositor's Signature</div>
        <div>Authorized Signature &amp; Stamp</div>
      </div>
      <div class="bar"></div>
      <div class="gen">This challan is system generated and does not require a signature.</div>
      <div>{_e(settings.COLLEGE_NAME)} &nbsp;·&nbsp; Receipt {_e(receipt_no)} &nbsp;·&nbsp; {_e(challan.challan_no)}</div>
    </div>
  </div>
</body></html>"""
