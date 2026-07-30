"""Chat schemas — the same shapes the existing chatbot widget already sends,
with an optional session_id added (old widgets keep working without it)."""
from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: str = Field(pattern=r"^(user|assistant|system)$")
    content: str = Field(min_length=1, max_length=8000)


class ChatRequest(BaseModel):
    messages: List[Message]
    temperature: Optional[float] = Field(default=0.6, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=1024, ge=1, le=4096)
    session_id: Optional[str] = None  # NEW, optional — for conversation grouping
    page_url: Optional[str] = Field(default=None, max_length=500)  # page the widget is on


class ChatResponse(BaseModel):
    reply: str
    success: bool
    error: Optional[str] = None
    session_id: Optional[str] = None  # NEW — widget should echo this back


class LeadRequest(BaseModel):
    name: str
    phone: str
    campus: str
    session_id: Optional[str] = None  # NEW, optional — links lead to the chat
    # Module 3 — all optional, so the deployed widget keeps working unchanged
    email: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=80)
    interested_course: Optional[str] = Field(default=None, max_length=150)
    interested_department: Optional[str] = Field(default=None, max_length=120)
    source: Optional[str] = Field(default=None, max_length=30)


class LeadResponse(BaseModel):
    success: bool
    message: str
