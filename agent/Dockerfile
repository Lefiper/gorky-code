# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8
WORKDIR /app

COPY agent/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip python -m pip install -r requirements.txt

RUN useradd --create-home --uid 10003 agent
COPY agent/app ./app
COPY agent/prompts ./prompts
COPY shared ./shared
COPY mcp_server/app ./calendar_storage
RUN chmod -R a+rX /app/app /app/prompts /app/shared /app/calendar_storage
USER agent
EXPOSE 8003

HEALTHCHECK --interval=10s --timeout=5s --retries=6 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=4).read()"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8003"]
