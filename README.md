# Brains College — Admission Management & Chatbot Portal

Your existing FastAPI chatbot, upgraded into a full admission management system.
The chatbot behaves exactly as before — but now **every conversation is saved
permanently**, **leads and applications go to a real database** (Google Sheets is
gone), and a modern **admin dashboard** at `/admin` gives you live monitoring,
analytics, search, and exports.

---

## What changed vs. the old project

| Before | Now |
|---|---|
| Leads pushed to Google Sheets | Leads stored in the database, managed at `/admin` → Leads |
| Chats vanished after the reply | Every message saved forever, grouped into sessions (ChatGPT-style history) |
| No student applications | Full admission form (`/apply`) + `/api/applications` endpoint |
| No admin panel | Dashboard, live chat monitor, analytics, exports, notifications |
| No authentication | JWT login with roles: `super_admin`, `admin`, `staff` |
| No fee workflow | Auto-generated **challan PDFs**, JazzCash receipt upload, cash verification, "All Challans" |
| No student self-service | **Student Portal** at `/portal` — status, challan download, receipt upload |
| Repeated notifications | **Smart notification engine** — duplicates blocked by content hash + fee-due reminder jobs |
| A4 challan saved as a file | **Thermal/POS receipt** opened in the browser and printed with Ctrl+P — nothing stored on disk |
| Manual payment editing | **Installment ledger** — advance/75%/100% rules auto-set payment status & class eligibility |
| Chatbot separate | Deployed chatbot **embedded** in the dashboard; conversations & leads flow into their sections |
| Application № as identifier | **Roll Number** is the unique primary identifier; search is by Roll Number only |
| Flat course list | Two-level **Programme Category → Course** catalog (Intermediate / Short Courses) |
| Simple approval | Payment approval **requires a Receipt Number**, stored permanently |
| PKR 5,000 advance | First installment is now **PKR 1,000** |
| No expense tracking | **Expense Management**: expenses, budgets, and a spending dashboard |
| No marketing data | **Lead Source** on every application (Instagram/WhatsApp/… ) with filters, exports & analytics |

**Backward compatible:** `/api/chat` and `/api/lead` keep the exact same
request/response shapes, so your deployed website widget keeps working with
**zero changes**. (An optional one-line upgrade is described below.)

---

## Quick start (local)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure
cp .env.example .env          # then edit .env — at minimum set GROQ_API_KEY and SECRET_KEY

# 3. IMPORTANT — keep your existing prompt.py!
#    This repo ships prompt.py.example only. Your customised prompt.py from the
#    old project must stay in the project root. (If it's missing, copy
#    prompt.py.example → prompt.py and edit it.)

# 4. Run
uvicorn main:app --reload
```

On first boot the app creates all tables (SQLite file `brains_college.db` by
default), seeds a **super admin**, and seeds default departments/courses.

| URL | What it is |
|---|---|
| `/` | Your website / chatbot page (`static/index.html`, untouched) |
| `/apply` | Public online admission form (returns a downloadable fee challan) |
| `/portal` | Student portal — check status, download challan, upload payment receipt |
| `/admin` | Admin dashboard (login required) |
| `/docs` | Interactive API documentation |

### Default login (change immediately!)

```
Email:    admin@brainscollege.edu.pk
Password: Admin@123
```

Set `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD` in `.env` **before first boot**
to seed different credentials, and change the password from
`/admin` → Settings after signing in.

---

## Environment variables (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `GROQ_API_KEY` | ✅ | Same key as before; chatbot returns 503 without it |
| `GROQ_MODEL` | — | Defaults to `meta-llama/llama-4-scout-17b-16e-instruct` |
| `SECRET_KEY` | ✅ | Long random string — signs the admin JWTs |
| `DATABASE_URL` | — | Defaults to SQLite; use Render Postgres URL in production |
| `ALLOWED_ORIGINS` | — | Comma-separated origins for CORS (default `*`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | Admin session length (default 480 = 8 h) |
| `SUPER_ADMIN_NAME/EMAIL/PASSWORD` | — | Seeded on first boot only |
| `TIMEZONE` | — | Default `Asia/Karachi` — used for “today / this month” stats |
| `CHALLAN_DEFAULT_AMOUNT` | — | Fee printed on challans (default 5000); per-course fees via `courses.admission_fee` |
| `CHALLAN_DUE_DAYS` | — | Days until a new challan is due (default 7) |
| `JAZZCASH_ACCOUNT` | — | JazzCash number printed on challans |
| `COLLEGE_NAME` / `COLLEGE_ADDRESS` / `COLLEGE_PHONE` | — | Shown on challan PDFs |
| `UPLOADS_DIR` | — | Folder for challan PDFs and uploaded receipts (default `uploads/`) |
| `SESSION_REUSE_MINUTES` | — | Group anonymous chat messages within N minutes (default 30) |

**Removed (delete from Render):** `GOOGLE_CREDENTIALS`, `GOOGLE_SHEET_ID` — the
Google Sheets integration is gone. You can also remove `gspread` and
`google-auth` from your environment.

---

## Deploying on Render

1. Push this project to your repo — Render redeploys as usual
   (`uvicorn main:app --host 0.0.0.0 --port $PORT`).
2. **Add a PostgreSQL database** (Render → New → PostgreSQL). SQLite works, but
   Render's disk is ephemeral on free plans, so Postgres is strongly
   recommended for permanent storage. Copy the *Internal Database URL* into
   `DATABASE_URL`. (`postgres://…` URLs are handled automatically.)
