from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta
from urllib import error, request
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import ensure_utc, now_utc
from app.models.task import Task


def _extract_json_object(text: str) -> str:
    payload = text.strip()
    if payload.startswith("```"):
        lines = payload.splitlines()
        if len(lines) >= 3:
            payload = "\n".join(lines[1:-1]).strip()
    if payload.startswith("json"):
        payload = payload[len("json") :].strip()
    start = payload.find("{")
    if start == -1:
        raise ValueError("No JSON object start")
    depth = 0
    for idx in range(start, len(payload)):
        char = payload[idx]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return payload[start : idx + 1]
    raise ValueError("No balanced JSON object found")


def _normalize_operations(raw_operations: object) -> list[dict]:
    if not isinstance(raw_operations, list):
        return []
    normalized: list[dict] = []
    for item in raw_operations:
        if not isinstance(item, dict):
            continue
        raw_op = str(item.get("op") or item.get("type") or item.get("action") or "").strip().lower()
        op_aliases = {
            "create": "create_task",
            "add": "create_task",
            "new": "create_task",
            "create_task": "create_task",
            "update": "update_task",
            "edit": "update_task",
            "change": "update_task",
            "update_task": "update_task",
            "delete": "delete_task",
            "remove": "delete_task",
            "delete_task": "delete_task",
        }
        op = op_aliases.get(raw_op, raw_op)
        normalized.append(
            {
                "op": op,
                "task_id": item.get("task_id") or item.get("id"),
                "title": item.get("title"),
                "mini_description": item.get("mini_description") or item.get("description"),
                "duration_minutes": item.get("duration_minutes"),
                "date": item.get("date"),
                "time": item.get("time"),
                "category": item.get("category"),
            }
        )
    return normalized


def _normalize_command_payload(raw: object, raw_content: str) -> dict:
    if not isinstance(raw, dict):
        return {
            "summary": "Не удалось надежно распознать ответ AI.",
            "operations": [],
            "need_clarification": True,
            "clarification_question": "Уточни, пожалуйста, что именно нужно сделать с задачей.",
        }

    summary = raw.get("summary") or raw.get("explanation") or raw.get("message") or ""
    need_clarification = bool(raw.get("need_clarification", False))
    clarification = raw.get("clarification_question") or raw.get("question")
    operations = _normalize_operations(raw.get("operations") or raw.get("actions") or [])

    if not isinstance(summary, str):
        summary = str(summary)
    if clarification is not None and not isinstance(clarification, str):
        clarification = str(clarification)

    if not operations and not need_clarification:
        need_clarification = True
        if not clarification:
            clarification = "Уточни, пожалуйста, какую именно задачу создать, обновить или удалить."
        if not summary:
            summary = raw_content.strip()[:400]

    return {
        "summary": summary,
        "operations": operations,
        "need_clarification": need_clarification,
        "clarification_question": clarification,
    }


class DeepSeekOperation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    op: str = ""
    task_id: str | None = None
    title: str | None = None
    mini_description: str | None = None
    duration_minutes: int | None = None
    date: str | None = None
    time: str | None = None
    category: str | None = None


class DeepSeekCommand(BaseModel):
    model_config = ConfigDict(extra="ignore")

    summary: str = ""
    operations: list[DeepSeekOperation] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None


@dataclass(frozen=True)
class AIAction:
    type: str
    task_id: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"type": self.type, "task_id": self.task_id}


class AIMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._success = 0
        self._failed = 0
        self._latency_sum = 0.0
        self._latency_count = 0

    def mark_success(self) -> None:
        with self._lock:
            self._success += 1

    def mark_failed(self) -> None:
        with self._lock:
            self._failed += 1

    def observe_latency(self, duration_seconds: float) -> None:
        with self._lock:
            self._latency_sum += duration_seconds
            self._latency_count += 1

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            avg = self._latency_sum / self._latency_count if self._latency_count else 0.0
            return {
                "ai_commands_success_total": self._success,
                "ai_commands_failed_total": self._failed,
                "deepseek_avg_latency_seconds": round(avg, 4),
            }


