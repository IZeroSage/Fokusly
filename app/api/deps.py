from __future__ import annotations

from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User

auth_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Missing bearer token")

    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token type")

    user_id = payload.get("sub")
    user = db.get(User, user_id)
    if user is None:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="User not found")
    return user


def paginate(items: list[dict[str, Any]], page: int, size: int) -> dict[str, Any]:
    total = len(items)
    start = (page - 1) * size
    end = start + size
    return {"items": items[start:end], "page": page, "size": size, "total": total}