3. Set env vars: `GROQ_API_KEY`, `SECRET_KEY`, `DATABASE_URL`,
   `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD`, and set `ALLOWED_ORIGINS` to
   your website's domain(s).
4. Delete `GOOGLE_CREDENTIALS` and `GOOGLE_SHEET_ID`.
5. Deploy — tables are created automatically. Sign in at `https://your-app/admin`.

---

## Fee & challan workflow (redesigned)

**Challans are print-only now.** Opening a challan shows a clean POS/thermal
receipt (80 mm) that the office prints with Ctrl+P — no downloads, no files on
the server. Put your logo at `static/img/logo.png` and it appears on every
challan (otherwise a "B" badge is shown).

**Installments are the single source of truth.** Each application has a fee
ledger the admission office manages from the application page:

- Set the **total fee** and **fee category**.
- Add / edit / delete **installments** (amount, due date, label).
- **Extend a due date** — the challan instantly shows the latest one.
- **Mark installments paid** or **Record a payment** (auto-applied to the
  oldest unpaid installments).

The system then applies these rules automatically, everywhere:

| Rule | Effect |
|---|---|
| Advance (1st installment) paid | Application → **Approved**, student **Not eligible** for classes yet |
| Paid ≥ **75%** of total fee | Student becomes **Eligible for classes** |
| Paid **100%** | Payment **Fully Paid** (green), admission → **Admitted** |

Payment status colours are consistent across the whole system:
**Unpaid** (red) · **Partially Paid** (yellow) · **Fully Paid** (green).

## Chatbot integration

Your deployed chatbot (`http://brainscollagenewchat.onrender.com/`) is embedded
as a floating launcher in the dashboard (bottom-right). Conversations recorded
by this backend appear under **Conversations**, and chatbot lead submissions
appear under **Leads**. To point at a different bot, edit the `data-src` of
`#bcChatFrame` in `static/admin/index.html`.

## JazzCash receipt upload (unchanged)

The earlier online-payment flow still works alongside the ledger:

1. Student submits `/apply` → a challan + advance installment are created.
2. **JazzCash:** student pays, opens `/portal`, and uploads the receipt
   (PDF/JPG/PNG ≤ 10 MB, duplicate transaction IDs rejected).
3. **Cash:** student pays at the college; admin uses the Challans page buttons.
4. Admin verifies in **Payments** → approving records the payment against the
   ledger, so statuses and eligibility update automatically.

### Old fee-workflow note (kept for reference)

1. Student submits `/apply` → a challan (`CH-2026-00001`) with PDF is generated
   automatically and offered for download.
2. **JazzCash:** student pays, then opens `/portal`, finds their application
   (application № + CNIC/phone) and uploads the receipt (PDF/JPG/PNG ≤ 10 MB,
   with transaction ID — duplicates rejected).
3. **Cash:** student pays at the college; admin uses the *Received / Approve /
   Reject* buttons on the Challans page.
