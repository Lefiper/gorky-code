"""Доменные ошибки, которые превращаются в HTTP-ответы."""

from __future__ import annotations


class ApiError(Exception):
    status_code = 500
    default_detail = "Внутренняя ошибка сервиса."

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class AuthError(ApiError):
    status_code = 401
    default_detail = "Недействительные данные авторизации MAX."


class NotFoundError(ApiError):
    status_code = 404
    default_detail = "Событие не найдено."


class ConflictError(ApiError):
    status_code = 409
    default_detail = "Конфликт идемпотентности."


class ValidationError(ApiError):
    status_code = 422
    default_detail = "Некорректные параметры запроса."


class StorageError(ApiError):
    status_code = 503
    default_detail = "Хранилище временно недоступно."
