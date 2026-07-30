"""Fee payment workflow (Module 1): challans and uploaded payment receipts.

Every application gets a Challan (unique number + printable PDF). Students pay
via JazzCash (upload receipt) or cash at the college; the department verifies
in the admin panel. Old receipts are never deleted (audit trail).
"""
import uuid

from sqlalchemy import (
    DateTime, Date, Float, ForeignKey, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import now


class ChallanStatus:
    UNPAID = "unpaid"
    PENDING_VERIFICATION = "pending_verification"
    PAID = "paid"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    ALL = [UNPAID, PENDING_VERIFICATION, PAID, REJECTED, CANCELLED]


class ReceiptStatus:
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REUPLOAD_REQUESTED = "reupload_requested"
    ALL = [PENDING, APPROVED, REJECTED, REUPLOAD_REQUESTED]


def _token() -> str:
    return uuid.uuid4().hex


class Challan(Base):
    __tablename__ = "challans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challan_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True
    )
    amount: Mapped[float] = mapped_column(Float, default=0)
    due_date: Mapped[object] = mapped_column(Date, nullable=True)
    payment_method: Mapped[str] = mapped_column(
        String(20), default="", index=True)  # jazzcash | cash | "" (not chosen yet)
    status: Mapped[str] = mapped_column(
        String(25), default=ChallanStatus.UNPAID, index=True)
    # Receipt number this challan was approved against. Deliberately NOT unique:
    # a challan is linked to the receipt the admin already issued on the
    # admissions page, so the same number legitimately appears on both.
    receipt_number: Mapped[str] = mapped_column(String(60), default="", index=True)
    pdf_path: Mapped[str] = mapped_column(String(300), default="")
    # Unguessable token — lets the student download their own challan / upload
    # a receipt from the public portal without an account.
    access_token: Mapped[str] = mapped_column(
        String(40), default=_token, unique=True, index=True)
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[object] = mapped_column(DateTime, default=now, onupdate=now)

    application = relationship("Application", backref="challans")
    receipts = relationship(
        "PaymentReceipt", back_populates="challan",
        order_by="PaymentReceipt.created_at")


class PaymentReceipt(Base):
    """One uploaded proof of payment. Multiple rows per challan are allowed
    (re-uploads after rejection) — nothing is ever deleted."""
    __tablename__ = "payment_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    challan_id: Mapped[int] = mapped_column(ForeignKey("challans.id"), index=True)
    file_path: Mapped[str] = mapped_column(String(300))
    original_name: Mapped[str] = mapped_column(String(200), default="")
    content_type: Mapped[str] = mapped_column(String(60), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    transaction_id: Mapped[str] = mapped_column(
        String(80), nullable=True, unique=True, index=True)  # no duplicates
    jazzcash_number: Mapped[str] = mapped_column(String(25), default="")
    payment_date: Mapped[object] = mapped_column(Date, nullable=True)
    remarks: Mapped[str] = mapped_column(Text, default="")

    status: Mapped[str] = mapped_column(
        String(25), default=ReceiptStatus.PENDING, index=True)
    verified_by: Mapped[int] = mapped_column(
        ForeignKey("admins.id"), nullable=True)
    verified_by_name: Mapped[str] = mapped_column(String(100), default="")
    verified_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    verification_remarks: Mapped[str] = mapped_column(Text, default="")

    ip_address: Mapped[str] = mapped_column(String(60), default="")
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)

    challan = relationship("Challan", back_populates="receipts")
