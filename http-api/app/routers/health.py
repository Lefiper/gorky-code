from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.dependencies import get_repository
from app.schemas import HealthOut
from app.storage import EventRepository

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthOut,
    summary="Проверка готовности API и PostgreSQL",
    responses={503: {"model": HealthOut, "description": "PostgreSQL недоступен"}},
)
def health(repository: EventRepository = Depends(get_repository)) -> dict | JSONResponse:
    try:
        repository.ping()
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
