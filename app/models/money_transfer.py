"""Inter-campus money transfer — moving a student's paid fee from the campus
that collected it to another campus, with a request → verify → approve flow.

Nothing financial changes until the destination campus approves AND confirms the
student's roll number matches. On approval the amount is booked as a ledger
movement (out of source, into destination) which the dashboard budget reads, so
the day's collection figures shift between campuses without touching the
student's own fee records.
"""
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.timeutil import now


class MoneyTransfer(Base):
    __tablename__ = "money_transfers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # human-facing unique id, e.g. MT-2026-00001
    transfer_no: Mapped[str] = mapped_column(String(30), unique=True, index=True)

    source_campus: Mapped[str] = mapped_column(String(60), index=True)
    dest_campus: Mapped[str] = mapped_column(String(60), index=True)

    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    student_name: Mapped[str] = mapped_column(String(120), default="")
    father_name: Mapped[str] = mapped_column(String(120), default="")
    course: Mapped[str] = mapped_column(String(150), default="")
    source_roll: Mapped[str] = mapped_column(String(40), default="")
    dest_roll: Mapped[str] = mapped_column(String(40), default="")

    amount: Mapped[float] = mapped_column(Float, default=0)
    remarks: Mapped[str] = mapped_column(Text, default="")
    reject_reason: Mapped[str] = mapped_column(String(300), default="")

    # pending | approved | rejected | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)

    requested_by_id: Mapped[int] = mapped_column(Integer, default=0)
    requested_by_name: Mapped[str] = mapped_column(String(100), default="")
    requested_at: Mapped[object] = mapped_column(
        DateTime, default=now, index=True)

    decided_by_id: Mapped[int] = mapped_column(Integer, default=0)
    decided_by_name: Mapped[str] = mapped_column(String(100), default="")
    approved_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    rejected_at: Mapped[object] = mapped_column(DateTime, nullable=True)
