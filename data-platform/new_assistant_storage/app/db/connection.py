"""Один вызов connect — одно соединение; вызывающая функция закрывает его через with."""

import psycopg
from psycopg.rows import dict_row

from app.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.host,
        port=settings.port,
        dbname=settings.dbname,
        user=settings.user,
        password=settings.password,
        connect_timeout=settings.connect_timeout,
        options="-c timezone=UTC -c statement_timeout=10000 -c lock_timeout=5000",
        application_name="assistant_mvp",
        row_factory=dict_row,
    )
