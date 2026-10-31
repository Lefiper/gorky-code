# syntax=docker/dockerfile:1
# Контекст сборки — корень репозитория (docker-compose.yml): миграции лежат в db/migrations.
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \
    MIGRATIONS_DIR=/app/db/migrations
WORKDIR /app

COPY mcp_server/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r requirements.txt

RUN useradd --create-home --uid 10001 assistant
COPY mcp_server/app ./app
COPY mcp_server/scripts ./scripts
COPY mcp_server/tests ./tests
# Shared-contract test imports only the API repository, not the API web service.
COPY api/app/storage.py api/app/errors.py api/app/__init__.py ./api/app/
COPY db/migrations ./db/migrations
RUN chmod -R a+rX /app/app /app/scripts /app/tests /app/api /app/db
USER assistant
EXPOSE 8001
CMD ["python", "-m", "app.mcp_server", "--transport", "http", "--host", "0.0.0.0"]
