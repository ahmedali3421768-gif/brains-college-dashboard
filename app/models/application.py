from sqlalchemy import String, Integer, ForeignKey, DateTime, Text, Float, Date, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import now


class Student(Base):
    """One row per real person — applications, payments and chat sessions hang
    off this so the same student is never duplicated."""
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    roll_number: Mapped[str] = mapped_column(
        String(40), unique=True, index=True, nullable=True)  # primary identifier
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    father_name: Mapped[str] = mapped_column(String(120), default="")
    cnic: Mapped[str] = mapped_column(String(20), index=True, nullable=True)
    phone: Mapped[str] = mapped_column(String(25), index=True)
    guardian_phone: Mapped[str] = mapped_column(String(25), default="")
    email: Mapped[str] = mapped_column(String(255), index=True, nullable=True)
    gender: Mapped[str] = mapped_column(String(15), default="")
    date_of_birth: Mapped[object] = mapped_column(Date, nullable=True)
    address: Mapped[str] = mapped_column(Text, default="")
    city: Mapped[str] = mapped_column(String(80), default="", index=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=now)

    applications = relationship("Application", back_populates="student")


class ApplicationStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"      # legacy — kept for old rows, hidden from filters
    ON_HOLD = "on_hold"
    DROPPED_OUT = "dropped_out"
    ALL = [PENDING, APPROVED, REJECTED, ON_HOLD, DROPPED_OUT]


class PaymentStatus:
    """Fee position of the whole application — auto-computed from payments."""
    UNPAID = "unpaid"                 # red
    PARTIALLY_PAID = "partially_paid" # yellow
    FULLY_PAID = "fully_paid"         # green
    # legacy values kept for old rows; migration maps them
    ALL = [UNPAID, PARTIALLY_PAID, FULLY_PAID]


class EligibilityStatus:
    NOT_ELIGIBLE = "not_eligible"     # < 75% of total fee paid
    ELIGIBLE = "eligible"             # >= 75% paid → can attend classes
    ALL = [NOT_ELIGIBLE, ELIGIBLE]


class AdmissionStatus:
    NOT_ADMITTED = "not_admitted"
    ADMITTED = "admitted"
    ENROLLED = "enrolled"
    ALL = [NOT_ADMITTED, ADMITTED, ENROLLED]


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_no: Mapped[str] = mapped_column(
        String(30), unique=True, index=True, nullable=True
    )
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id"), index=True, nullable=True
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"), index=True, nullable=True
    )
    # New two-level programme selection (catalog-driven, not tied to courses table)
    programme_category: Mapped[str] = mapped_column(
        String(40), default="", index=True)   # "Short Courses" | "Intermediate"
    course_name: Mapped[str] = mapped_column(String(150), default="")  # chosen course
    session: Mapped[str] = mapped_column(String(40), default="")
    lead_source: Mapped[str] = mapped_column(String(40), default="", index=True)
    lead_source_detail: Mapped[str] = mapped_column(String(120), default="")
    assigned_staff_id: Mapped[int] = mapped_column(
        ForeignKey("admins.id"), nullable=True, index=True)
    assigned_staff_name: Mapped[str] = mapped_column(String(100), default="")
    remarks: Mapped[str] = mapped_column(Text, default="")
    campus: Mapped[str] = mapped_column(String(60), default="")
    previous_qualification: Mapped[str] = mapped_column(String(150), default="")
    percentage: Mapped[float] = mapped_column(Float, nullable=True)
    documents: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    extra_fields: Mapped[str] = mapped_column(Text, default="{}")  # JSON dict

    # ── Academic Information (all optional) — printed on the Attendance Card
    class_time: Mapped[str] = mapped_column(String(80), default="")
    lab_time: Mapped[str] = mapped_column(String(80), default="")
    instructor_name: Mapped[str] = mapped_column(String(120), default="")
    course_duration_months: Mapped[int] = mapped_column(Integer, default=3)

    # ── Referral (separate Referral Portal — kept out of normal admissions)
    is_referral: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    referral_user_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    referral_enrolled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    referral_enrolled_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    # The destination campus admin accepts or rejects a referral application.
    # pending | accepted | rejected  (only meaningful when is_referral is true)
    referral_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True)
    referral_decided_by: Mapped[str] = mapped_column(String(100), default="")
    referral_decided_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    referral_remarks: Mapped[str] = mapped_column(String(400), default="")

    # ── Campus transfer history
    transferred_from: Mapped[str] = mapped_column(String(60), default="")
    previous_roll_number: Mapped[str] = mapped_column(String(40), default="")
    transferred_at: Mapped[object] = mapped_column(DateTime, nullable=True)

    # ── Attendance Card tracking
    card_generated_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    card_last_printed_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    card_printed_by: Mapped[str] = mapped_column(String(100), default="")
    card_print_count: Mapped[int] = mapped_column(Integer, default=0)

    application_status: Mapped[str] = mapped_column(
        String(20), default=ApplicationStatus.PENDING, index=True
    )
    payment_status: Mapped[str] = mapped_column(
        String(20), default=PaymentStatus.UNPAID, index=True
    )
    eligibility_status: Mapped[str] = mapped_column(
        String(20), default=EligibilityStatus.NOT_ELIGIBLE, index=True
    )
    total_fee: Mapped[float] = mapped_column(Float, default=0)
    fee_category: Mapped[str] = mapped_column(String(60), default="Admission Fee")
    admission_status: Mapped[str] = mapped_column(
        String(20), default=AdmissionStatus.NOT_ADMITTED, index=True
    )

    submitted_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[object] = mapped_column(DateTime, default=now, onupdate=now)

    student = relationship("Student", back_populates="applications")
    department = relationship("Department")
    course = relationship("Course")
    notes = relationship(
        "ApplicationNote", back_populates="application", order_by="ApplicationNote.created_at",
        cascade="all, delete-orphan"
    )
    payments = relationship(
        "Payment", back_populates="application", cascade="all, delete-orphan"
    )
    installments = relationship(
        "Installment", back_populates="application", cascade="all, delete-orphan"
    )
    payment_allocations = relationship(
        "PaymentAllocation", back_populates="application", cascade="all, delete-orphan"
    )
    challans = relationship(
        "Challan", back_populates="application", cascade="all, delete-orphan"
    )
    transfer_requests = relationship(
        "TransferRequest", back_populates="application", cascade="all, delete-orphan"
    )
    money_transfers = relationship(
        "MoneyTransfer", back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationNote(Base):
    __tablename__ = "application_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    admin_id: Mapped[int] = mapped_column(ForeignKey("admins.id"), nullable=True)
    admin_name: Mapped[str] = mapped_column(String(100), default="")
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime, default=now)

    application = relationship("Application", back_populates="notes")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[float] = mapped_column(Float, default=0)
    method: Mapped[str] = mapped_column(String(40), default="")
    receipt_number: Mapped[str] = mapped_column(String(60), default="", index=True)
    reference: Mapped[str] = mapped_column(String(120), default="")
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    verified_by: Mapped[int] = mapped_column(ForeignKey("admins.id"), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=now)
    verified_at: Mapped[object] = mapped_column(DateTime, nullable=True)

    application = relationship("Application", back_populates="payments")
