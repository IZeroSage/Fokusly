from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SuccessResponse(BaseModel):
    success: bool = True


class SuccessMessageResponse(BaseModel):
    success: bool = True
    message: str


class PaginationQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


def to_model_dict(model: Any, *, exclude_unset: bool = False) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)
