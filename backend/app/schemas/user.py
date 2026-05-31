"""
schemas/user.py — Pydantic schemas for User

WHY have BOTH SQLAlchemy models AND Pydantic schemas?
  This is the most common confusion for beginners.

  SQLAlchemy model (app/models/user.py):
    → Represents a ROW in the database
    → Talks to PostgreSQL
    → Has relationships, lazy loading, etc.

  Pydantic schema (app/schemas/user.py):
    → Represents data IN TRANSIT (HTTP request/response)
    → Validates and serializes JSON
    → Has no DB knowledge

  They are deliberately separate. The schema controls what the API EXPOSES.
  For example: the User model has hashed_password — but UserResponse NEVER
  includes it. The schema acts as a security boundary.

  This pattern is sometimes called the "DTO" pattern (Data Transfer Object)
  — very common in Java/Spring, increasingly common in Python FastAPI.

Interview question: "Why would you separate your ORM model from your API schema?"
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import password_exceeds_bcrypt_limit


# ── Request schemas (what the API accepts) ──────────────────────────────────────

class UserRegister(BaseModel):
    """Schema for POST /auth/register"""
    email: EmailStr                      # Pydantic validates email format automatically
    password: str = Field(min_length=8, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        """
        WHY validate in the schema and not the endpoint?
          Single responsibility. The endpoint should trust that validated data arrives.
          The schema is the contract — it enforces it before any code runs.
        """
        if password_exceeds_bcrypt_limit(v):
            raise ValueError("Password must be 72 bytes or less")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserLogin(BaseModel):
    """Schema for POST /auth/login"""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """Schema for PATCH /users/me — all fields optional (partial update)"""
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=100)


# ── Response schemas (what the API returns) ─────────────────────────────────────

class UserResponse(BaseModel):
    """
    Safe public representation of a User.

    Notice what is NOT here: hashed_password.
    Even if a bug in the endpoint accidentally fetched the full ORM object,
    Pydantic would only serialize the fields declared in this schema.
    Security through schema design.
    """
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    # WHY model_config with from_attributes=True?
    #   By default Pydantic v2 expects dict input.
    #   from_attributes=True lets it read directly from SQLAlchemy ORM objects.
    #   Without this: UserResponse.model_validate(user_orm_object) would fail.
    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Schema for auth token responses"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    """Internal: decoded JWT payload"""
    sub: str          # subject — the user's UUID as string
    exp: int          # expiry Unix timestamp
    type: str         # "access" or "refresh"
