from __future__ import annotations

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    email: str
    password: str
    password_repeat: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str
    new_password_repeat: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str


class PasswordResetRequestResponse(BaseModel):
    success: bool = True
    message: str = "Reset email sent"
