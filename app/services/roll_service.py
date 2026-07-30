"""Campus roll numbers — fixed prefix per campus, strict sequence, no gaps.

Walton Road → W-1, W-2 …      Queen Road   → Q-1, Q-2 …
Darogwala   → D-1, D-2 …      Bhagbanpura  → B-1, B-2 …

Each campus admin sets a *starting* number (Admissions Settings). From then on
roll numbers must run consecutively: if D-34 is the latest, the next admission
must be D-35 — D-36 is rejected.
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import CampusRollSetting, Student

# Campus → prefix. The only source of truth.
CAMPUS_PREFIX = {
    "Walton Road": "W",
    "Queen Road": "Q",
    "Darogwala": "D",
    "Bhagbanpura": "B",
}


def prefix_for(campus: str) -> str:
    """The roll prefix for a campus, or '' if the campus is unknown."""
    return CAMPUS_PREFIX.get((campus or "").strip(), "")


def parse(roll: str) -> tuple[str, int] | None:
    """'D-35' → ('D', 35). None if it doesn't match PREFIX-NUMBER."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\s*-\s*(\d+)\s*", roll or "")
    if not m:
        return None
    return m.group(1).upper(), int(m.group(2))


def format_roll(prefix: str, number: int) -> str:
    return f"{prefix}-{number}"


def start_number(db: Session, campus: str) -> int:
    """Configured starting roll number for a campus (default 1)."""
    row = (db.query(CampusRollSetting)
           .filter(CampusRollSetting.campus == campus).first())
    return row.start_number if row else 1


def set_start_number(db: Session, campus: str, number: int,
                     by_name: str = "") -> CampusRollSetting:
    if number < 1:
        raise HTTPException(status_code=422,
                            detail="Starting roll number must be 1 or more.")
    row = (db.query(CampusRollSetting)
           .filter(CampusRollSetting.campus == campus).first())
    if row is None:
        row = CampusRollSetting(campus=campus)
        db.add(row)
    row.start_number = number
    row.updated_by_name = by_name
    db.commit()
    db.refresh(row)
    return row


def retired_numbers(db: Session, campus: str) -> set[int]:
    """Roll numbers that were issued at this campus and then retired when the
    student transferred away. They must never be handed out again."""
    from app.models import Application

    prefix = prefix_for(campus)
    if not prefix:
        return set()
    out: set[int] = set()
    rows = (db.query(Application.previous_roll_number)
            .filter(Application.previous_roll_number.ilike(f"{prefix}-%")).all())
    for (roll,) in rows:
        parsed = parse(roll or "")
        if parsed and parsed[0] == prefix:
            out.add(parsed[1])
    return out


def highest_number(db: Session, campus: str) -> int | None:
    """Highest roll number ever issued at this campus, or None if none yet.

    Counts BOTH the students currently at the campus and the roll numbers
    retired by transfers — a retired number is burnt forever, so the sequence
    never walks backwards over it.
    """
    prefix = prefix_for(campus)
    if not prefix:
        return None
    rows = (db.query(Student.roll_number)
            .filter(Student.roll_number.ilike(f"{prefix}-%")).all())
    best = None
    for (roll,) in rows:
        parsed = parse(roll)
        if parsed and parsed[0] == prefix:
            n = parsed[1]
            if best is None or n > best:
                best = n
    for n in retired_numbers(db, campus):
        if best is None or n > best:
            best = n
    return best


def next_roll(db: Session, campus: str) -> str:
    """The roll number the next admission at this campus must use."""
    prefix = prefix_for(campus)
    if not prefix:
        return ""
    highest = highest_number(db, campus)
    nxt = start_number(db, campus) if highest is None else highest + 1
    return format_roll(prefix, nxt)


def validate(db: Session, roll_number: str, campus: str) -> str:
    """Check a roll number against the campus prefix AND the sequence.

    Returns the cleaned roll number, or raises 422 with a clear message.
    """
    roll = (roll_number or "").strip()
    prefix = prefix_for(campus)
    if not prefix:
        # Unknown campus (shouldn't happen) — don't block the admission.
        return roll

    parsed = parse(roll)
    if not parsed:
        raise HTTPException(
            status_code=422,
            detail=f'Invalid roll number format. Use "{prefix}-1", '
                   f'"{prefix}-2", and so on for the {campus} campus.')

    got_prefix, number = parsed
    if got_prefix != prefix:
        raise HTTPException(
            status_code=422,
            detail=f'Invalid roll number. The {campus} campus uses the '
                   f'"{prefix}-" prefix — for example {next_roll(db, campus)}.')

    if number in retired_numbers(db, campus):
        raise HTTPException(
            status_code=409,
            detail=f"Roll number {format_roll(prefix, number)} belonged to a "
                   f"student who transferred away. Retired roll numbers can "
                   f"never be reused. The next available roll number is "
                   f"{next_roll(db, campus)}.")

    expected = next_roll(db, campus)
    exp_num = parse(expected)[1]
    if number != exp_num:
        highest = highest_number(db, campus)
        if highest is None:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid roll number. The first roll number for "
                       f"{campus} is {expected}.")
        raise HTTPException(
            status_code=422,
            detail=f"Invalid roll number. The previous assigned roll number "
                   f"is {format_roll(prefix, highest)}. The next available "
                   f"roll number is {expected}.")
    return format_roll(prefix, number)


# ── Referral roll numbers ────────────────────────────────────────────────
REFERRAL_PREFIX = "F"
REFERRAL_CAMPUSES = ["Darogwala", "Bhagbanpura"]


def next_referral_roll(db: Session, campus: str) -> str:
    """Referral roll numbers use the F- prefix but stay in step with the
    campus's own numbering.

    If Bhagbanpura is at B-003, the next referral is F-004. If the highest
    number at that campus is 087, the referral becomes F-088. Existing F-
    numbers are counted too, so two referrals never collide.
    """
    campus_high = highest_number(db, campus) or 0

    ref_high = 0
    for (roll,) in (db.query(Student.roll_number)
                    .filter(Student.roll_number.ilike(f"{REFERRAL_PREFIX}-%"))
                    .all()):
        parsed = parse(roll)
        if parsed and parsed[0] == REFERRAL_PREFIX:
            ref_high = max(ref_high, parsed[1])

    base = max(campus_high, ref_high)
    if base == 0:
        base = max(0, start_number(db, campus) - 1)
    return format_roll(REFERRAL_PREFIX, base + 1)


def next_transfer_roll(db: Session, destination_campus: str) -> str:
    """The roll number a transferred student receives at the destination
    campus — simply the next in that campus's sequence."""
    return next_roll(db, destination_campus)
