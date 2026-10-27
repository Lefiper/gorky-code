"""Pydantic-схемы HTTP-контракта."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

EventType = Literal["task", "reminder", "meeting", "project"]
EventStatus = Literal["pending", "new", "progress", "done", "blocked", "cancelled"]


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: str
    event_type: EventType
    name: str
    description: str
    event_at: datetime
    created_at: datetime
    status: EventStatus
    duration_minutes: int | None = None

    @field_serializer("event_at", "created_at")
    def _serialize_datetime(self, value: datetime) -> str:
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class EventListOut(BaseModel):
    items: list[EventOut]
    has_more: bool


class EventCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_type: EventType
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10000)
    event_at: datetime
    duration_minutes: int | None = None
    status: EventStatus = "new"

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name не может быть пустым.")
        return value

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str) -> str:
        return value.strip()

    @field_validator("event_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_at должен содержать часовое смещение, например +03:00.")
        return value

    @field_validator("duration_minutes")
    @classmethod
    def _validate_duration(cls, value: int | None) -> int | None:
        if value is None:
            return None
        if type(value) is not int or isinstance(value, bool) or not 1 <= value <= 2147483647:
            raise ValueError("duration_minutes: положительное целое число минут или null.")
        return value


class EventCreateOut(BaseModel):
    event: EventOut
    created: bool


class EventUpdateStatusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: EventStatus


class TimezoneIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = Field(min_length=1, max_length=100)


class TimezoneOut(BaseModel):
    timezone: str | None = None


class TimezoneResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: str = Field(min_length=10, max_length=10)
    time: str = Field(min_length=4, max_length=8)


class TimezoneResolveOut(BaseModel):
    event_at: str


class HealthOut(BaseModel):
    status: Literal["ok", "unavailable"]


class MeOut(BaseModel):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    language_code: str | None = None
    photo_url: str | None = None
