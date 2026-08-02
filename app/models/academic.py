from sqlalchemy import String, Integer, ForeignKey, Boolean, Float, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import now


class Department(Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    courses = relationship("Course", back_populates="department")


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("departments.id"), index=True
    )
    admission_fee: Mapped[float] = mapped_column(Float, nullable=True)  # None → default fee
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    department = relationship("Department", back_populates="courses")


class CampusRollSetting(Base):
    """Starting roll number configured per campus.

    Each campus has a fixed prefix (Walton Road → W, Queen Road → Q,
    Darogwala → D, Bhagbanpura → B) and its own starting number. Roll numbers
    are then issued sequentially with no gaps.
    """
    __tablename__ = "campus_roll_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campus: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    start_number: Mapped[int] = mapped_column(Integer, default=1)
    updated_by_name: Mapped[str] = mapped_column(String(100), default="")
    updated_at: Mapped[object] = mapped_column(
        DateTime, default=now, onupdate=now)


class TransferRequest(Base):
    """A pending student-transfer awaiting the destination campus's decision.

    The source campus creates the request; the student stays put until the
    destination admin approves it. Only on approval does the move happen and a
    new roll number get issued. Statuses: pending | approved | rejected.
    """
    __tablename__ = "transfer_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    from_campus: Mapped[str] = mapped_column(String(60), index=True)
    to_campus: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    reason: Mapped[str] = mapped_column(String(500), default="")

    # snapshot for the list view (so we don't re-join on every render)
    student_name: Mapped[str] = mapped_column(String(120), default="")
    current_roll: Mapped[str] = mapped_column(String(40), default="")
    new_roll: Mapped[str] = mapped_column(String(40), default="")
    course: Mapped[str] = mapped_column(String(120), default="")

    requested_by_id: Mapped[int] = mapped_column(Integer, default=0)
    requested_by_name: Mapped[str] = mapped_column(String(100), default="")
    decided_by_id: Mapped[int] = mapped_column(Integer, default=0)
    decided_by_name: Mapped[str] = mapped_column(String(100), default="")
    decided_at: Mapped[object] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(
        DateTime, default=now, index=True)

    application = relationship("Application", back_populates="transfer_requests")
