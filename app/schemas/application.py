import re

from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import VALID_CAMPUSES
from app.models.application import (
    AdmissionStatus, ApplicationStatus, PaymentStatus,
)

_PHONE_RE = re.compile(r"^\+?[\d\s\-]{7,20}$")
_CNIC_RE = re.compile(r"^\d{5}-?\d{7}-?\d$")


class ApplicationSubmit(BaseModel):
    """Public admission form payload (replaces the Google Sheets submission)."""
    full_name: str = Field(min_length=2, max_length=120)
    father_name: str = Field(default="", max_length=120)
    roll_number: str = Field(min_length=1, max_length=40)
    cnic: str | None = Field(default=None, max_length=20)
    phone: str = Field(min_length=7, max_length=25)
    guardian_phone: str = Field(default="", max_length=25)
    email: str | None = Field(default=None, max_length=255)
    gender: str = Field(default="", max_length=15)
    date_of_birth: str | None = None  # YYYY-MM-DD
    address: str = Field(default="", max_length=1000)
    city: str = Field(default="", max_length=80)
    programme_category: str = Field(min_length=1, max_length=40)
    course_name: str = Field(min_length=1, max_length=150)
    course_id: int | None = None
    department_id: int | None = None
    campus: str = Field(default="", max_length=60)
    session: str = Field(default="", max_length=40)
    lead_source: str = Field(min_length=1, max_length=40)
    lead_source_detail: str = Field(default="", max_length=120)
    class_timing: str = Field(default="", max_length=60)
    admission_date: str | None = None   # YYYY-MM-DD
    duration: str | None = Field(default=None, max_length=60)
    previous_qualification: str = Field(default="", max_length=150)
    percentage: float | None = Field(default=None, ge=0, le=100)
    marks: float | None = Field(default=None, ge=0)
    semester: str | None = Field(default=None, max_length=40)
    documents: list[str] = Field(default_factory=list)
    extra_fields: dict = Field(default_factory=dict)

    # ── Academic Information (optional) — used by the Attendance Card
    class_time: str = Field(default="", max_length=80)
    lab_time: str = Field(default="", max_length=80)
    instructor_name: str = Field(default="", max_length=120)
    course_duration_months: int = Field(default=3, ge=1, le=24)

    @field_validator("guardian_phone")
    @classmethod
    def _check_guardian(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""                       # optional
        digits = sum(ch.isdigit() for ch in v)
        if digits < 7 or digits > 15:
            raise ValueError("Enter a valid guardian phone number.")
        return v

    @field_validator("roll_number")
    @classmethod
    def clean_roll(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Roll Number is required")
        return v

    @field_validator("programme_category")
    @classmethod
    def valid_category(cls, v):
        from app.catalog import PROGRAMME_CATEGORIES
        if v not in PROGRAMME_CATEGORIES:
            raise ValueError(
                f"Programme Category must be one of: "
                f"{', '.join(PROGRAMME_CATEGORIES)}")
        return v

    @field_validator("lead_source")
    @classmethod
    def valid_source(cls, v):
        from app.catalog import LEAD_SOURCES
        v = v.strip()
        if v not in LEAD_SOURCES:
            raise ValueError(
                f"How did you hear about us? must be one of: "
                f"{', '.join(LEAD_SOURCES)}")
        return v

    @model_validator(mode="after")
    def check_source_detail(self):
        if self.lead_source == "Others" and not (self.lead_source_detail or "").strip():
            raise ValueError('Please specify how you heard about us.')
        return self

    @field_validator("phone")
    @classmethod
    def valid_phone(cls, v):
        v = v.strip()
        if not _PHONE_RE.match(v):
            raise ValueError("Enter a valid phone number")
        return v

    @field_validator("cnic")
    @classmethod
    def valid_cnic(cls, v):
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _CNIC_RE.match(v):
            raise ValueError("CNIC must look like 35202-1234567-1")
        return v

    @field_validator("email")
    @classmethod
    def valid_email(cls, v):
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("campus")
    @classmethod
    def valid_campus(cls, v):
        if v and v not in VALID_CAMPUSES:
            raise ValueError(f"Campus must be one of: {', '.join(VALID_CAMPUSES)}")
        return v


class ApplicationUpdate(BaseModel):
    """Admin editing of an application / student record."""
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    father_name: str | None = Field(default=None, max_length=120)
    cnic: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=25)
    guardian_phone: str | None = Field(default=None, max_length=25)
    email: str | None = Field(default=None, max_length=255)
    gender: str | None = Field(default=None, max_length=15)
    date_of_birth: str | None = None
    address: str | None = Field(default=None, max_length=1000)
    city: str | None = Field(default=None, max_length=80)
    roll_number: str | None = Field(default=None, max_length=40)
    programme_category: str | None = Field(default=None, max_length=40)
    course_name: str | None = Field(default=None, max_length=150)
    session: str | None = Field(default=None, max_length=40)
    lead_source: str | None = Field(default=None, max_length=40)
    lead_source_detail: str | None = Field(default=None, max_length=120)
    class_timing: str | None = Field(default=None, max_length=60)
    assigned_staff_id: int | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    course_id: int | None = None
    department_id: int | None = None
    campus: str | None = Field(default=None, max_length=60)
    previous_qualification: str | None = Field(default=None, max_length=150)
    percentage: float | None = Field(default=None, ge=0, le=100)
    class_time: str | None = Field(default=None, max_length=80)
    lab_time: str | None = Field(default=None, max_length=80)
    instructor_name: str | None = Field(default=None, max_length=120)
    course_duration_months: int | None = Field(default=None, ge=1, le=24)


class StatusUpdate(BaseModel):
    application_status: str | None = None
    payment_status: str | None = None
    admission_status: str | None = None
    referral_status: str | None = None
    referral_remarks: str | None = None

    @field_validator("application_status")
    @classmethod
    def v1(cls, v):
        if v is not None and v not in ApplicationStatus.ALL:
            raise ValueError(f"Must be one of: {', '.join(ApplicationStatus.ALL)}")
        return v

    @field_validator("payment_status")
    @classmethod
    def v2(cls, v):
        if v is not None and v not in PaymentStatus.ALL:
            raise ValueError(f"Must be one of: {', '.join(PaymentStatus.ALL)}")
        return v

    @field_validator("admission_status")
    @classmethod
    def v3(cls, v):
        if v is not None and v not in AdmissionStatus.ALL:
            raise ValueError(f"Must be one of: {', '.join(AdmissionStatus.ALL)}")
        return v

    @field_validator("referral_status")
    @classmethod
    def v4(cls, v):
        valid = ["pending", "accepted", "approved", "rejected", "enrolled", "under_review", "contacted", "cancelled"]
        if v is not None and v.lower() not in valid:
            raise ValueError(f"referral_status must be one of: {', '.join(valid)}")
        return v.lower() if v else None


class NoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class LeadStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(new|contacted|interested|follow_up|documents_pending|application_submitted|converted|rejected|lost)$")
