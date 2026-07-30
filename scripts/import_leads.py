"""Import your old Google Sheets leads into the database.

HOW TO USE
1. Open your Google Sheet → File → Download → Comma-separated values (.csv)
2. Put the file next to this script (or anywhere) and run:

       python scripts/import_leads.py path/to/leads.csv

The script auto-detects common column names (Name / Phone / Campus /
Timestamp / Email / City / Course). Rows with the same phone number that
already exist in the database are skipped, so it is safe to run twice.
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Lead, LeadSource  # noqa: E402
from app.seed import init_db  # noqa: E402

NAME_KEYS = ["name", "student name", "full name", "naam"]
PHONE_KEYS = ["phone", "phone number", "mobile", "whatsapp", "contact"]
CAMPUS_KEYS = ["campus", "branch"]
EMAIL_KEYS = ["email", "e-mail"]
CITY_KEYS = ["city"]
COURSE_KEYS = ["course", "interested course", "program"]
DATE_KEYS = ["timestamp", "date", "created", "created at", "time"]

DATE_FORMATS = ["%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%m/%d/%Y", "%d/%m/%Y", "%Y-%m-%d"]


def pick(row: dict, keys: list[str]) -> str:
    lowered = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
    for key in keys:
        if key in lowered and lowered[key]:
            return lowered[key]
    return ""


def parse_date(value: str):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def main(csv_path: str):
    init_db()
    db = SessionLocal()
    added = skipped = 0
    try:
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = pick(row, NAME_KEYS)
                phone = pick(row, PHONE_KEYS)
                if not name or not phone:
                    skipped += 1
                    continue
                if db.query(Lead).filter(Lead.phone == phone,
                                         Lead.name == name).first():
                    skipped += 1
                    continue
                lead = Lead(
                    name=name[:120], phone=phone[:25],
                    campus=pick(row, CAMPUS_KEYS)[:60],
                    email=pick(row, EMAIL_KEYS)[:255] or None,
                    city=pick(row, CITY_KEYS)[:80],
                    interested_course=pick(row, COURSE_KEYS)[:150],
                    source=LeadSource.CHATBOT,
                )
                when = parse_date(pick(row, DATE_KEYS))
                if when:
                    lead.created_at = when
                db.add(lead)
                added += 1
        db.commit()
    finally:
        db.close()
    print(f"Done — imported {added} lead(s), skipped {skipped} "
          f"(missing data or already in the database).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/import_leads.py path/to/leads.csv")
        sys.exit(1)
    main(sys.argv[1])
