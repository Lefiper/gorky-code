# syntax=docker/dockerfile:1
FROM python:3.13-slim-bookworm@sha256:e32be0e55814a08977501ca863271d9bd02443710db8f2afaf8372e2c4508530
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
WORKDIR /app
COPY requirements.linux.lock.txt ./requirements.linux.lock.txt
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r requirements.linux.lock.txt
RUN useradd --create-home --uid 10001 assistant
COPY --chown=assistant:assistant app ./app
COPY --chown=assistant:assistant sql ./sql
COPY --chown=assistant:assistant tests ./tests
COPY --chown=assistant:assistant scripts ./scripts
USER assistant
EXPOSE 8001
CMD ["python", "-m", "app.mcp_server", "--transport", "http", "--host", "0.0.0.0"]
