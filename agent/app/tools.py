"""Инструменты календаря для GigaChat. user_id подставляет только backend, модель его не видит."""

from __future__ import annotations

from datetime import datetime as DateTime
from typing import Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.mcp_client import CalendarMCP, MCPError
from app.prompt import WEEKDAYS_RU

EventType = Literal["task", "reminder", "meeting", "project"]


class CreateEventInput(BaseModel):
    event_type: EventType = Field(description="task — задача, reminder — напоминание, meeting — встреча, project — проект.")
    name: str = Field(min_length=1, max_length=200, description="Краткое подтверждённое название события.")
    datetime: str = Field(description="Дата и время ISO 8601 с часовым смещением, например 2026-10-30T15:00:00+03:00.")
    description: str = Field(default="", max_length=10000, description="Только детали, которые сообщил пользователь; иначе пустая строка.")


class GetEventInput(BaseModel):
    start_time: str = Field(description="Начало периода включительно, ISO 8601 с часовым смещением.")
    end_time: str = Field(description="Конец периода исключительно, ISO 8601 с часовым смещением.")
    event_type: list[EventType] | None = Field(default=None, description="Фильтр типов, например [\"meeting\"]; null — все типы.")


class GetEventByQueryInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="Поисковые слова по названию и описанию.")
    start_time: str | None = Field(default=None, description="Необязательное начало периода, ISO 8601 с смещением.")
    end_time: str | None = Field(default=None, description="Необязательный конец периода, ISO 8601 с смещением.")


class DeleteEventInput(BaseModel):
    event_id: str = Field(min_length=1, description="UUID события из get_event или get_event_by_query.")
    name: str = Field(min_length=1, max_length=200, description="Название события — для показа пользователю в подтверждении.")
    datetime: str = Field(description="Дата и время события ISO 8601 — для показа пользователю в подтверждении.")
    event_type: EventType = Field(description="Тип события.")


class UpdateEventTimeInput(BaseModel):
    event_id: str = Field(min_length=1, description="UUID события из get_event или get_event_by_query.")
    name: str = Field(min_length=1, max_length=200, description="Название события — для показа пользователю в подтверждении.")
    datetime: str = Field(description="Новое время ISO 8601 с часовым смещением.")
    event_type: EventType = Field(description="Тип события.")


class CalendarTools:
    """Инструменты одного сообщения пользователя. user_id и idempotency-ключи задаёт сервер."""

    def __init__(self, mcp: CalendarMCP, *, user_id: str, message_id: str, zone):
        self.mcp = mcp
        self.user_id = user_id
        self.message_id = message_id
        self.zone = zone
        self._creates = 0

    async def _call(self, name: str, arguments: dict) -> dict:
        try:
            return await self.mcp.call(name, arguments)
        except MCPError as exc:
            return {"error": str(exc)}

    async def create_event(self, event_type, name, datetime, description="") -> dict:
        self._creates += 1
        key = f"{self.message_id}:create:{self._creates}"
        return await self._call("create_event", {
            "user_id": self.user_id,
            "event_type": event_type,
            "name": name,
            "datetime": datetime,
            "description": description,
            "idempotency_key": key,
        })

    async def get_event(self, start_time, end_time, event_type=None) -> dict:
        data = await self._call("get_event", {
            "user_id": self.user_id,
            "start_time": start_time,
            "end_time": end_time,
            "event_type": event_type,
        })
        return self._localize(data)

    async def get_event_by_query(self, text, start_time=None, end_time=None) -> dict:
        data = await self._call("get_event_by_query", {
            "user_id": self.user_id,
            "text": text,
            "start_time": start_time,
            "end_time": end_time,
        })
        return self._localize(data)

    async def delete_event(self, event_id, name, datetime, event_type) -> dict:
        """Предложение удаления — backend покажет подтверждение, фактически не удаляет."""
        return {"_proposal": "delete", "event_id": event_id, "name": name,
                "datetime": datetime, "event_type": event_type}

    async def update_event_time(self, event_id, name, datetime, event_type) -> dict:
        """Предложение переноса — backend покажет подтверждение, фактически не меняет."""
        return {"_proposal": "reschedule", "event_id": event_id, "name": name,
                "datetime": datetime, "event_type": event_type}

    def _localize(self, data: dict) -> dict:
        for item in data.get("items", []):
            local = DateTime.fromisoformat(item["event_at"].replace("Z", "+00:00")).astimezone(self.zone)
            item["local_event_at"] = local.isoformat()
            item["local_weekday"] = WEEKDAYS_RU[local.weekday()]
        return data


def build_tools(box: CalendarTools) -> list[StructuredTool]:
    return [
        StructuredTool.from_function(
            coroutine=box.create_event,
            name="create_event",
            description="Подготовить предложение события с известными параметрами. Сервер запросит подтверждение и сохранит событие только после отдельного согласия.",
            args_schema=CreateEventInput,
        ),
        StructuredTool.from_function(
            coroutine=box.get_event,
            name="get_event",
            description="Получить события пользователя за период. Пустой items означает, что событий нет.",
            args_schema=GetEventInput,
        ),
        StructuredTool.from_function(
            coroutine=box.get_event_by_query,
            name="get_event_by_query",
            description="Найти события по словам в названии и описании (русские формы слов, запасной поиск по любому слову).",
            args_schema=GetEventByQueryInput,
        ),
        StructuredTool.from_function(
            coroutine=box.delete_event,
            name="delete_event",
            description="Подготовить предложение удаления события. Сначала найди событие через get_event_by_query, получи его event_id. Сервер запросит подтверждение у пользователя.",
            args_schema=DeleteEventInput,
        ),
        StructuredTool.from_function(
            coroutine=box.update_event_time,
            name="update_event_time",
            description="Подготовить предложение переноса события на новое время. Сначала найди событие через get_event_by_query, получи его event_id. Сервер запросит подтверждение у пользователя.",
            args_schema=UpdateEventTimeInput,
        ),
    ]
