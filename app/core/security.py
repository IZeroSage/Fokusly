from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.core.exceptions import AppError


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_iso_utc(value: datetime) -> str:
    return ensure_utc(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_email(email: str) -> str:
    normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Email is invalid",
            details={"field": "email"},
        )
    return normalized


def validate_password(password: str, field_name: str = "password") -> None:
    if len(password) < 8:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Password must be at least 8 characters",
            details={"field": field_name},
        )


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_payload(payload: str) -> str:
    raw = hmac.new(settings.secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    return b64url_encode(raw)


def encode_token(payload: dict[str, Any]) -> str:
    encoded = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{encoded}.{sign_payload(encoded)}"


def decode_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 2:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token")
    encoded_payload, signature = parts
    if not hmac.compare_digest(signature, sign_payload(encoded_payload)):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token signature")
    try:
        payload = json.loads(b64url_decode(encoded_payload))
    except (json.JSONDecodeError, ValueError):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token payload")

    exp = payload.get("exp")
    if not isinstance(exp, int) or int(now_utc().timestamp()) >= exp:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Token expired")
    return payload
