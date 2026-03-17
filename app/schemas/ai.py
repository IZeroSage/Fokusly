from __future__ import annotations

from pydantic import BaseModel, Field


class AIMessageItem(BaseModel):
    id: str
    role: str
    text: str
    created_at: str


class AIHistoryResponse(BaseModel):
    items: list[AIMessageItem]


class SendAIMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    request_id: str | None = Field(default=None, max_length=128)


class AIActionItem(BaseModel):
    type: str
    task_id: str | None = None


class SendAIMessageResponse(BaseModel):
    reply: str
    actions: list[AIActionItem]
    created_at: str
