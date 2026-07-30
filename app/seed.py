"""Create tables and seed the first super admin + default departments/courses.

Runs automatically at startup (see main.py lifespan). Safe to run repeatedly —
it only inserts when the relevant tables are empty.
"""
import logging

from app import models  # noqa: F401 — ensures every table is registered
from app.auth.security import hash_password
from app.config import settings
from app.database import Base, SessionLocal, engine

logger = logging.getLogger(__name__)

DEFAULT_DEPARTMENTS = [
    ("Science", "SCI"),
    ("Computer Science", "CS"),
    ("Arts", "ARTS"),
    ("Commerce", "COM"),
]

DEFAULT_COURSES = [
    # (name, code, department code, admission fee — None → default)
    ("FSc Pre-Medical", "FSC-PM", "SCI", None),
    ("FSc Pre-Engineering", "FSC-PE", "SCI", None),
    ("ICS (Computer Science)", "ICS", "CS", None),
    ("FA (Arts)", "FA", "ARTS", None),
    ("I.Com (Commerce)", "ICOM", "COM", None),
]


def init_db():
    Base.metadata.create_all(bind=engine)
    # add any new columns to pre-existing tables (safe, additive only)
    from app.migrate import (ensure_receipt_indexes, map_legacy_values,
                             run_additive_migration)
    run_additive_migration()
    map_legacy_values()
    ensure_receipt_indexes()
    db = SessionLocal()
    try:
        # ── Super admin (college-wide, no campus) ─────────────────────
        if not db.query(models.Admin).count():
            db.add(models.Admin(
                name=settings.SUPER_ADMIN_NAME,
                email=settings.SUPER_ADMIN_EMAIL.lower(),
                password_hash=hash_password(settings.SUPER_ADMIN_PASSWORD),
                role=models.Role.SUPER_ADMIN,
                campus="",
            ))
            db.commit()
            logger.info("Seeded super admin: %s", settings.SUPER_ADMIN_EMAIL)
            if settings.SUPER_ADMIN_PASSWORD == "Admin@123":
                logger.warning(
                    "Super admin is using the DEFAULT password. "
                    "Set SUPER_ADMIN_PASSWORD in .env and change it after login."
                )

        # ── One admin per campus (each scoped to their own campus) ─────
        from app.config import (CAMPUS_ADMINS, CAMPUS_RECEPTIONISTS,
                                 VALID_CAMPUSES)
        for campus in VALID_CAMPUSES:
            cfg = CAMPUS_ADMINS.get(campus)
            if not cfg:
                continue
            email = cfg["email"].lower()
            if db.query(models.Admin).filter(
                    models.Admin.email == email).first():
                continue
            db.add(models.Admin(
                name=cfg["name"], email=email,
                password_hash=hash_password(cfg["password"]),
                role=models.Role.ADMIN, campus=campus,
            ))
            logger.info("Seeded campus admin: %s (%s)", email, campus)
        db.commit()

        # ── One receptionist per campus (read-only fee lookup) ─────────
        for campus in VALID_CAMPUSES:
            cfg = CAMPUS_RECEPTIONISTS.get(campus)
            if not cfg:
                continue
            email = cfg["email"].lower()
            if db.query(models.Admin).filter(
                    models.Admin.email == email).first():
                continue
            db.add(models.Admin(
                name=cfg["name"], email=email,
                password_hash=hash_password(cfg["password"]),
                role=models.Role.RECEPTIONIST, campus=campus,
            ))
            logger.info("Seeded receptionist: %s (%s)", email, campus)
        db.commit()

        # ── Referral portal user (separate login) ──────────────────────
        from app.config import REFERRAL_USER
        if not db.query(models.ReferralUser).filter(
                models.ReferralUser.email == REFERRAL_USER["email"]).first():
            db.add(models.ReferralUser(
                name=REFERRAL_USER["name"],
                email=REFERRAL_USER["email"],
                password_hash=hash_password(REFERRAL_USER["password"]),
            ))
            db.commit()
            logger.info("Seeded referral user: %s", REFERRAL_USER["email"])

        # ── Departments & courses ──────────────────────────────────────
        if not db.query(models.Department).count():
            for name, code in DEFAULT_DEPARTMENTS:
                db.add(models.Department(name=name, code=code))
            db.commit()
            dept_by_code = {
                d.code: d.id for d in db.query(models.Department).all()
            }
            for name, code, dept_code, fee in DEFAULT_COURSES:
                db.add(models.Course(
                    name=name, code=code,
                    department_id=dept_by_code[dept_code],
                    admission_fee=fee,
                ))
            db.commit()
            logger.info("Seeded default departments and courses.")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    init_db()
    print("Database initialised.")