4. Admin verifies in **Payments** → *Approve* sets the challan to PAID, the
   application payment to VERIFIED and the application to eligible/APPROVED —
   the student-facing statuses update instantly in the portal. *Reject* /
   *Request re-upload* notify and let the student upload again; old receipts
   are kept forever for audit, and approved receipts are locked.
5. Every action (created / uploaded / verified / rejected / downloaded) is
   written to the audit log with the admin and IP address.

**Note for Render:** challans are no longer stored (print-only), but uploaded JazzCash *receipts* are files on disk. On
Render's ephemeral disk they vanish on redeploys — challan PDFs regenerate
automatically, but receipts do not, so attach a Render **Persistent Disk**
mounted at the app folder's `uploads/` path (or set `UPLOADS_DIR` to the disk
mount) if you use the JazzCash upload flow in production.

## Importing your old Google Sheets leads

Your previous deployment stored leads in Google Sheets. To bring them in:
Google Sheet → File → Download → **CSV**, then run:

```bash
python scripts/import_leads.py path/to/leads.csv
```

Column names like Name/Phone/Campus/Timestamp are detected automatically and
re-running the script never creates duplicates. (Old chatbot *conversations*
cannot be imported — the old code never saved them anywhere. They start being
recorded the moment this version is deployed.)

## Optional: 1-line widget upgrade (better chat grouping)

Old widgets work as-is — the server groups anonymous messages from the same
visitor within 30 minutes. For **perfect** session grouping, have your widget
remember the `session_id` the API now returns:

```js
// when sending a chat message:
const body = {
  messages: chatHistory,
  session_id: localStorage.getItem('bc_chat_session') || undefined,
};
const res = await fetch('/api/chat', { method: 'POST',
  headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
const data = await res.json();
if (data.session_id) localStorage.setItem('bc_chat_session', data.session_id);
```

If your lead form lives inside the chat widget, also send the same
`session_id` to `/api/lead` — the dashboard will then show *who* each
conversation belongs to, and link chats to their admission application
automatically when the phone numbers match.

---

## Roles

| Role | Can do |
|---|---|
| `staff` | Read everything: applications, chats, leads, analytics, exports |
| `admin` | Everything staff can + change statuses, edit applications, add notes, manage leads, link chats |
| `super_admin` | Everything + manage admin accounts, add departments/courses, delete conversations |

Manage accounts at `/admin` → Admin Accounts (super admin only).

---

## Key API endpoints

Public (no auth):
- `POST /api/chat` — chatbot (unchanged contract; now also returns `session_id`)
- `POST /api/lead` — quick lead (unchanged contract)
- `POST /api/applications` — admission form submission
- `GET  /api/meta/form-options` — campuses/departments/courses for the form
- `GET  /api/health`

Admin (Bearer token from `POST /api/auth/login`):
- `GET /api/admin/applications` — search, filters, sorting, pagination
- `PATCH /api/admin/applications/{id}/status` — approve/reject/hold, payment, admission
- `GET /api/admin/applications/{id}/pdf` — printable application sheet
- `GET /api/admin/chats` / `GET /api/admin/chats/{session_id}` — conversation history
- `GET /api/admin/analytics/overview | /applications | /chats`
- `GET /api/admin/exports/{applications|chats|leads|analytics}?format=csv|xlsx|pdf`
- `GET /api/admin/search?q=…` — global search
- `WS  /ws/admin?token=…` — live events for the dashboard

Full interactive docs at `/docs`.

---

## Project structure

```
main.py                     FastAPI app, routers, static serving
prompt.py                   ← YOUR existing system prompt (not in repo; keep it!)
prompt.py.example           fallback template
app/
  config.py  database.py  seed.py
  models/                   SQLAlchemy tables (see docs/DATABASE.md)
  schemas/                  Pydantic validation + serializers
  auth/                     bcrypt + JWT + role dependencies
  services/                 chat logging, analytics, exports, notifications, WebSocket hub
  routers/                  API endpoints by feature
  utils/                    pagination, rate limiting, request metadata, timezone
static/
  index.html                ← your existing website/chatbot page (keep yours)
  apply.html                public admission form
  admin/                    dashboard (login.html, index.html, css/, js/)
docs/DATABASE.md            schema + ER diagram
```

## Security notes

