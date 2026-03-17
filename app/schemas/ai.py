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


class SendAIMessageResponse(BaseModel):
    reply: str
    created_at: str
