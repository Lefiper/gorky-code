from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import MaxUser
from app.dependencies import get_current_user
from app.schemas import MeOut

router = APIRouter(
    tags=["me"],
    responses={401: {"description": "Нет или недействителен MAX initData."}},
)


@router.get("/me", response_model=MeOut, summary="Текущий пользователь из MAX initData")
def me(user: MaxUser = Depends(get_current_user)) -> MaxUser:
    return user
