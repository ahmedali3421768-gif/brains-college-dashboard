"""Attendance Card — a premium, printable A4 card for each admitted student.

Deliberately nothing like the fee challan: its own layout, its own palette
(deep green + gold on white), and its own sections —

    Header · Student Information · Course Progress (auto-generated months)
    · Test Session · Fee Status · Warning Record

The Course Progress months are derived automatically from the admission date
and the course duration, so no one types them in.
"""
from __future__ import annotations

from datetime import datetime
from html import escape as _e

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def course_months(start, duration_months: int) -> list[str]:
    """['June 2026', 'July 2026', 'August 2026'] — consecutive from the
    admission date, one per month of the course."""
    if not start:
        start = datetime.now()
    try:
        y, m = start.year, start.month
    except AttributeError:
        y, m = datetime.now().year, datetime.now().month
    n = max(1, min(int(duration_months or 3), 24))
    out = []
    for _ in range(n):
        out.append(f"{MONTHS[m - 1]} {y}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _fmt(d) -> str:
    if not d:
        return "—"
    try:
        return d.strftime("%d %B %Y")
    except Exception:
        return str(d)


def render(application, *, campus_name: str = "") -> str:
    s = application.student
    course = (getattr(application, "course_name", "") or
              (application.course.name if application.course else "")) or "—"
    months = course_months(application.submitted_at,
                           getattr(application, "course_duration_months", 3))

    rows_progress = "".join(
        f'<tr><td class="mn">{_e(m)}</td><td class="blank"></td>'
        f'<td class="blank sm"></td></tr>' for m in months)

    rows_fee = "".join(
        '<tr><td class="blank"></td><td class="blank"></td>'
        '<td class="blank"></td></tr>' for _ in range(3))

    rows_warn = "".join(
        f'<tr><td class="wlab">Warning {i} for</td>'
        f'<td class="blank sm"></td>'
        f'<td class="wlab2">Month</td>'
        f'<td class="blank"></td></tr>' for i in (1, 2, 3))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Attendance Card — {_e(s.full_name if s else '')}</title>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  :root {{
    --green:#123D33; --green2:#1c5546; --gold:#c9a227; --gold2:#e6c65a;
    --ink:#16211d; --soft:#5b6b64; --faint:#93a29b; --line:#d9e2dd;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#eef2f0;font-family:'Inter',Arial,sans-serif;color:var(--ink);
    padding:22px;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
  .toolbar{{max-width:210mm;margin:0 auto 14px;display:flex;gap:10px;justify-content:flex-end}}
  .toolbar button{{padding:11px 22px;border:0;border-radius:11px;font-weight:700;
    font-size:14px;cursor:pointer;background:var(--green);color:#fff;font-family:inherit}}
  .toolbar button:hover{{background:var(--green2)}}
  .toolbar .ghost{{background:#fff;color:var(--green);border:1.5px solid var(--line)}}

  .card{{width:210mm;min-height:297mm;margin:0 auto;background:#fff;
    box-shadow:0 10px 40px rgba(20,33,29,.13);border-radius:6px;overflow:hidden;
    display:flex;flex-direction:column}}

  /* ── Header ── */
  .hd{{background:linear-gradient(120deg,#0d2e26,var(--green) 55%,var(--green2));
    color:#fff;padding:16px 20px;position:relative;overflow:hidden}}
  .hd::after{{content:"";position:absolute;right:-40px;top:-40px;width:170px;height:170px;
    background:radial-gradient(circle,rgba(201,162,39,.4),transparent 70%)}}
  .hd-in{{display:flex;align-items:center;gap:14px;position:relative}}
  .logo{{width:52px;height:52px;border-radius:14px;background:#fff;display:grid;place-items:center;
    overflow:hidden;box-shadow:0 0 0 2px var(--gold);flex:none}}
  .logo img{{width:100%;height:100%;object-fit:contain;padding:6px}}
  .logo span{{color:var(--green);font-family:'Fraunces',serif;font-weight:700;font-size:26px}}
  .hd h1{{font-family:'Fraunces',serif;font-size:19px;font-weight:600;line-height:1.15}}
  .hd .sub{{font-size:10.5px;color:#cfe0d8;letter-spacing:.5px;text-transform:uppercase;margin-top:2px}}
  .hd .spacer{{flex:1}}
  .title-badge{{background:rgba(255,255,255,.13);border:1.5px solid var(--gold);
    padding:8px 18px;border-radius:11px;text-align:center}}
  .title-badge b{{font-family:'Fraunces',serif;font-size:17px;letter-spacing:1px;display:block}}
  .hd-meta{{display:flex;gap:8px;margin-top:12px;position:relative;flex-wrap:wrap}}
  .chip{{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.25);
    border-radius:999px;padding:3px 12px;font-size:11px;font-weight:600}}
  .chip b{{color:var(--gold2)}}

  .body{{padding:16px 20px 20px;flex:1;display:flex;flex-direction:column;gap:13px}}

  .sect-h{{display:flex;align-items:center;gap:8px;margin-bottom:7px}}
  .sect-h .ic{{width:20px;height:20px;border-radius:6px;background:var(--green);
    color:#fff;display:grid;place-items:center;font-size:11px;flex:none}}
  .sect-h h2{{font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.9px;
    color:var(--green)}}
  .sect-h .rule{{flex:1;height:1px;background:linear-gradient(90deg,var(--gold),transparent)}}

  .panel{{border:1.5px solid var(--line);border-radius:12px;padding:12px 14px;background:#fcfdfc}}

  /* ── Student info grid ── */
  .sgrid{{display:grid;grid-template-columns:1fr 1fr;gap:9px 22px}}
  .f{{display:flex;gap:7px;align-items:baseline;border-bottom:1px dotted #cdd8d2;padding-bottom:5px}}
  .f .l{{font-size:10.5px;font-weight:700;color:var(--soft);min-width:96px;
    text-transform:uppercase;letter-spacing:.3px}}
  .f .v{{font-size:13px;font-weight:600;color:var(--ink)}}
  .f.wide{{grid-column:1 / -1}}
  .f .v.big{{font-family:'Fraunces',serif;font-size:15px;color:var(--green)}}

  table{{width:100%;border-collapse:collapse}}
  th{{background:var(--green);color:#fff;font-size:10.5px;font-weight:700;
    text-transform:uppercase;letter-spacing:.6px;padding:8px 10px;text-align:left;
    border:1px solid var(--green)}}
  td{{border:1px solid var(--line);padding:0;height:27px;font-size:12px}}
  td.mn{{padding:6px 10px;font-weight:700;color:var(--green);background:#f4f8f6;width:31%}}
  td.blank{{background:#fff}}
  td.sm{{width:22%}}
  .hint{{font-size:9.5px;color:var(--faint);margin-top:5px;font-style:italic}}

  /* ── Test session ── */
  .test-lines{{display:flex;flex-direction:column;gap:0}}
  .tl{{display:grid;grid-template-columns:1.4fr 1fr .8fr .8fr 1.6fr;border:1px solid var(--line);
    border-top:0}}
  .tl:first-child{{border-top:1px solid var(--line)}}
  .tl > div{{border-right:1px solid var(--line);height:28px}}
  .tl > div:last-child{{border-right:0}}
  .tl.head > div{{background:var(--green);color:#fff;font-size:10.5px;font-weight:700;
    text-transform:uppercase;letter-spacing:.5px;padding:7px 9px;height:auto}}

  /* ── Warnings ── */
  .warn table td{{height:30px}}
  td.wlab{{padding:6px 10px;font-weight:700;color:#a5281c;background:#fdf0ee;width:19%;font-size:11.5px}}
  td.wlab2{{padding:6px 10px;font-weight:600;color:var(--soft);background:#f7faf8;width:11%;font-size:11.5px}}

  .foot{{border-top:2px solid var(--gold);margin-top:auto;padding-top:9px;
    display:flex;justify-content:space-between;align-items:center;font-size:9.5px;color:var(--faint)}}
  .sig{{text-align:center}}
  .sig .ln{{width:130px;border-top:1.2px solid var(--ink);margin-bottom:3px}}
  .sig b{{font-size:10px;color:var(--ink)}}
  .sigs{{display:flex;gap:34px;justify-content:flex-end;margin-top:14px}}

  @media print {{
    body{{background:#fff;padding:0}}
    .toolbar{{display:none}}
    .card{{box-shadow:none;border-radius:0;width:auto;min-height:auto;margin:0}}
    @page {{ size:A4; margin:9mm; }}
  }}
</style></head><body>

<div class="toolbar">
  <button class="ghost" onclick="window.close()">Close</button>
  <button onclick="window.print()">🖨 Print Attendance Card</button>
</div>

<div class="card">
  <div class="hd">
    <div class="hd-in">
      <div class="logo"><img src="/static/img/logo.png" alt=""
        onerror="this.style.display='none';this.nextElementSibling.style.display='block'"><span style="display:none">B</span></div>
      <div>
        <h1>Brains Group of IT Colleges</h1>
        <div class="sub">Excellence in IT Education</div>
      </div>
      <div class="spacer"></div>
      <div class="title-badge"><b>ATTENDANCE CARD</b></div>
    </div>
    <div class="hd-meta">
      <span class="chip"><b>Campus:</b> {_e(campus_name or application.campus or '—')}</span>
      <span class="chip"><b>Session:</b> {_e(getattr(application, 'session', '') or '—')}</span>
      <span class="chip"><b>Batch:</b> {_e(getattr(application, 'session', '') or '—')}</span>
    </div>
  </div>

  <div class="body">

    <!-- Student Information -->
    <div>
      <div class="sect-h"><span class="ic">👤</span><h2>Student Information</h2><span class="rule"></span></div>
      <div class="panel sgrid">
        <div class="f"><span class="l">Roll Number</span><span class="v big">{_e(s.roll_number if s else '—')}</span></div>
        <div class="f"><span class="l">Date of Admission</span><span class="v">{_fmt(application.submitted_at)}</span></div>
        <div class="f wide"><span class="l">Student Name</span><span class="v big">{_e(s.full_name if s else '—')}</span></div>
        <div class="f wide"><span class="l">Course</span><span class="v">{_e(course)}</span></div>
        <div class="f"><span class="l">Teacher</span><span class="v">{_e(getattr(application, 'instructor_name', '') or '—')}</span></div>
        <div class="f"><span class="l">Class Time</span><span class="v">{_e(getattr(application, 'class_time', '') or '—')}</span></div>
        <div class="f"><span class="l">Lab Time</span><span class="v">{_e(getattr(application, 'lab_time', '') or '—')}</span></div>
      </div>
    </div>

    <!-- Course Progress -->
    <div>
      <div class="sect-h"><span class="ic">📚</span><h2>Course Progress</h2><span class="rule"></span></div>
      <table>
        <thead><tr><th>Month</th><th>Course Topic</th><th>Total Marks</th></tr></thead>
        <tbody>{rows_progress}</tbody>
      </table>
      <div class="hint">Months generated automatically from the admission date and course duration.</div>
    </div>

    <!-- Test Session -->
    <div>
      <div class="sect-h"><span class="ic">📝</span><h2>Test Session</h2><span class="rule"></span></div>
      <div class="test-lines">
        <div class="tl head"><div>Test Name</div><div>Test Date</div><div>Obtained</div><div>Total</div><div>Remarks</div></div>
        <div class="tl"><div></div><div></div><div></div><div></div><div></div></div>
        <div class="tl"><div></div><div></div><div></div><div></div><div></div></div>
        <div class="tl"><div></div><div></div><div></div><div></div><div></div></div>
        <div class="tl"><div></div><div></div><div></div><div></div><div></div></div>
      </div>
    </div>

    <!-- Fee Status -->
    <div>
      <div class="sect-h"><span class="ic">💳</span><h2>Fee Status</h2><span class="rule"></span></div>
      <table>
        <thead><tr><th>Receipt Number</th><th>Date</th><th>Remarks</th></tr></thead>
        <tbody>{rows_fee}</tbody>
      </table>
    </div>

    <!-- Warning Record -->
    <div class="warn">
      <div class="sect-h"><span class="ic">⚠</span><h2>Warning Record</h2><span class="rule"></span></div>
      <table><tbody>{rows_warn}</tbody></table>
    </div>

    <div class="sigs">
      <div class="sig"><div class="ln"></div><b>Instructor</b></div>
      <div class="sig"><div class="ln"></div><b>Campus Head</b></div>
    </div>

    <div class="foot">
      <span>Brains Group of IT Colleges · {_e(campus_name or application.campus or '')} Campus</span>
      <span>Roll {_e(s.roll_number if s else '')} · Issued {_fmt(application.submitted_at)}</span>
    </div>
  </div>
</div>
</body></html>"""
