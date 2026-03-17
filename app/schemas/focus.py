from __future__ import annotations

from pydantic import BaseModel


class FocusSummaryResponse(BaseModel):
    focus_minutes: int
    tasks_done: int
    completion_rate: float
    best_hours: str
    stress_level: str
    ai_tip: str
