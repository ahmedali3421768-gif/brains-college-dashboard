"""Expense Management (Module 7): institutional expenses and budgets."""
from sqlalchemy import Date, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.utils.timeutil import now


class Budget(Base):
    """An allocated budget for one operational category. `spent` is derived
    from expenses in the same category, so remaining is always accurate."""
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)
    allocated: Mapped[float] = mapped_column(Float, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[object] = mapped_column(DateTime, default=now)
    updated_at: Mapped[object] = mapped_column(DateTime, default=now, onupdate=now)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(150), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(80), default="", index=True)
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)
    purchase_date: Mapped[object] = mapped_column(Date, nullable=True, index=True)
    vendor: Mapped[str] = mapped_column(String(150), default="")
    amount: Mapped[float] = mapped_column(Float, default=0)
    payment_method: Mapped[str] = mapped_column(String(30), default="cash", index=True)
    remarks: Mapped[str] = mapped_column(Text, default="")
    recorded_by_name: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)
