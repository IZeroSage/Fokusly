from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class UserPublic(BaseModel):
    id: str
    display_name: str
    email: str
    avatar_initial: str


class AuthResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserPublic


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    new_password_repeat: str


class UserSettingsPayload(BaseModel):
    language: str
    theme: Literal["light", "dark"]
    smart_planning: bool
    ai_suggestions: bool
    timezone: str = "Europe/Moscow"


class SubscriptionResponse(BaseModel):
    plan: str
    status: str
    renews_at: str | None = None
