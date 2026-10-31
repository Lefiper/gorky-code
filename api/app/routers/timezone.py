from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import MaxUser
from app.dependencies import get_current_user, get_repository, get_settings
from app.config import Settings
from app.schemas import TimezoneIn, TimezoneOut, TimezoneResolveIn, TimezoneResolveOut
from app.storage import EventRepository

router = APIRouter(
    prefix="/timezone",
    tags=["timezone"],
    responses={
        401: {"description": "Нет или недействителен MAX initData."},
        503: {"description": "PostgreSQL недоступен."},
    },
)


@router.get("", response_model=TimezoneOut, summary="Таймзона пользователя")
def get_timezone(
    settings: Settings = Depends(get_settings),
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    return {"timezone": repository.get_user_timezone(user.id) or settings.default_timezone}


@router.put("", response_model=TimezoneOut, summary="Установить таймзону пользователя")
def set_timezone(
    payload: TimezoneIn,
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    result = repository.set_user_timezone(user.id, payload.timezone)
    return {"timezone": result["timezone"]}


@router.post("/resolve", response_model=TimezoneResolveOut, summary="Преобразовать локальную дату/время в UTC ISO")
def resolve_timezone(
    payload: TimezoneResolveIn,
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    return {"event_at": repository.resolve_local_datetime(user.id, payload.date, payload.time)}
