"""Настройки сервиса из переменных окружения и .env."""

from __future__ import annotations

from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.storage import PgConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    app_env: Literal["development", "test", "production"] = Field(
        default="development", validation_alias="APP_ENV"
    )
    api_prefix: str = Field(default="/api", validation_alias="API_PREFIX")
    cors_origins: str = Field(default="*", validation_alias="CORS_ORIGINS")
    default_timezone: str = Field(default="Europe/Moscow", validation_alias="DEFAULT_TIMEZONE")

    pg_host: str = Field(default="127.0.0.1", validation_alias="PGHOST")
    pg_port: int = Field(default=55432, validation_alias="PGPORT")
    pg_database: str = Field(default="assistant_mvp", validation_alias="PGDATABASE")
    pg_user: str = Field(default="assistant_api", validation_alias="PGUSER")
    pg_password: SecretStr = Field(validation_alias="PGPASSWORD")
    pg_connect_timeout: int = Field(default=5, validation_alias="PGCONNECT_TIMEOUT")

    max_bot_token: SecretStr = Field(default="", validation_alias="MAX_BOT_TOKEN")
    max_init_data_ttl_seconds: int = Field(
        default=3600, ge=60, le=86400, validation_alias="MAX_INIT_DATA_TTL_SECONDS"
    )

    auth_dev_mode: bool = Field(default=False, validation_alias="AUTH_DEV_MODE")
    dev_user_id: str = Field(default="dev:1", validation_alias="DEV_USER_ID")

    @field_validator("pg_password")
    @classmethod
    def _validate_pg_password(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("PGPASSWORD не может быть пустым.")
        return value

    @field_validator("default_timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:  # ZoneInfoNotFoundError/ValueError
            raise ValueError("DEFAULT_TIMEZONE: неизвестный часовой пояс IANA.") from exc
        return value

    @field_validator("api_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_PREFIX должен начинаться с / и не заканчиваться на /.")
        return value

    @model_validator(mode="after")
    def _validate_auth(self) -> Settings:
        if self.auth_dev_mode and self.app_env != "development":
            raise ValueError("AUTH_DEV_MODE разрешён только при APP_ENV=development.")
        if not self.auth_dev_mode and not self.max_bot_token.get_secret_value().strip():
            raise ValueError("MAX_BOT_TOKEN обязателен, если AUTH_DEV_MODE выключен.")
        if not 1 <= self.pg_port <= 65535:
            raise ValueError("PGPORT: допустимый диапазон 1–65535.")
        if not 1 <= self.pg_connect_timeout <= 60:
            raise ValueError("PGCONNECT_TIMEOUT: допустимый диапазон 1–60 секунд.")
        if self.auth_dev_mode and not self.dev_user_id.strip():
            raise ValueError("DEV_USER_ID не может быть пустым.")
        return self

    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def pg_config(self) -> PgConfig:
        return PgConfig(
            host=self.pg_host,
            port=self.pg_port,
            dbname=self.pg_database,
            user=self.pg_user,
            password=self.pg_password.get_secret_value(),
            connect_timeout=self.pg_connect_timeout,
        )