- Passwords hashed with bcrypt; JWTs expire (default 8 h); rate limiting on
  login (8/min), chat (20/min), lead (10/min) and application (5/min) endpoints.
- All SQL goes through the SQLAlchemy ORM (parameterised — no SQL injection).
- The dashboard escapes every server value before rendering (XSS-safe), and
  auth uses the `Authorization` header rather than cookies (CSRF-resistant).
- Set a strong `SECRET_KEY` and a real `ALLOWED_ORIGINS` list in production.

## Applications, Roll Numbers & Programme catalog

Every applicant now has a unique **Roll Number** — the primary identifier used
in listings, search, receipts, reports and exports. Duplicate roll numbers are
rejected ("An application with Roll Number {X} already exists.").

Admission staff create applications straight from the panel with
**Applications → Create New Application**. The form is two-level: choose a
**Programme Category** (Intermediate or Short Courses), and the **Course**
dropdown updates to that category's list. Courses live in one file —
`app/catalog.py` (`PROGRAMME_CATALOG`) — so editing that dict updates every
dropdown, the public form, and validation at once.

Search on the Applications page is **by Roll Number only** (fast and exact,
since roll numbers are unique). Filters cover programme category, status,
payment, admission, lead source, session and date range. Every application has
a **Delete** button (with a confirmation dialog) for mistakes.

## Receipt Numbers on payment approval

Approving any payment — a JazzCash receipt, a cash challan, marking an
installment paid, or recording a payment — now **requires a Receipt Number**.
It is stored permanently on the payment and shown in the application's payment
history, the printable receipt, reports and exports. The first installment
(advance) defaults to **PKR 1,000** (`CHALLAN_DEFAULT_AMOUNT`).

Open a student's application and click **Download Receipt** for a clean,
printable payment receipt (student + roll number + receipt number + full
installment history), ready for Ctrl+P.

## Lead Source (marketing)

The application form asks **"How did you hear about us?"** (required):
Instagram, WhatsApp, Facebook, LinkedIn, YouTube, or Others (which then
requires a "Please specify" note). The lead source shows in the applications
list, the detail page, reports and exports, has its own **filter** on the
Applications page, and drives a marketing breakdown on the **Analytics** page
(applications per channel).

## Expense Management

A new **Expenses** section (sidebar) with three parts:

- **Expense entry** — title, description, category, purchase date, vendor,
  amount, remarks; full create / edit / delete / search / filter.
- **Budgets** — allocate a budget per category; *spent* and *remaining* update
  automatically from expenses in that category, with a utilization bar.
- **Dashboard** — total budget, total expenses, remaining, this-month spend,
  budget utilization, a by-category doughnut and a monthly-trend chart.

All expense endpoints live under `/api/admin/expenses`, `/api/admin/budgets`
and `/api/admin/expenses-dashboard`.

## Multi-campus (4 campus admins + 1 super admin)

The system now supports **one shared database with per-campus access**. Five
logins exist out of the box:

| Login | Email | Password | Sees |
|-------|-------|----------|------|
| Super admin | admin@brainscollege.edu.pk | Admin@123 | **All campuses** combined |
| Walton Road | waltonroad@brainscollege.edu.pk | Campus@123 | Only Walton Road |
| Queen Road | queenroad@brainscollege.edu.pk | Campus@123 | Only Queen Road |
| Darogwala | darogwala@brainscollege.edu.pk | Campus@123 | Only Darogwala |
| Bhagbanpura | bhagbanpura@brainscollege.edu.pk | Campus@123 | Only Bhagbanpura |

Change these before going live via environment variables, e.g.
`CAMPUS_WALTONROAD_EMAIL`, `CAMPUS_WALTONROAD_PASSWORD` (and the same pattern
for the other campuses), plus `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`.

**What "per-campus" means:** each campus admin sees only their own campus's
applications, fees, challans, payments, leads, chatbot conversations, expenses
and budgets. Every dashboard total, chart and export is limited to their
campus. Applications they create are automatically stamped with their campus,
and they get a 404 if they try to open another campus's record by ID. The
super admin sees everything combined.

**Campus admin access:** each campus admin has the **full menu and full
control** — applications, payments, challans, leads, conversations,
notifications, expenses, analytics and settings — but every list, total, chart,
export and record they touch is automatically limited to **their own campus**.
They cannot see or edit another campus's data (a cross-campus record returns a
404, as if it doesn't exist). Only the super admin can see all campuses combined
and manage admin accounts and the global course catalog.

