from __future__ import annotations

from datetime import date as Date
from datetime import datetime as DateTime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.auth import MaxUser
from app.config import Settings
from app.dependencies import get_current_user, get_repository, get_settings
from app.errors import NotFoundError, ValidationError
from app.schemas import EventCreateIn, EventCreateOut, EventListOut, EventOut, EventType, EventUpdateStatusIn
from app.storage import EventRepository, day_bounds, normalize_range

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    responses={
        401: {"description": "Нет или недействителен MAX initData."},
        503: {"description": "PostgreSQL недоступен."},
    },
)


def _resolve_period(
    date: Date | None,
    from_: DateTime | None,
    to: DateTime | None,
    timezone_name: str,
) -> tuple[DateTime, DateTime]:
    if date is not None:
        if from_ is not None or to is not None:
            raise ValidationError("Укажите либо date, либо from/to, но не вместе.")
        return day_bounds(date, timezone_name)

    if from_ is None or to is None:
        raise ValidationError("Укажите date или обе границы from и to.")

    start, end = normalize_range(from_, to, required=True)
    if start is None or end is None:
        raise ValidationError("Укажите date или обе границы from и to.")
    return start, end


@router.get("", response_model=EventListOut, summary="События за день или период")
def list_tasks(
    date: Date | None = Query(default=None, description="День в часовом поясе timezone."),
    from_: DateTime | None = Query(default=None, alias="from", description="Начало периода включительно, ISO 8601 с offset."),
    to: DateTime | None = Query(default=None, description="Конец периода исключительно, ISO 8601 с offset."),
    event_type: list[EventType] | None = Query(default=None, description="Фильтр типа; можно передать несколько раз."),
    timezone_name: str | None = Query(default=None, alias="timezone", description="IANA-таймзона для date."),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    settings: Settings = Depends(get_settings),
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    start, end = _resolve_period(date, from_, to, timezone_name or settings.default_timezone)
    return repository.list_events(
        user_id=user.id,
        start_time=start,
        end_time=end,
        event_types=event_type,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=EventListOut, summary="Полнотекстовый поиск событий")
def search_tasks(
    q: str = Query(min_length=1, max_length=1000, description="Поисковый текст."),
    from_: DateTime | None = Query(default=None, alias="from", description="Необязательное начало периода включительно."),
    to: DateTime | None = Query(default=None, description="Необязательный конец периода исключительно."),
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    return repository.search_events(
        user_id=user.id,
        text=q,
        start_time=from_,
        end_time=to,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=EventCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="Создать событие",
    responses={
        200: {"model": EventCreateOut, "description": "Повтор идемпотентной операции."},
        409: {"description": "Idempotency-Key уже использован с другими данными."},
    },
)
def create_task(
    payload: EventCreateIn,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    result = repository.create_event(
        user_id=user.id,
        event_type=payload.event_type,
        name=payload.name,
        event_at=payload.event_at,
        description=payload.description,
        duration_minutes=payload.duration_minutes,
        status=payload.status,
        idempotency_key=idempotency_key,
    )
    if not result["created"]:
        response.status_code = status.HTTP_200_OK
    return result


@router.get("/{event_id}", response_model=EventOut, summary="Событие по ID", responses={
    404: {"description": "Событие не найдено или принадлежит другому пользователю."}
})
def get_task(
    event_id: UUID,
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    return repository.get_event_by_id(user.id, event_id)


@router.patch(
    "/{event_id}",
    response_model=EventOut,
    summary="Изменить статус события",
    responses={
        404: {"description": "Событие не найдено или принадлежит другому пользователю."},
    },
)
def update_task_status(
    event_id: UUID,
    payload: EventUpdateStatusIn,
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> dict:
    result = repository.update_event_status(user.id, event_id, payload.status)
    if result is None:
        raise NotFoundError()
    return result


@router.delete(
    "/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить событие",
    responses={
        404: {"description": "Событие не найдено или принадлежит другому пользователю."},
    },
)
def delete_task(
    event_id: UUID,
    user: MaxUser = Depends(get_current_user),
    repository: EventRepository = Depends(get_repository),
) -> None:
    if not repository.delete_event(user.id, event_id):
        raise NotFoundError()
