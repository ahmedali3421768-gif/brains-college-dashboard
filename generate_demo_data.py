"""Build a 1,000-student demo database that exercises every path in the system.

Run once against a fresh database:

    python generate_demo_data.py

It writes directly through the app's own models and services, so every row obeys
the real schema and the real rules: campus roll-number sequences with no gaps,
retired roll numbers after transfers, unique receipt numbers, the four-stage
payment schedule, per-stage payment allocations, and fee totals that never
exceed the course fee.

Every value it picks (campus, course, lead source, class timing, programme,
status) is one the portals actually offer — nothing is invented.

Scenarios covered
-----------------
  1. Fully paid students (all four stages settled)
  2. Partially paid students with a live installment plan
  3. Partially paid students whose due date has PASSED (payment is blocked
     until an admin extends the date — the exact case the guard defends)
  4. Drop-outs (some after paying, some after paying nothing)
  5. Transferred students (approved, rejected, and still pending)
  6. Referral students (pending / accepted / rejected, F- roll numbers)

Plus the awkward cases that break naive code:
  · paid late (settled after the due date)
  · fee set but nothing scheduled yet
  · scheduled but nothing paid
  · a single receipt settling two stages at once
  · zero-fee (scholarship) students
  · overdue by one day vs overdue by months
  · students who paid the admission fee and then vanished
  · brand-new applications with no fee decided at all
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from app.database import Base, SessionLocal, engine
from app.models import (
    Admin, Application, ApplicationStatus, AdmissionStatus, Expense,
    Installment, InstallmentStatus, Payment, PaymentAllocation, PaymentStatus,
    Student, TransferRequest,
)
from app.services import roll_service
from app.services.schedule_service import STAGES, STAGE_KEYS

random.seed(20260714)          # deterministic — same database every run

TODAY = date.today()
NOW = datetime.now()

# ── Only values the portals actually offer ──────────────────────────────
CAMPUSES = ["Walton Road", "Queen Road", "Darogwala", "Bhagbanpura"]
LEAD_SOURCES = ["Instagram", "WhatsApp", "Facebook", "LinkedIn", "YouTube",
                "Others"]
CLASS_TIMINGS = ["Morning", "Afternoon", "Evening"]
PROGRAMME = "Short Courses"
METHODS = ["cash", "bank", "jazzcash"]

COURSES = [
    "Graphic Designing", "Digital Marketing", "Video Editing",
    "Content Writing", "Freelancing", "E-Commerce", "Amazon Virtual Assistant",
    "Social Media Marketing", "SEO", "Canva Mastery", "AI Tools",
    "Web Development", "MERN Stack", "Python Programming", "WordPress",
    "App Development", "Generative AI", "Agentic AI",
    "Computer Basics", "MS Office", "Accounting & QuickBooks",
    "Hardware & Networking", "Autocad", "Solar Technician",
    "Mobile Repairing", "Electrician", "Plumbing", "Welding",
    "Fashion Designing", "Beautician Course", "Cooking & Baking",
    "CCTV Course", "Auto EFI Scanner Training", "Shopify",
    "6 in 1", "3 in 1",
]

FIRST = ["Ahmed", "Ali", "Hassan", "Bilal", "Usman", "Hamza", "Zain", "Owais",
         "Saad", "Faizan", "Tayyab", "Danish", "Umar", "Kashif", "Adeel",
         "Sara", "Ayesha", "Fatima", "Hira", "Maryam", "Zainab", "Noor",
         "Iqra", "Amna", "Rabia", "Sana", "Laiba", "Areeba", "Mahnoor"]
LAST = ["Khan", "Ali", "Hussain", "Ahmed", "Malik", "Butt", "Sheikh", "Raza",
        "Iqbal", "Javed", "Aslam", "Nawaz", "Riaz", "Farooq", "Saeed",
        "Chaudhry", "Qureshi", "Abbasi", "Zafar", "Mehmood"]
CITIES = ["Lahore", "Kasur", "Sheikhupura", "Gujranwala", "Faisalabad",
          "Okara", "Sahiwal", "Nankana Sahib"]
INSTRUCTORS = ["Muhammad Bilal", "Ayesha Tariq", "Usman Ghani", "Hina Shah",
               "Kamran Akmal", "Sadia Rehman", "Fahad Mustafa", "Nida Yasir"]

_used_receipts: set[str] = set()
_receipt_seq = 1000


def receipt(prefix: str) -> str:
    """A receipt number that is unique across the whole database."""
    global _receipt_seq
    while True:
        _receipt_seq += 1
        rn = f"{prefix}-{_receipt_seq}"
        if rn.lower() not in _used_receipts:
            _used_receipts.add(rn.lower())
            return rn


def person() -> tuple[str, str]:
    return f"{random.choice(FIRST)} {random.choice(LAST)}", \
           f"{random.choice(['Muhammad', 'Abdul', 'Ghulam'])} {random.choice(LAST)}"


def phone() -> str:
    return f"03{random.randint(0, 4)}{random.randint(0, 9)}-{random.randint(1000000, 9999999)}"


def cnic() -> str:
    return f"35201-{random.randint(1000000, 9999999)}-{random.randint(1, 9)}"


class RollBook:
    """Hands out roll numbers exactly the way roll_service does.

    Each campus keeps its own strict sequence (W-1, W-2 … / B-1, B-2 …).
    Referral roll numbers use the F- prefix and take the next number that is
    free across BOTH that campus's sequence and every F- number already issued
    — which is why a single global F- counter is kept here, mirroring
    ``roll_service.next_referral_roll``.
    """

    def __init__(self):
        self.next_num = {c: 1 for c in CAMPUSES}
        self.f_high = 0                       # highest F- number issued anywhere

    def take(self, campus: str, referral: bool = False) -> str:
        if not referral:
            n = self.next_num[campus]
            self.next_num[campus] = n + 1
            return f"{roll_service.prefix_for(campus)}-{n}"

        # referral: next number free across this campus AND all F- numbers
        campus_high = self.next_num[campus] - 1
        n = max(campus_high, self.f_high) + 1
        self.f_high = n
        return f"F-{n}"


ROLLS = RollBook()


def make_student(db, campus: str, referral: bool = False,
                 days_ago: int = 0) -> tuple[Student, Application]:
    name, father = person()
    submitted = NOW - timedelta(days=days_ago,
                                hours=random.randint(0, 9))
    s = Student(
        roll_number=ROLLS.take(campus, referral),
        full_name=name, father_name=father,
        cnic=cnic(), phone=phone(),
        guardian_phone=phone() if random.random() < 0.75 else "",
        email=(f"{name.split()[0].lower()}{random.randint(10, 999)}@gmail.com"
               if random.random() < 0.6 else None),
        gender=random.choice(["Male", "Female"]),
        city=random.choice(CITIES),
        address=f"House {random.randint(1, 400)}, Street {random.randint(1, 40)}",
        created_at=submitted,
    )
    db.add(s)
    db.flush()

    course = random.choice(COURSES)
    dur = random.choice([1, 2, 3, 3, 3, 6, 6, 12])
    a = Application(
        application_no=f"APP-2026-{s.id:05d}",
        student_id=s.id,
        programme_category=PROGRAMME,
        course_name=course,
        session="",
        lead_source=random.choice(LEAD_SOURCES),
        campus=campus,
        class_time=random.choice(["9:00 AM – 11:00 AM", "2:00 PM – 4:00 PM",
                                  "6:00 PM – 8:00 PM"]),
        lab_time=random.choice(["11:00 AM – 12:00 PM", "4:00 PM – 5:00 PM", ""]),
        instructor_name=random.choice(INSTRUCTORS),
        course_duration_months=dur,
        is_referral=referral,
        application_status=ApplicationStatus.APPROVED,
        admission_status=AdmissionStatus.ENROLLED,
        payment_status=PaymentStatus.UNPAID,
        total_fee=0,
        submitted_at=submitted,
        extra_fields=f'{{"class_timing": "{random.choice(CLASS_TIMINGS)}"}}',
    )
    db.add(a)
    db.flush()
    return s, a


def build_schedule(db, a: Application, total: float,
                   due_dates: list[date | None]) -> list[Installment]:
    """Create the four stages. Amounts always add up to exactly total_fee."""
    adm = round(total * 0.25, -2)
    test = round(total * 0.10, -2)
    rest = total - adm - test
    first = round(rest / 2, -2)
    second = total - adm - test - first          # exact remainder, no rounding drift
    amounts = [adm, first, second, test]

    rows = []
    for idx, ((key, label), amt, due) in enumerate(
            zip(STAGES, amounts, due_dates), start=1):
        i = Installment(
            application_id=a.id, number=idx, label=label, stage=key,
            amount=float(amt), due_date=due,
            status=InstallmentStatus.PENDING, paid_amount=0,
        )
        db.add(i)
        rows.append(i)
    db.flush()
    return rows


def pay_stage(db, a: Application, inst: Installment, when: date,
              rn: str | None = None, method: str | None = None,
              amount: float | None = None,
              payment_written: bool = False) -> str:
    """Settle a stage on a given day, writing the payment, the allocation and
    the receipt exactly as the app does.

    One receipt number = ONE row in `payments` (the table has a unique index on
    it), but that single receipt may settle more than one stage — each stage it
    touches gets its own row in `payment_allocations`. Pass
    ``payment_written=True`` for the second stage covered by the same receipt so
    the payment row is not written twice.
    """
    amt = float(amount if amount is not None else inst.amount)
    if amt <= 0:
        return ""
    rn = rn or receipt(random.choice(["RC", "AF", "INS"]))
    method = method or random.choice(METHODS)
    stamp = datetime.combine(when, datetime.min.time()) + timedelta(
        hours=random.randint(9, 17))

    inst.paid_amount = round((inst.paid_amount or 0) + amt, 2)
    inst.paid_at = stamp
    inst.paid_method = method
    inst.receipt_number = rn
    inst.recorded_by_name = "Campus Admin"
    if inst.paid_amount >= (inst.amount or 0):
        inst.status = InstallmentStatus.PAID

    if not payment_written:
        db.add(Payment(application_id=a.id, amount=amt, method=method,
                       receipt_number=rn, reference=inst.label,
                       status="verified", created_at=stamp, verified_at=stamp))
    db.add(PaymentAllocation(
        application_id=a.id, installment_id=inst.id, stage=inst.stage,
        amount=amt, receipt_number=rn, method=method, paid_on=when,
        recorded_by_name="Campus Admin", created_at=stamp))
    return rn


def refresh_totals(db, a: Application, rows: list[Installment]) -> None:
    paid = round(sum(i.paid_amount or 0 for i in rows), 2)
    total = a.total_fee or 0
    if total <= 0 or paid <= 0:
        a.payment_status = PaymentStatus.UNPAID
    elif paid >= total - 0.01:
        a.payment_status = PaymentStatus.FULLY_PAID
    else:
        a.payment_status = PaymentStatus.PARTIALLY_PAID
    a.eligibility_status = ("eligible" if total > 0 and paid >= total * 0.75
                            else "not_eligible")


def d(days: int) -> date:
    return TODAY + timedelta(days=days)


# ═══════════════════════════════════════════════════════════════════════
def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(Student).count():
        print("Students already exist — refusing to double-seed.")
        print("Delete brains_college.db and re-run.")
        db.close()
        return

    counts: dict[str, int] = {}

    def tally(k: str) -> None:
        counts[k] = counts.get(k, 0) + 1

    # ── 1. FULLY PAID — 260 ────────────────────────────────────────────
    # All four stages settled. Some paid every stage on its own day, some
    # cleared two stages with a single receipt.
    for n in range(260):
        campus = CAMPUSES[n % 4]
        s, a = make_student(db, campus, days_ago=random.randint(45, 300))
        total = random.choice([20000, 25000, 30000, 35000, 40000, 45000])
        a.total_fee = total
        start = TODAY - timedelta(days=random.randint(40, 260))
        rows = build_schedule(db, a, total,
                              [start, start + timedelta(30),
                               start + timedelta(60), start + timedelta(85)])
        if n % 7 == 0:
            # ONE receipt clears the admission fee AND the first installment —
            # one payment row, two stage allocations
            rn = receipt("RC")
            pay_stage(db, a, rows[0], start, rn=rn, method="cash")
            pay_stage(db, a, rows[1], start, rn=rn, method="cash",
                      payment_written=True)
            for i in rows[2:]:
                pay_stage(db, a, i, i.due_date)
            tally("fully paid (one receipt settling two stages)")
        else:
            for i in rows:
                # a few settle a day or two early
                pay_stage(db, a, i, i.due_date - timedelta(random.randint(0, 2)))
            tally("fully paid")
        refresh_totals(db, a, rows)

    # ── 2. PARTIALLY PAID, plan still running — 250 ────────────────────
    # Paid what was due; the remaining stages fall due in the future.
    for n in range(250):
        campus = CAMPUSES[n % 4]
        s, a = make_student(db, campus, days_ago=random.randint(10, 90))
        total = random.choice([20000, 25000, 30000, 36000, 42000])
        a.total_fee = total
        start = TODAY - timedelta(days=random.randint(10, 60))
        rows = build_schedule(db, a, total,
                              [start, start + timedelta(30),
                               d(random.randint(10, 40)),
                               d(random.randint(45, 75))])
        pay_stage(db, a, rows[0], start)
        if random.random() < 0.7:
            pay_stage(db, a, rows[1], rows[1].due_date)
            tally("partial — 2 of 4 stages paid")
        else:
            tally("partial — admission fee only")
        # a handful pay half of the next stage
        if random.random() < 0.15:
            half = round((rows[2].amount or 0) / 2, -2)
            if half > 0:
                pay_stage(db, a, rows[2], TODAY - timedelta(1), amount=half)
                tally("partial — part-paid a single stage")
        refresh_totals(db, a, rows)

    # ── 3. PARTIALLY PAID, DUE DATE HAS PASSED — 190 ───────────────────
    # The blocking case: money cannot be taken until an admin extends the date.
    for n in range(190):
        campus = CAMPUSES[n % 4]
        s, a = make_student(db, campus, days_ago=random.randint(60, 240))
        total = random.choice([25000, 30000, 35000, 40000])
        a.total_fee = total
        start = TODAY - timedelta(days=random.randint(90, 200))
        # how badly overdue? 1 day … 5 months
        late = random.choice([1, 2, 5, 9, 15, 22, 40, 65, 90, 150])
        rows = build_schedule(db, a, total,
                              [start, start + timedelta(30),
                               d(-late), d(-late + 30)])
        pay_stage(db, a, rows[0], start)
        if random.random() < 0.75:
            # settled the first installment, but LATE — a real "Paid Late" row
            if random.random() < 0.4:
                pay_stage(db, a, rows[1],
                          rows[1].due_date + timedelta(random.randint(3, 20)))
                tally("overdue — earlier stage was paid late")
            else:
                pay_stage(db, a, rows[1], rows[1].due_date)
                tally("overdue — payment blocked until extended")
        else:
            tally("overdue — admission fee only, badly behind")
        refresh_totals(db, a, rows)

    # ── 4. DROP-OUTS — 90 ──────────────────────────────────────────────
    for n in range(90):
        campus = CAMPUSES[n % 4]
        s, a = make_student(db, campus, days_ago=random.randint(60, 320))
        total = random.choice([20000, 30000, 40000])
        a.total_fee = total
        start = TODAY - timedelta(days=random.randint(70, 300))
        rows = build_schedule(db, a, total,
                              [start, start + timedelta(30),
                               start + timedelta(60), start + timedelta(90)])
        r = random.random()
        if r < 0.45:
            pay_stage(db, a, rows[0], start)
            tally("drop-out — paid admission fee then left")
        elif r < 0.75:
            pay_stage(db, a, rows[0], start)
            pay_stage(db, a, rows[1], rows[1].due_date)
            tally("drop-out — left mid-plan, money outstanding")
        else:
            tally("drop-out — never paid a rupee")
        a.application_status = ApplicationStatus.DROPPED_OUT
        a.admission_status = AdmissionStatus.NOT_ADMITTED
        a.remarks = random.choice([
            "Stopped attending after 3 weeks.",
            "Moved to another city.",
            "Financial difficulty — could not continue.",
            "Found a job, dropped the course.",
        ])
        refresh_totals(db, a, rows)

    # ── 5. TRANSFERRED STUDENTS — 70 ───────────────────────────────────
    # 40 approved (already moved, old roll retired), 15 rejected, 15 pending.
    for n in range(70):
        src = CAMPUSES[n % 4]
        dst = CAMPUSES[(n + 1 + (n % 3)) % 4]
        if dst == src:
            dst = CAMPUSES[(n + 2) % 4]

        s, a = make_student(db, src, days_ago=random.randint(50, 200))
        total = random.choice([25000, 30000, 35000])
        a.total_fee = total
        start = TODAY - timedelta(days=random.randint(45, 180))
        rows = build_schedule(db, a, total,
                              [start, start + timedelta(30),
                               d(random.randint(5, 50)), d(random.randint(55, 95))])
        pay_stage(db, a, rows[0], start)
        if random.random() < 0.6:
            pay_stage(db, a, rows[1], rows[1].due_date)
        refresh_totals(db, a, rows)

        old_roll = s.roll_number
        req = TransferRequest(
            application_id=a.id, from_campus=src, to_campus=dst,
            reason=random.choice(["Student moved house.",
                                  "Closer to home.",
                                  "Preferred class timing available there.",
                                  "Requested by parent."]),
            student_name=s.full_name, current_roll=old_roll,
            course=a.course_name,
            requested_by_id=0, requested_by_name=f"{src} Admin",
            created_at=NOW - timedelta(days=random.randint(1, 30)),
        )

        if n < 40:
            # APPROVED — the student really moved, the old roll is burnt
            new_roll = ROLLS.take(dst)
            a.previous_roll_number = old_roll
            a.transferred_from = src
            a.transferred_at = NOW - timedelta(days=random.randint(1, 25))
            a.campus = dst
            s.roll_number = new_roll
            req.status = "approved"
            req.new_roll = new_roll
            req.decided_by_name = f"{dst} Admin"
            req.decided_at = a.transferred_at
            tally("transferred — approved, old roll retired")
        elif n < 55:
            req.status = "rejected"
            req.decided_by_name = f"{dst} Admin"
            req.decided_at = NOW - timedelta(days=random.randint(1, 20))
            tally("transfer rejected — student stayed put")
        else:
            req.status = "pending"
            tally("transfer request awaiting approval")
        db.add(req)

    # ── 6. REFERRAL STUDENTS — 90 ──────────────────────────────────────
    # The referral portal only serves Darogwala and Bhagbanpura.
    for n in range(90):
        campus = "Darogwala" if n % 2 == 0 else "Bhagbanpura"
        s, a = make_student(db, campus, referral=True,
                            days_ago=random.randint(2, 120))
        a.referral_user_id = 1
        a.lead_source = random.choice(LEAD_SOURCES)

        r = random.random()
        if r < 0.45:
            # accepted, enrolled, paying normally
            a.referral_status = "accepted"
            a.referral_enrolled = True
            a.referral_enrolled_at = a.submitted_at + timedelta(days=2)
            a.referral_decided_by = f"{campus} Admin"
            a.referral_decided_at = a.submitted_at + timedelta(days=1)
            total = random.choice([25000, 30000, 35000])
            a.total_fee = total
            start = TODAY - timedelta(days=random.randint(10, 90))
            rows = build_schedule(db, a, total,
                                  [start, start + timedelta(30),
                                   d(random.randint(5, 40)), d(random.randint(45, 80))])
            pay_stage(db, a, rows[0], start)
            if random.random() < 0.55:
                pay_stage(db, a, rows[1], rows[1].due_date)
            if random.random() < 0.2:
                for i in rows[2:]:
                    pay_stage(db, a, i, TODAY - timedelta(random.randint(1, 5)))
            refresh_totals(db, a, rows)
            tally("referral — accepted and paying")
        elif r < 0.65:
            a.referral_status = "rejected"
            a.referral_decided_by = f"{campus} Admin"
            a.referral_decided_at = a.submitted_at + timedelta(days=1)
            a.referral_remarks = random.choice([
                "Seats full for this course.",
                "Could not verify documents.",
                "Student did not respond.",
            ])
            a.admission_status = AdmissionStatus.NOT_ADMITTED
            tally("referral — rejected by campus")
        else:
            # still waiting for the campus admin to decide
            a.referral_status = "pending"
            a.admission_status = AdmissionStatus.NOT_ADMITTED
            a.application_status = ApplicationStatus.PENDING
            tally("referral — pending decision")

    # ── 7. THE AWKWARD ONES — 50 ───────────────────────────────────────
    # These are the rows that break code written for the happy path.
    #   260 + 250 + 190 + 90 + 70 + 90 + 50  =  1,000 students
    for n in range(50):
        campus = CAMPUSES[n % 4]
        s, a = make_student(db, campus, days_ago=random.randint(0, 20))
        kind = n % 8

        if kind == 0:
            # fee agreed, schedule never built
            a.total_fee = random.choice([25000, 30000])
            tally("edge — fee set, no schedule yet")

        elif kind == 1:
            # schedule built, not a rupee paid, first date already gone
            a.total_fee = 30000
            build_schedule(db, a, 30000,
                           [d(-12), d(20), d(50), d(80)])
            tally("edge — scheduled, nothing paid, already overdue")

        elif kind == 2:
            # scholarship: zero fee, nothing to collect
            a.total_fee = 0
            a.payment_status = PaymentStatus.FULLY_PAID
            a.eligibility_status = "eligible"
            a.remarks = "Full scholarship — merit award."
            tally("edge — zero fee (scholarship)")

        elif kind == 3:
            # overdue by exactly one day (boundary)
            a.total_fee = 24000
            rows = build_schedule(db, a, 24000,
                                  [d(-40), d(-1), d(30), d(60)])
            pay_stage(db, a, rows[0], d(-40))
            refresh_totals(db, a, rows)
            tally("edge — overdue by exactly one day")

        elif kind == 4:
            # due TODAY — still payable, not yet overdue
            a.total_fee = 28000
            rows = build_schedule(db, a, 28000,
                                  [d(-30), TODAY, d(30), d(60)])
            pay_stage(db, a, rows[0], d(-30))
            refresh_totals(db, a, rows)
            tally("edge — due today (boundary)")

        elif kind == 5:
            # brand-new application, nothing decided at all
            a.application_status = ApplicationStatus.PENDING
            a.admission_status = AdmissionStatus.NOT_ADMITTED
            a.total_fee = 0
            tally("edge — brand-new, no fee decided")

        elif kind == 6:
            # on hold
            a.application_status = ApplicationStatus.ON_HOLD
            a.total_fee = 30000
            rows = build_schedule(db, a, 30000,
                                  [d(5), d(35), d(65), d(95)])
            a.remarks = "On hold — waiting for documents."
            refresh_totals(db, a, rows)
            tally("edge — on hold, schedule ready, unpaid")

        else:
            # every stage paid late — the whole plan slipped
            a.total_fee = 32000
            start = TODAY - timedelta(days=150)
            rows = build_schedule(db, a, 32000,
                                  [start, start + timedelta(30),
                                   start + timedelta(60), start + timedelta(90)])
            for i in rows:
                pay_stage(db, a, i,
                          i.due_date + timedelta(random.randint(5, 25)))
            refresh_totals(db, a, rows)
            tally("edge — every single stage paid late")

    # ── Expenses, so the expense module and its reports have real data ──
    cats = ["Rent", "Utilities", "Salaries", "Marketing", "Equipment",
            "Furniture", "Stationery", "Maintenance", "Internet", "Misc"]
    vendors = ["Al-Noor Traders", "Lahore Electric", "PakNet ISP",
               "City Stationers", "Metro Cash & Carry", "Hafeez Centre",
               "Tech Solutions", "Ravi Printers"]
    for _ in range(240):
        campus = random.choice(CAMPUSES)
        when = NOW - timedelta(days=random.randint(0, 180))
        db.add(Expense(
            title=f"{random.choice(cats)} — {when.strftime('%b %Y')}",
            category=random.choice(cats),
            amount=float(random.choice([3500, 8000, 12000, 25000, 45000,
                                        60000, 120000])),
            vendor=random.choice(vendors),
            payment_method=random.choice(["cash", "bank", "jazzcash", "other"]),
            campus=campus,
            description="Recorded from campus petty cash book.",
            purchase_date=when.date(),
            created_at=when,
            recorded_by_name=f"{campus} Admin",
        ))

    db.commit()

    # ── Roll-number settings, so the next real admission continues cleanly ──
    from app.models import CampusRollSetting
    for c in CAMPUSES:
        row = (db.query(CampusRollSetting)
               .filter(CampusRollSetting.campus == c).first())
        if not row:
            row = CampusRollSetting(campus=c)
            db.add(row)
        row.start_number = 1
    db.commit()

    # ── Report ─────────────────────────────────────────────────────────
    total_students = db.query(Student).count()
    print(f"\n  {total_students} students created\n")
    for k in sorted(counts):
        print(f"    {counts[k]:>4}  {k}")

    print("\n  By campus")
    for c in CAMPUSES:
        n = db.query(Application).filter(Application.campus == c).count()
        nxt = roll_service.next_roll(db, c)
        print(f"    {c:<14} {n:>4} students   next roll: {nxt}")

    print(f"\n    {db.query(Expense).count()} expenses")
    print(f"    {db.query(Payment).count()} payments")
    print(f"    {db.query(PaymentAllocation).count()} stage allocations")
    print(f"    {db.query(TransferRequest).count()} transfer requests")
    db.close()


if __name__ == "__main__":
    main()