**Two campuses can share a budget category name** (e.g. each has its own
"Equipment" budget) — budgets are tracked per campus.

## Dashboard date-range filter

The Dashboard has a **start-date → end-date** picker at the top. Set a range
and every panel updates to that window: applications, fees & eligibility, the
application-growth chart, popular courses, **and expenses** (total spent,
by-category, and trend for the selected dates). Clear the range to return to
the all-time view. The Expenses page and its dashboard also accept the same
date range.

## Receptionist dashboard (read-only fee lookup)

A separate, deliberately minimal **Reception** panel at **`/reception`** lets
front-desk staff verify a student's fee status in seconds — nothing more. It is
**not** the admin panel: receptionists cannot edit, add, delete, approve, mark
fees paid, generate challans, export, or see any admin pages.

**Four receptionist logins (one per campus):**

| Campus | Email | Password |
|--------|-------|----------|
| Walton Road | reception.waltonroad@brainscollege.edu.pk | Reception@123 |
| Queen Road | reception.queenroad@brainscollege.edu.pk | Reception@123 |
| Darogwala | reception.darogwala@brainscollege.edu.pk | Reception@123 |
| Bhagbanpura | reception.bhagbanpura@brainscollege.edu.pk | Reception@123 |

Override per campus with `RECEPTION_WALTONROAD_EMAIL` /
`RECEPTION_WALTONROAD_PASSWORD` (and the same pattern for the others).

**What a receptionist can do:** search by student name or roll number, filter by
course / batch / fee status, and open a student to see a small popup. Every view
shows only: student name, roll number, campus, course, total fee, paid fee,
pending fee, next due date and a colour-coded fee status (green = Paid,
yellow = Partially Paid, red = Pending).

**Security.** Each receptionist is hard-locked to their own campus — they can
never see or open another campus's students (a cross-campus lookup returns 404,
as if the record doesn't exist). The reception API (`/api/reception/*`) is
read-only and returns only the whitelisted fields, so CNIC, phone, address,
father's name, documents, installment history, notes and every other field are
never sent to the browser at all. All admin endpoints reject receptionists with
403, and there are no write endpoints on the reception surface — so restrictions
can't be bypassed through the URL or browser dev tools.

---

## Receipt Number Management

Every payment carries its own **unique** receipt number — advance, each installment,
each full payment, and every approved challan. Receipt numbers can never be reused.

* Admins type the receipt number when approving a payment. The field checks the
  database **as you type** and shows `❌ Receipt Number "RC-10542" already exists.`
  before you can save.