ai_metrics = AIMetrics()


def build_system_prompt(timezone_name: str, now_value: datetime) -> str:
    return (
        "You are Fokusly backend task assistant.\n"
        "Return ONLY strict JSON with keys: summary, operations, need_clarification, clarification_question.\n"
        "Allowed operations: create_task, update_task, delete_task.\n"
        "For create_task require title/date/time. For update_task require task_id and at least one changed field.\n"
        "Do not include markdown.\n"
        f"User timezone: {timezone_name}. Current datetime in user timezone: "
        f"{ensure_utc(now_value).astimezone(ZoneInfo(timezone_name)).isoformat()}."
    )


def _extract_deepseek_content(payload: dict) -> str:
    try:
        return str(payload["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AppError(status_code=502, code="BAD_GATEWAY", message="Could not parse AI response") from exc


def _deepseek_request(messages: list[dict[str, str]]) -> DeepSeekCommand:
    if not settings.deepseek_api_key:
        raise AppError(status_code=503, code="SERVICE_UNAVAILABLE", message="AI service temporary unavailable")

    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": settings.deepseek_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 3000,
        "response_format": {"type": "json_object"},
    }
    req = request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.deepseek_api_key}",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with request.urlopen(req, timeout=settings.deepseek_timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        ai_metrics.mark_failed()
        ai_metrics.observe_latency(time.perf_counter() - started)
        raise AppError(status_code=503, code="SERVICE_UNAVAILABLE", message="AI service temporary unavailable") from exc

    ai_metrics.observe_latency(time.perf_counter() - started)
    try:
        parsed = json.loads(body)
        content = _extract_deepseek_content(parsed)
        try:
            command_payload = json.loads(_extract_json_object(content))
        except ValueError:
            command_payload = {}
        normalized_payload = _normalize_command_payload(command_payload, content)
        command = DeepSeekCommand.model_validate(normalized_payload)
    except (json.JSONDecodeError, ValidationError, AppError) as exc:
        ai_metrics.mark_failed()
        raise AppError(status_code=502, code="BAD_GATEWAY", message="Could not parse AI response") from exc

    ai_metrics.mark_success()
    return command


def call_deepseek(user_message: str, timezone_name: str, recent_tasks: list[Task]) -> DeepSeekCommand:
    tasks_context = [
        {
            "id": task.id,
            "title": task.title,
            "mini_description": task.mini_description,
            "duration_minutes": task.duration_minutes,
            "start_at_utc": ensure_utc(task.start_at).isoformat(),
            "category": task.category,
        }
        for task in recent_tasks
    ]
    messages = [
        {"role": "system", "content": build_system_prompt(timezone_name, now_utc())},
        {
            "role": "user",
            "content": json.dumps(
                {"message": user_message, "known_tasks": tasks_context},
                ensure_ascii=False,
            ),
        },
    ]
    return _deepseek_request(messages)


def parse_user_datetime(local_date: str, local_time: str, timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
        normalized_date = local_date.strip().lower()
        if normalized_date in {"today", "сегодня"}:
            parsed_date = ensure_utc(now_utc()).astimezone(zone).date()
        elif normalized_date in {"tomorrow", "завтра"}:
            parsed_date = ensure_utc(now_utc()).astimezone(zone).date() + timedelta(days=1)
        else:
            parsed_date = date.fromisoformat(local_date)

        normalized_time = local_time.strip().replace(".", ":")
        if ":" not in normalized_time:
            normalized_time = f"{normalized_time}:00"
        hour_str, minute_str = normalized_time.split(":", 1)
        parsed_time = dt_time(hour=int(hour_str), minute=int(minute_str))
    except Exception as exc:
        raise AppError(status_code=422, code="VALIDATION_ERROR", message="Invalid date/time in AI command") from exc
    return datetime.combine(parsed_date, parsed_time, tzinfo=zone)
