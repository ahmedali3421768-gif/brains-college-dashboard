from pydantic import BaseModel, Field, field_validator

from app.models.admin import Role


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: dict


class AdminCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)
    role: str = Role.STAFF

    @field_validator("role")
    @classmethod
    def valid_role(cls, v):
        if v not in Role.ALL:
            raise ValueError(f"Role must be one of: {', '.join(Role.ALL)}")
        return v


class AdminUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    role: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("role")
    @classmethod
    def valid_role(cls, v):
        if v is not None and v not in Role.ALL:
            raise ValueError(f"Role must be one of: {', '.join(Role.ALL)}")
        return v


class ChangePassword(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)
