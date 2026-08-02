from sqlalchemy import String, Integer, ForeignKey, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.utils.timeutil import now


class ChatSession(Base):
    """A conversation between one visitor and the AI (like a ChatGPT thread)."""
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid4 hex
    visitor_id: Mapped[str] = mapped_column(String(40), index=True)  # ip+ua hash
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="SET NULL"), nullable=True, index=True
    )
    visitor_name: Mapped[str] = mapped_column(String(120), nullable=True)
    visitor_phone: Mapped[str] = mapped_column(String(25), nullable=True, index=True)
    campus: Mapped[str] = mapped_column(String(60), default="", index=True)
    visitor_email: Mapped[str] = mapped_column(String(255), nullable=True)

    ip_address: Mapped[str] = mapped_column(String(60), default="")
    browser: Mapped[str] = mapped_column(String(40), default="")
    os: Mapped[str] = mapped_column(String(40), default="")
    device: Mapped[str] = mapped_column(String(20), default="")
    country: Mapped[str] = mapped_column(String(60), nullable=True)
    page_url: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(15), default="active", index=True)  # active|archived

    title: Mapped[str] = mapped_column(String(150), default="New conversation")
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)
    last_activity_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)

    messages = relationship(
        "ChatMessage", back_populates="session", order_by="ChatMessage.created_at",
        cascade="all, delete-orphan"
    )
    student = relationship("Student")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(15))  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text)
    response_time_ms: Mapped[int] = mapped_column(
        Integer, nullable=True
    )  # AI answer latency, or user typing gap
    created_at: Mapped[object] = mapped_column(DateTime, default=now, index=True)

    session = relationship("ChatSession", back_populates="messages")
