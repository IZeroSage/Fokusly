from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    id: str
    title: str
    mini_description: str
    duration_minutes: int
    start_at: str
    category: str


class TasksListResponse(BaseModel):
    items: list[TaskResponse]
    page: int
    size: int
    total: int


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    mini_description: str = Field(default="", max_length=400)
    duration_minutes: int = Field(ge=1, le=24 * 60)
    start_at: datetime
    category: str = Field(min_length=1, max_length=60)
    source_note_id: str | None = None


class UpdateTaskRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    mini_description: str | None = Field(default=None, max_length=400)
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    start_at: datetime | None = None
    category: str | None = Field(default=None, min_length=1, max_length=60)
    source_note_id: str | None = None


class ScheduleDayItem(BaseModel):
    id: str
    time: str
    title: str
    subtitle: str
    duration_minutes: int
    category: str


class DayScheduleResponse(BaseModel):
    date: str
    tasks_count: int
    day_load_label: str
    items: list[ScheduleDayItem]


class WeekDayResponse(BaseModel):
    date: str
    tasks_count: int


class WeekScheduleResponse(BaseModel):
    days: list[WeekDayResponse]


class MonthDayResponse(BaseModel):
    day: int
    tasks_count: int
    is_selected: bool


class MonthScheduleResponse(BaseModel):
    year: int
    month: int
    selected_day: int
    days: list[MonthDayResponse]


class YearMonthResponse(BaseModel):
    month: int
    active_days: list[int]


class YearScheduleResponse(BaseModel):
    year: int
    months: list[YearMonthResponse]


class GenerateScheduleRequest(BaseModel):
    date: date
    mode: Literal["balanced", "deep_focus", "light"] = "balanced"


class GenerateScheduleResponse(BaseModel):
    success: bool
    created_tasks: int
    message: str
