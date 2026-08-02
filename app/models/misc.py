from sqlalchemy import String, Integer, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import now


class LeadStatus:
    NEW = "new"
    CONTACTED = "contacted"
    INTERESTED = "interested"
    FOLLOW_UP = "follow_up"
    DOCUMENTS_PENDING = "documents_pending"
    APPLICATION_SUBMITTED = "application_submitted"
    CONVERTED = "converted"
    REJECTED = "rejected"
    LOST = "lost"
    ALL = [NEW, CONTACTED, INTERESTED, FOLLOW_UP, DOCUMENTS_PENDING,
           APPLICATION_SUBMITTED, CONVERTED, REJECTED, LOST]


class LeadSource:
    CHATBOT = "chatbot"
    ADMISSION_FORM = "admission_form"
    CONTACT_FORM = "contact_form"
    COURSE_INQUIRY = "course_inquiry"
    NEWSLETTER = "newsletter"
    WEBSITE_POPUP = "website_popup"
    OTHER = "other"
    ALL = [CHATBOT, ADMISSION_FORM, CONTACT_FORM, COURSE_INQUIRY,
           NEWSLETTER, WEBSITE_POPUP, OTHER]


class Lead(Base):
    """Every interested visitor becomes a lead (Module 3). The original
    chatbot shape (name + phone + campus) still works unchanged; everything
    else is optional."""
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    phone: Mapped[str] = mapped_column(String(25), index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=True, index=True)
    city: Mapped[str] = mapped_column(String(80), default="")
    campus: Mapped[str] = mapped_column(String(60), index=True)
    interested_course: Mapped[str] = mapped_column(String(150), default="")
    interested_department: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(
        String(30), default=LeadSource.CHATBOT, index=True)
    status: Mapped[str] = mapped_column(
        String(30), default=LeadStatus.NEW, index=True)

    assigned_to: Mapped[int] = mapped_column(
        ForeignKey("admins.id"), nullable=True, index=True)
    assigned_to_name: Mapped[str] = mapped_column(String(100), default="")
    follow_up_at: Mapped[object] = mapped_column(DateTime, nullable=True, index=True)

    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True)  # set on conversion
    session_id: Mapped[str] = mapped_column(String(36), nullable=True)

    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[object] = mapped_column(DateTime, default=now, onupdate=now)

    notes = relationship("LeadNote", back_populates="lead",
                         order_by="LeadNote.created_at",
                         cascade="all, delete-orphan")


class LeadNote(Base):
    __tablename__ = "lead_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lead_id: Mapped[int] = mapped_column(
        ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"), nullable=True)
    admin_name: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime, default=now)

    lead = relationship("Lead", back_populates="notes")


class NotificationPriority:
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"
    ALL = [LOW, NORMAL, HIGH, CRITICAL]


class Notification(Base):
    """Smart notifications (Module 4). A unique content hash prevents the
    same notification from ever being created twice — repeats just bump
    `occurrences` and `updated_at` instead."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(
        String(30), default="general", index=True)
    priority: Mapped[str] = mapped_column(
        String(10), default=NotificationPriority.NORMAL, index=True)
    channel: Mapped[str] = mapped_column(String(15), default="in_app")

    title: Mapped[str] = mapped_column(String(150))
    message: Mapped[str] = mapped_column(Text, default="")
    related_id: Mapped[str] = mapped_column(String(40), nullable=True)
    # Campus this notification belongs to. Empty = global (visible to super
    # admin only in the per-campus view).
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)

    # sha256 of (type | related_id | title | message) — the duplicate detector
    hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=True)
    occurrences: Mapped[int] = mapped_column(Integer, default=1)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[object] = mapped_column(DateTime, default=now, onupdate=now)
