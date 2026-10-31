"""Системный промпт с серверным временем, часовым поясом и доверенным user_id."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path

EVENT_TYPES = ("task", "reminder", "meeting", "project")
WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "system_prompt.md"


def server_now(zone, *, clock=None) -> datetime:
    """Серверное время с точностью до секунды в часовом поясе пользователя."""
    current = clock() if clock is not None else datetime.now(zone)
    return current.astimezone(zone).replace(microsecond=0)


def render_system_prompt(*, now: datetime, timezone_name: str, user_id: str, template: str | None = None) -> str:
    text = template if template is not None else PROMPT_PATH.read_text(encoding="utf-8")
    replacements = {
        "{{now}}": now.replace(microsecond=0).isoformat(),
        "{{weekday}}": WEEKDAYS_RU[now.weekday()],
        "{{timezone}}": timezone_name,
        "{{user_id}}": user_id,
        "{{event_types}}": ", ".join(EVENT_TYPES),
    }
    for placeholder, value in replacements.items():
        text = text.replace(placeholder, value)
    if template is not None:
        return text
    return text + "\nЛюбое создание, удаление или перенос требует отдельного подтверждения. Обрабатывай действия по одному. При неоднозначном поиске спроси, какое событие выбрано. Не утверждай успех без ответа инструмента."