* Approval is blocked without a receipt number, and blocked if it's a duplicate
  (case-insensitive, so `rc-1` and `RC-1` can't both exist).
* A **unique database index** on `payments.receipt_number` is the final backstop,
  so even two admins approving at the same instant can't create a duplicate.

## Installment Due Students

A new page (**Installment Due** in the sidebar, Admin + Super Admin). Pick a date
and see every student whose installment falls due that day — roll number, name,
course, campus, total/paid/pending fee, current installment, due date, colour-coded
payment status (green Paid / yellow Partial / red Pending), student status and the
latest receipt number. Search by roll number or name, and filter by course and status.

## Applications — Pending Payment

The Applications table now has a **Pending Payment** column showing exactly what the
student still owes (total − paid). It updates automatically after every approved
payment — no manual maths.

## Reception — latest receipt

The reception portal now shows each student's **latest receipt number**, both in the
table and the student popup, so front-desk staff can identify the most recent payment
at a glance.

## Expenses — Budget Allocation removed

The expense module is now a clean tracker: **Record Expense, list, search, filters,
reports and export**. All budget allocation / budget limits / budget distribution has
been removed. Each expense also records a **Payment Method** (Cash / Bank Transfer /
JazzCash-EasyPaisa / Other).

## Professional exports

**Applications export** (Excel / CSV / PDF) is now a proper college report with two
sections — **RECOVERIES** (receipt number, roll, name, course, campus, total/paid/
pending fee, latest payment + date, status) and **ADMISSIONS** (the full admission
record). Branded header, summary block, styled section bars, alternating row colours,
frozen header, auto-fitted columns, PKR formatting and a grand total.

**Expense export** (Excel / CSV / PDF) is an accounting-quality report: branded header,
summary (count, total, cash / bank / JazzCash breakdowns, date range), full detail
table, grand total, page numbers and footer. Filter by date range, category, campus,
payment method or who recorded it. **Admin and Super Admin only** — receptionists get 403.

## Attendance Card

A brand-new module, completely separate from the fee challan. Open any application and
click **Print Attendance Card**.

* **Academic Information** (optional) is captured on the application form: Class Time,
  Lab Time, Instructor Name and Course Duration. Leaving them blank is fine.
* The card auto-fills the student's details and **auto-generates the course months**
  from the admission date and duration (a 3-month course gives 3 months, a 6-month
  course gives 6, and so on) — nobody types them in.
* Sections: branded header (campus / session / batch) · Student Information ·
  Course Progress (Month / Course Topic / Total Marks) · Test Session · Fee Status
  (Receipt Number / Date / Remarks × 3) · Warning Record (× 3) · signatures.
* Blank columns are left for teachers to fill in by hand after printing.
* Prints cleanly on A4. Print tracking (count, last printed, printed by) is stored.

---

# Latest update

## Challan page removed
The dedicated Challan page is gone from the admin portal (navigation, page and its
API). The **only** official printable receipt is now:

**Admissions → open a student → Download Receipt**

The public application flow, the student portal and the Payments (payment
verification) page are untouched — students can still upload payment proof and
staff still verify it.

## Receipt shows every receipt number
The receipt now carries a **Payments received** ledger listing each recorded
payment with its own receipt number:

| Payment | Amount | Receipt No | Method | Date |
|---|---|---|---|---|
| Admission Fee | Rs 5,000 | AF-1001 | Cash | 11-07-2026 |
| Installment #1 | Rs 10,000 | INS-1002 | Cash | 11-07-2026 |
| Installment #2 | Rs 8,000 | INS-1003 | Bank | 11-07-2026 |

## Campus roll numbers — prefix + strict sequence
Each campus has a fixed prefix:

| Campus | Prefix |
|---|---|
| Walton Road | `W-` |
| Queen Road | `Q-` |
| Darogwala | `D-` |
| Bhagbanpura | `B-` |

* A Darogwala admin can only create `D-…` roll numbers. `B-45`, `Q-45`, `ABC-45`
  and `45` are all rejected with a clear message.
* Roll numbers must be **consecutive**. If `D-34` is the latest, `D-35` is the only
  value accepted — `D-36` is rejected with
  *"Invalid roll number. The previous assigned roll number is D-34. The next
  available roll number is D-35."*
* **Settings → Admissions — roll numbers** lets each campus admin set their
  *starting* number (super admin sees all four campuses).
* The Create Application form **pre-fills the next roll number**, so nobody has to
  work it out by hand.

## Fee validation
Admission fee + every installment can never exceed the student's total course fee.
Recording a payment that would push the total over the course fee is rejected:
*"Total collected cannot exceed the total course fee. Total fee is Rs 30,000 and
Rs 25,000 is already paid, so at most Rs 5,000 can be recorded now."*
Enforced everywhere payments are entered — record payment, pay installment and
payment approval.

## Notifications
Every admission action now writes a notification carrying the student name, roll
number, campus, the user who did it and the timestamp: new admission, admission
updated, roll number changed, starting-roll configuration changed, fee set,
installment added, payment recorded and installment paid.

---

# Phase 3 update

## Payment schedule (four fixed stages)
Every student's fees now follow one schedule with four stages that always exist:
**Admission Fee · 1st Installment · 2nd Installment · Test Session**. On the
student's page, the *Payment schedule* table lets you set each stage's **amount**
and **due date** together and save in one click. The four amounts can never add
up to more than the finalised course fee, and a stage can't be lowered below what
was already collected for it.

## Recoveries / Admissions export with a date
The Applications **Export** dialog now has a **Report date** picker and applies the
current page filters:
* **RECOVERIES** — students who actually paid on that date, with the amount shown
  under the exact stage(s) it settled (Admission Fee / 1st / 2nd / Test Session),
  plus receipt number, total fee and pending fee. Students who paid nothing that
  day are excluded.
* **ADMISSIONS** — applications created that date, each with the full agreed
  schedule: every stage's amount and due date.

Available in Excel, CSV and PDF.

## Due-date change notifications
Editing any stage's due date raises its own notification naming the student, the
stage, the old and new dates, the campus and who made the change.

## Session removed
The **Session** field is gone from both the admin admission form and the referral
form. Nothing else about the forms changed.

---

# Latest update

## Payments are blocked once a due date has passed
If a student turns up after the deadline, the payment **cannot be recorded**. The
system returns a clear message naming the stage, the date it was due and how many
days ago that was, and tells the admin to extend the due date first.

Enforced on the **backend** too — a direct API call is rejected the same way, so
the frontend can't be bypassed.

Once an authorised user **extends** the due date, payment goes through normally.
Every extension is logged and raises a notification (student, roll number, campus,
stage, old date, new date, who changed it, when).

The payment schedule shows this plainly: a red banner (*"Payment blocked — a due
date has passed"*), the overdue row highlighted with *"N days overdue — extend to
accept payment"*, and an **Extend** button right on the row. Payments made after a
deadline are marked **Paid Late** with the number of days.

## Schedule total can never exceed the course fee
Admission Fee + 1st Installment + 2nd Installment + Test Session must add up to at
most the finalised course fee — checked on both the frontend and the backend.

## Courses
Added **6 in 1** and **3 in 1**. Admin, Super Admin and the Referral Portal now all
read the **same** course list (`/api/meta/form-options` → `programme_catalog`), so any
course added in future appears everywhere automatically. *(This also fixed a bug where
the referral form's course dropdown was reading a key that didn't exist and came up
empty.)*

---

# Update — transfer approval, referral fix, red receipt

## Two-step transfer approval
A transfer is now a **request**, not an instant move. When a campus starts a
transfer the student stays put — nothing moves, no roll number changes. The
destination campus sees the request under **Transfer Students → Pending transfer
requests** (student, current roll, source campus, course, payment status,
remaining fee, who requested it, when) and chooses **Approve** or **Reject**.

* **Approve** → the student moves, gets the next roll number at the new campus,
  all data (payments, installments, eligibility, history) travels with them, and
  the old roll number is retired forever.
* **Reject** → nothing changes; the student stays exactly as they were and the
  source campus is notified.

Only the destination campus (or the super admin) can decide. Every step —
requested, received, approved, rejected — raises a notification for both campuses.

## Referral application create — fixed
The referral form failed silently because it sent an invalid "How did you hear
about us?" value. It now has that dropdown (shared with the admin form), so
referral applications submit correctly and get their F- roll number.

## Receipt — red & white redesign
The Download Receipt page has a fresh red-and-white look: a red gradient header,
red section accents, zebra-striped tables, a summary panel and an interactive
print button. Prints cleanly with colours intact.

---

# Update — referral dashboard & Referral Applications page

## Referrals (Admissions section) — campus-scoped dashboard
The **Referrals** page now shows the referral-students dashboard for **your campus
only**. A Bhagbanpura admin sees Bhagbanpura's referrals, Darogwala sees Darogwala's,
and the super admin sees all four campuses. Tiles show total referrals, accepted /
enrolled, awaiting decision, rejected and fee collected, above a full table (student,
referral roll, course, phone, total fee, paid, remaining, status, date).

## Referral Applications — new page
Referral students stay **out of the normal Applications list** (unchanged). They now
have their own page: **Referral Applications**.

* A campus admin sees only the referrals sent to **their** campus.
* Tabs filter by **Pending / Accepted / Rejected**, with a search box for name, roll
  number or phone.
* Each pending referral has **Accept** and **Reject** buttons, with an optional
  remarks note. The decision is recorded with who made it and when, and the referral
  portal sees the outcome.
* Only the receiving campus (or the super admin) can decide — another campus gets 403.
  Receptionists cannot decide.

---

# Demo database — 1,000 students

The shipped `brains_college.db` is pre-loaded with **1,000 students** that exercise
every path in the system. It is deterministic (fixed random seed), schema-valid, and
uses only values the portals actually offer (four campuses, real courses incl.
"6 in 1" / "3 in 1", the six lead sources, Morning/Afternoon/Evening timings).

Scenario coverage:

* **Fully paid** — all four stages settled (some via a single receipt covering two stages)
* **Partially paid, plan running** — paid what was due, future installments pending
* **Partially paid, due date PASSED** — payment is blocked until an admin extends the date
* **Paid late** — settled after the due date (shows as *Paid Late* with days late)
* **Drop-outs** — some after paying the admission fee, some after paying nothing
* **Transferred** — approved (old roll retired), rejected, and still pending approval
* **Referrals** — pending / accepted / rejected, with F- roll numbers, per campus
* **Edge cases** — zero-fee scholarship, fee-with-no-schedule, overdue-by-one-day,
  due-today, brand-new (no fee), on-hold, and every-stage-paid-late

Totals: ~2,100 payments, ~2,150 stage allocations, 70 transfer requests, 240 expenses.
Each campus's roll sequence has 10 retired numbers (from approved transfers) that the
next real admission correctly skips.

Log in as the super admin (`admin@brainscollege.edu.pk` / `Admin@123`) to see all four
campuses, or as a campus admin (e.g. `bhagbanpura@brainscollege.edu.pk` / `Campus@123`)
to see one campus's slice.

## Regenerating the demo data
    rm brains_college.db
    python generate_demo_data.py     # rebuilds the same 1,000 students

## Running the app
    pip install -r requirements.txt
    uvicorn main:app                 # wait ~5s on first boot (seeds accounts)
    # open http://localhost:8000/admin

---

# New module — Money Transfer (inter-campus fee movement)

Under **Admission → Money Transfer**, one campus can move a student's *already-paid*
fee to another campus, with the same request → approve safety as student transfers.

## How it works
1. **Source campus** opens the form (source campus is fixed to the logged-in user),
   picks a destination campus, and enters the student's roll number. The student's
   name, father, course, total paid, remaining fee and **transferable balance** load
   automatically (read-only). It enters an amount and optional remarks, then sends the
   request (status **Pending**). Nothing financial changes yet.
2. **Destination campus** sees the request under Money Transfer → *Pending money
   transfers*, with the transfer number, student, amount, source campus and requester.
3. To **approve**, the destination admin must re-key the student's roll number. If it
   doesn't match the source roll, approval is blocked ("Roll number does not match").
   On a match, the amount is booked as a ledger movement: the source campus's
   collection figure drops by the amount and the destination's rises — the dashboard
   budget reflects it immediately. The student's own fee records are left untouched.
4. To **reject**, the destination admin picks a reason (Incorrect Roll Number / Wrong
   Student / Invalid Amount / Duplicate Request / Other). Nothing moves; the source
   campus is notified with the reason.

## Rules enforced (frontend + backend)
* Source and destination campus cannot be the same.
* Amount must be > 0 and cannot exceed the student's transferable balance
  (paid fee minus any amount already transferred out) — never a negative balance.
* Every transfer has a unique `MT-YYYY-NNNNN` number.
* No duplicate pending request for the same student and amount.
* Source campus cannot approve its own request (only the destination can).
* Only the requesting campus can cancel its own pending request.
* Receptionists and the referral portal have no access.

## Dashboard, reports, notifications, audit
* Dashboard widget: today's transfers, pending, incoming/outgoing approved amounts.
* Money Transfer report with filters (status, source, destination) — Excel / CSV / PDF.
* Search by transfer number, student, roll, campus.
* Notifications on request, approval and rejection (with reason) for both campuses.
* Every action is written to the audit log (created, roll verified, approved,
  rejected, cancelled) with the user, campus, reference and IP where available.

This is a brand-new module — the existing Student Transfer, referral, overdue-blocking,
schedule and export features are unchanged.

---

# UI refresh — Canyon-inspired theme

The whole system (admin dashboard, reception, referral portal, and the public
apply/portal pages) now shares a refreshed look inspired by a modern
university-website palette: a **deep teal-navy brand** with a **warm gold accent**,
a clean cool-neutral background, and **Fraunces** (serif) display headings over
**Inter** body text.

Only colours, fonts and surface styling changed — every layout, page, workflow and
permission is exactly as before. The red-and-white payment receipt keeps its own
distinct look by design. All colours are driven by CSS variables in
`static/admin/css/admin.css` (and each public page's `:root`), so future tweaks are
one-line changes.
