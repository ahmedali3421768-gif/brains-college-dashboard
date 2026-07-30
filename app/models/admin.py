from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.timeutil import now


class Role:
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    STAFF = "staff"
    RECEPTIONIST = "receptionist"
    ALL = [SUPER_ADMIN, ADMIN, STAFF, RECEPTIONIST]


class Admin(Base):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default=Role.STAFF, index=True)
    # Campus scoping: a campus admin only sees their own campus's data.
    # Empty/None campus = college-wide access (super admin).
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=now)
    last_login: Mapped[object] = mapped_column(DateTime, nullable=True)


class ActivityLog(Base):
    """Audit trail of admin actions (logins, status changes, exports…)."""
    __tablename__ = "activity_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("admins.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(60), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)


class ReferralUser(Base):
    """Referral partners — their own login, entirely separate from Admin.

    They can only create referral applications for Darogwala / Bhagbanpura and
    see their own referral stats. They never touch the admin portal.
    """
    __tablename__ = "referral_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(25), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=now)
    last_login: Mapped[object] = mapped_column(DateTime, nullable=True)
