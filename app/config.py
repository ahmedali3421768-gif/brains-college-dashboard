"""Central configuration. Every tunable value lives here and comes from .env."""
import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()


class Settings:
    APP_NAME: str = "Brains College Admission & Chatbot Portal"
    VERSION: str = "2.0.0"

    # AI
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv(
        "GROQ_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"
    )

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./brains_college.db")

    # Security
    SECRET_KEY: str = os.getenv(
        "SECRET_KEY", "insecure-dev-key-change-me-in-production-0000"
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480")
    )
    ALLOWED_ORIGINS: list[str] = [
        o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()
    ]

    # Seed super admin
    SUPER_ADMIN_NAME: str = os.getenv("SUPER_ADMIN_NAME", "Super Admin")
    SUPER_ADMIN_EMAIL: str = os.getenv(
        "SUPER_ADMIN_EMAIL", "admin@brainscollege.edu.pk"
    )
    SUPER_ADMIN_PASSWORD: str = os.getenv("SUPER_ADMIN_PASSWORD", "Admin@123")

    # Timezone used for "today / this month" style analytics
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Karachi")

    # Reuse an anonymous visitor's chat session if they return within N minutes
    SESSION_REUSE_MINUTES: int = int(os.getenv("SESSION_REUSE_MINUTES", "30"))

    # ── Fee challans (Module 1) ─────────────────────────────────────────
    COLLEGE_NAME: str = os.getenv("COLLEGE_NAME", "Brains College, Lahore")
    COLLEGE_ADDRESS: str = os.getenv(
        "COLLEGE_ADDRESS",
        "Campuses: Walton Road | Queen Road | Darogwala | Bhagbanpura — Lahore",
    )
    COLLEGE_PHONE: str = os.getenv("COLLEGE_PHONE", "")
    CHALLAN_DEFAULT_AMOUNT: float = float(os.getenv("CHALLAN_DEFAULT_AMOUNT", "1000"))
    CHALLAN_DUE_DAYS: int = int(os.getenv("CHALLAN_DUE_DAYS", "7"))
    JAZZCASH_ACCOUNT: str = os.getenv("JAZZCASH_ACCOUNT", "")  # number shown on challan
    # Where uploaded receipts / generated challan PDFs are stored
    UPLOADS_DIR: str = os.getenv("UPLOADS_DIR", "uploads")
    MAX_RECEIPT_MB: int = int(os.getenv("MAX_RECEIPT_MB", "10"))

    @property
    def tz(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.TIMEZONE)
        except Exception:
            return ZoneInfo("UTC")


settings = Settings()

VALID_CAMPUSES = ["Walton Road", "Queen Road", "Darogwala", "Bhagbanpura"]


def _slug(campus: str) -> str:
    return campus.lower().replace(" ", "")


# One admin account per campus. Each can be overridden via environment
# variables, e.g. CAMPUS_WALTONROAD_EMAIL / CAMPUS_WALTONROAD_PASSWORD.
# Defaults use the pattern <slug>@brainscollege.edu.pk / Campus@123.
CAMPUS_ADMINS = {
    campus: {
        "name": f"{campus} Admin",
        "email": os.getenv(
            f"CAMPUS_{_slug(campus).upper()}_EMAIL",
            f"{_slug(campus)}@brainscollege.edu.pk"),
        "password": os.getenv(
            f"CAMPUS_{_slug(campus).upper()}_PASSWORD", "Campus@123"),
    }
    for campus in VALID_CAMPUSES
}

# One receptionist per campus (read-only fee lookup). Overridable via env,
# e.g. RECEPTION_WALTONROAD_EMAIL / RECEPTION_WALTONROAD_PASSWORD.
# Defaults: reception.<slug>@brainscollege.edu.pk / Reception@123
CAMPUS_RECEPTIONISTS = {
    campus: {
        "name": f"{campus} Reception",
        "email": os.getenv(
            f"RECEPTION_{_slug(campus).upper()}_EMAIL",
            f"reception.{_slug(campus)}@brainscollege.edu.pk"),
        "password": os.getenv(
            f"RECEPTION_{_slug(campus).upper()}_PASSWORD", "Reception@123"),
    }
    for campus in VALID_CAMPUSES
}


# ── Referral portal user (separate login, its own portal) ────────────────
# Override with REFERRAL_EMAIL / REFERRAL_PASSWORD in .env.
REFERRAL_USER = {
    "name": os.getenv("REFERRAL_NAME", "Referral Partner"),
    "email": os.getenv("REFERRAL_EMAIL", "referral@brainscollege.edu.pk").lower(),
    "password": os.getenv("REFERRAL_PASSWORD", "Referral@123"),
}
