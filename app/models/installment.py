"""Fee installments — the single source of truth for a student's fee records.

The admission office creates/edits installments; everything else (challan,
payment status colours, class eligibility, dashboards) derives from them
automatically. Nothing is ever edited on the challan itself.
"""
from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import now


class InstallmentStatus:
    PENDING = "pending"
    PAID = "paid"
    # "overdue" is derived at read time (pending + past due date)
    ALL = [PENDING, PAID]


class Installment(Base):
    __tablename__ = "installments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(60), default="Installment")
    # Which of the four schedule stages this row is:
    # admission_fee | first_installment | second_installment | test_session
    stage: Mapped[str] = mapped_column(String(30), default="", index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[object] = mapped_column(Date, nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(15), default=InstallmentStatus.PENDING, index=True)
    paid_amount: Mapped[float] = mapped_column(Float, default=0)
    paid_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    paid_method: Mapped[str] = mapped_column(String(20), default="")
    receipt_number: Mapped[str] = mapped_column(String(60), default="", index=True)
    recorded_by_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[object] = mapped_column(DateTime, default=now)
    updated_at: Mapped[object] = mapped_column(DateTime, default=now, onupdate=now)

    application = relationship("Application", back_populates="installments")
    allocations = relationship(
        "PaymentAllocation", back_populates="installment",
        cascade="all, delete-orphan", passive_deletes=True
    )


# receipt number captured when a payment is approved/recorded


class PaymentAllocation(Base):
    """Which schedule stage a payment landed on, and on what day.

    A single recorded payment can settle more than one stage (e.g. the admission
    fee and the first installment together), so we keep one allocation row per
    stage touched. The Recoveries export reads these rows to show exactly what
    was collected on a given date, stage by stage.
    """
    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    installment_id: Mapped[int] = mapped_column(
        ForeignKey("installments.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(30), default="", index=True)
    amount: Mapped[float] = mapped_column(Float, default=0)
    receipt_number: Mapped[str] = mapped_column(String(60), default="", index=True)
    method: Mapped[str] = mapped_column(String(40), default="")
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)
    paid_on: Mapped[object] = mapped_column(Date, nullable=True, index=True)
    recorded_by_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)

    application = relationship("Application", back_populates="payment_allocations")
    installment = relationship("Installment", back_populates="allocations")
