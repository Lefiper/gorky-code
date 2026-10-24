FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py .
RUN useradd --create-home bot && mkdir state && chown bot:bot state
USER bot
EXPOSE 8080
CMD ["python", "bot.py", "webhook"]
