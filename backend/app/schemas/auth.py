"""Auth request/response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

DELETE_CONFIRMATION_PHRASE = "delete my account"


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class UserOut(BaseModel):
    id: str
    email: str
    created_at: datetime


class AuthResponse(BaseModel):
    user: UserOut
    # Echoed so the SPA can send it back in the X-CSRF-Token header. It is
    # bound to the HttpOnly session cookie and useless without it.
    csrf_token: str


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)
    confirmation: Literal["delete my account"] = Field(description=f'Must be exactly "{DELETE_CONFIRMATION_PHRASE}".')
