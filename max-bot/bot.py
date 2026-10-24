"""MAX transport module. Python 3.11+, standard library only."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import ssl
import threading
import time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlencode, urlsplit
from urllib.error import URLError
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("max_bot")
HELP = ("Я помогаю с задачами, напоминаниями и встречами. Напишите или отправьте голосовое:\n"
        "• Напомни завтра в 10 позвонить Ивану\n"
        "• Добавь встречу в пятницу в 15:00\n"
        "• Что у меня на этой неделе?\n"
        "• Найди задачу про презентацию\n\n"
        "/today — сегодня; /tomorrow — завтра; /app — приложение; /help — помощь.\n"
        "/timezone Europe/Moscow — ваш часовой пояс (по умолчанию Москва).")
QUERIES = {"today": "Что у меня сегодня?", "tomorrow": "Что у меня завтра?"}
ERROR = "Не удалось получить результат. Я не могу подтвердить сохранение. Повторите запрос позже."


def load_env():
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def tz(name):
    # Moscow has a fixed offset; works on Windows even without tzdata installed.
    if name == "Europe/Moscow":
        return timezone(timedelta(hours=3))
    if name == "UTC":
        return timezone.utc
    return ZoneInfo(name)


def event_key(event):
    kind = event.get("update_type")
    if kind == "message_created":
        mid = (event.get("message", {}).get("body") or {}).get("mid")
        if not mid:
            raise ValueError("missing message ID")
        return "message:" + str(mid)
    if kind == "message_callback":
        cid = event.get("callback", {}).get("callback_id")
        if not cid:
            raise ValueError("missing callback ID")
        return "callback:" + str(cid)
    return hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.db:
            self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, event TEXT NOT NULL, response TEXT,
              sent INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS reminders (
              id TEXT PRIMARY KEY, user_id INTEGER NOT NULL, text TEXT NOT NULL,
              due REAL NOT NULL, sent INTEGER NOT NULL DEFAULT 0,
              attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL DEFAULT 0);
            """)

    def execute(self, sql, params=()):
        with self.lock, self.db:
            return self.db.execute(sql, params)

    def enqueue(self, event):
        kind = event.get("update_type")
        if kind not in {"message_created", "message_callback", "bot_started"}:
            return
        self.execute("INSERT OR IGNORE INTO jobs(id,event) VALUES (?,?)",
                     (event_key(event), json.dumps(event)))

    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, str(value)))

    def next_job(self):
        # One worker: preserves conversational order; exhausted jobs do not block users.
        with self.lock:
            return self.db.execute("SELECT * FROM jobs WHERE done=0 AND available<=? "
                                   "ORDER BY rowid LIMIT 1", (time.time(),)).fetchone()

    def remind(self, data):
        rid = str(data["id"])
        uid = int(data["user_id"])
        text = str(data["text"]).strip()
        due = datetime.fromisoformat(data["due_at"].replace("Z", "+00:00"))
        if not rid or len(rid) > 200 or not text or len(text) > 3500 or not due.tzinfo:
            raise ValueError("invalid reminder")
        # Stable IDs are mandatory. A repeated registration cannot reset a sent reminder.
        with self.lock, self.db:
            old = self.db.execute("SELECT * FROM reminders WHERE id=?", (rid,)).fetchone()
            if old and (old["user_id"] != uid or old["text"] != text or old["due"] != due.timestamp()):
                raise ValueError("reminder ID already belongs to another payload")
            self.db.execute("INSERT OR IGNORE INTO reminders(id,user_id,text,due) VALUES (?,?,?,?)",
                            (rid, uid, text, due.timestamp()))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or follow unvalidated media redirects.


class HTTP:
    def __init__(self):
        context = ssl.create_default_context()
        if os.getenv("EXTRA_CA_FILE"):
            ca_path = Path(os.environ["EXTRA_CA_FILE"])
            if not ca_path.is_absolute():
                ca_path = ROOT / ca_path
            context.load_verify_locations(str(ca_path))
        self.opener = build_opener(HTTPSHandler(context=context), NoRedirect())

    def raw(self, method, url, body=None, headers=None, limit=2_000_000, timeout=90):
        req = Request(url, data=body, headers=headers or {}, method=method)
        with self.opener.open(req, timeout=timeout) as response:
            content = response.read(limit + 1)
        if len(content) > limit:
            raise ValueError("response too large")
        return content

    def json(self, method, url, data=None, headers=None):
        h = {"Content-Type": "application/json", **(headers or {})}
        body = None if data is None else json.dumps(data).encode()
        return json.loads(self.raw(method, url, body, h))


class MaxAPI:
    def __init__(self, http):
        self.http = http
        self.base = os.getenv("MAX_API_URL", "https://platform-api2.max.ru").rstrip("/")
        self.headers = {"Authorization": os.environ["MAX_BOT_TOKEN"]}
        self.last_send = 0.0

    def call(self, method, path, data=None, **query):
        suffix = "?" + urlencode(query) if query else ""
        result = self.http.json(method, self.base + path + suffix, data, self.headers)
        if result.get("success") is False or result.get("error"):
            raise ValueError("MAX rejected operation")
        return result

    def send(self, user_id, text, attachments=None):
        # Global pacing is intentionally conservative: <=2 messages/sec per dialog.
        time.sleep(max(0, 0.55 - (time.monotonic() - self.last_send)))
        self.last_send = time.monotonic()
        return self.call("POST", "/messages", {"text": text, "attachments": attachments or []},
                         user_id=user_id)


def keyboard():
    rows = [[{"type": "callback", "text": "Сегодня", "payload": "today"},
             {"type": "callback", "text": "Завтра", "payload": "tomorrow"}],
            [{"type": "callback", "text": "Помощь", "payload": "help"}]]
    # A MAX deep link opens the already registered mini app.
    link = os.getenv("MINI_APP_LINK", "")
    if link:
        rows.append([{"type": "link", "text": "Открыть задачи", "url": link}])
    return [{"type": "inline_keyboard", "payload": {"buttons": rows}}]


class Bot:
    def __init__(self, store, http, api):
        self.store, self.http, self.api = store, http, api
        self.stop = threading.Event()

    def speech(self, attachment):
        url = attachment.get("payload", {}).get("url", "")
        parsed = urlsplit(url)
        allowed = {x.strip().lower() for x in os.getenv("AUDIO_ALLOWED_HOSTS", "").split(",") if x.strip()}
        # Exact trusted CDN hostnames, not arbitrary URLs supplied in a message.
        if parsed.scheme != "https" or parsed.hostname not in allowed or parsed.username or parsed.port not in (None, 443):
            raise ValueError("audio host not configured")
        endpoint = os.getenv("STT_URL", "")
        if not endpoint:
            raise ValueError("STT not configured")
        audio = self.http.raw("GET", url, limit=int(os.getenv("MAX_AUDIO_BYTES", "20000000")), timeout=45)
        # In-memory audio: no temporary recordings on disk.
        boundary = "maxbot" + uuid.uuid4().hex
        suffix = Path(parsed.path).suffix.lower()
        if suffix not in {".ogg", ".mp3", ".m4a", ".wav", ".webm", ".mp4"}:
            suffix = ".ogg"
        parts = []
        for key, val in {"model": os.getenv("STT_MODEL", "whisper-1"), "language": "ru"}.items():
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{val}\r\n'.encode())
        parts.append((f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
                      f'filename="voice{suffix}"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()
                     + audio + f'\r\n--{boundary}--\r\n'.encode())
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        if os.getenv("STT_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["STT_API_KEY"]
        result = json.loads(self.http.raw("POST", endpoint, b"".join(parts), headers))
        text = result.get("text", "").strip()
        if not text or len(text) > 16000:
            raise ValueError("empty or oversized transcription")
        return text

    def agent(self, uid, mid, text):
        if os.getenv("AGENT_MODE", "http") == "mock":
            return {"reply": "Тестовый режим. Получен текст: " + text + "\nДанные не сохранены."}
        zone = self.store.setting(f"tz:{uid}", "Europe/Moscow")
        payload = {"user_id": str(uid), "message_id": mid, "conversation_id": f"max:{uid}",
                   "text": text, "timezone": zone,
                   "now": datetime.now(tz(zone)).isoformat()}
        headers = {"Idempotency-Key": mid}
        if os.getenv("AGENT_API_KEY"):
            headers["Authorization"] = "Bearer " + os.environ["AGENT_API_KEY"]
        result = self.http.json("POST", os.environ["AGENT_URL"], payload, headers)
        if not isinstance(result.get("reply"), str) or not result["reply"].strip():
            raise ValueError("invalid agent response")
        return result

    def prepare(self, job):
        event = json.loads(job["event"])
        kind = event["update_type"]
        callback_id = None
        audio = None
        if kind == "bot_started":
            uid = int(event["user"]["user_id"])
            text = "/start"
        elif kind == "message_callback":
            cb = event["callback"]
            uid = int(cb["user"]["user_id"])
            callback_id = cb["callback_id"]
            text = "/" + str(cb.get("payload", ""))
        else:
            msg = event["message"]
            if msg.get("sender", {}).get("is_bot"):
                return {"skip": True}
            # Personal assistant: do not leak a private agenda into a group.
            if msg.get("recipient", {}).get("chat_type") != "dialog":
                return {"skip": True}
            uid = int(msg["sender"]["user_id"])
            body = msg.get("body") or {}
            text = (body.get("text") or "").strip()
            audio = next((a for a in body.get("attachments") or [] if a.get("type") == "audio"), None)
        if callback_id:
            try:
                self.api.call("POST", "/answers", {}, callback_id=callback_id)
            except Exception as exc:
                LOG.warning("callback_ack_failed type=%s", type(exc).__name__)
        if text in {"/start", "/help"}:
            return {"user_id": uid, "reply": HELP}
        if text == "/app":
            return {"user_id": uid, "reply": "Откройте задачи кнопкой ниже." if os.getenv("MINI_APP_LINK")
                    else "Mini App пока не подключено командой."}
        if text.startswith("/timezone "):
            name = text.split(maxsplit=1)[1].strip()
            try:
                tz(name)
            except (ValueError, KeyError):
                return {"user_id": uid, "reply": "Неизвестный часовой пояс. Пример: /timezone Europe/Moscow"}
            self.store.set(f"tz:{uid}", name)
            return {"user_id": uid, "reply": "Часовой пояс установлен: " + name}
        text = QUERIES.get(text.lstrip("/"), text)
        if not text and not audio:
            return {"user_id": uid, "reply": "Пришлите текст или голосовое сообщение."}
        if len(text) > 16000:
            return {"user_id": uid, "reply": "Запрос слишком длинный. Сократите его до 16000 символов."}
        try:
            self.api.send(uid, "Обрабатываю запрос…")
        except Exception as exc:
            LOG.warning("progress_send_failed type=%s", type(exc).__name__)
        if audio:
            try:
                text = self.speech(audio)
            except Exception as exc:
                LOG.warning("speech_failed type=%s", type(exc).__name__)
                return {"user_id": uid, "reply": "Не удалось распознать голосовое. Повторите запись или напишите текстом."}
        # Persist the transcript before invoking a remote side effect.
        saved = self.store.setting("input:" + job["id"])
        if saved:
            text = saved
        else:
            self.store.set("input:" + job["id"], text)
        try:
            result = self.agent(uid, job["id"], text)
        except Exception as exc:
            LOG.warning("agent_failed type=%s", type(exc).__name__)
            return {"user_id": uid, "reply": ERROR}
        return {**result, "user_id": uid}

    def process(self, job):
        result = json.loads(job["response"]) if job["response"] else self.prepare(job)
        # uid always comes from the authenticated MAX event, never from agent output.
        if result.get("skip"):
            self.store.execute("UPDATE jobs SET done=1 WHERE id=?", (job["id"],))
            return
        if not job["response"]:
            self.store.execute("UPDATE jobs SET response=? WHERE id=?", (json.dumps(result), job["id"]))
        uid = result["user_id"]
        reminders = result.get("reminders", [])
        if not isinstance(reminders, list):
            raise ValueError("invalid reminders")
        for item in reminders:
            self.store.remind({**item, "user_id": uid})
        reply = result["reply"]
        chunks = [reply[i:i + 3500] for i in range(0, len(reply), 3500)]
        for index in range(job["sent"], len(chunks)):
            self.api.send(uid, chunks[index], keyboard() if index == len(chunks) - 1 else None)
            self.store.execute("UPDATE jobs SET sent=? WHERE id=?", (index + 1, job["id"]))
        self.store.execute("UPDATE jobs SET done=1 WHERE id=?", (job["id"],))
        self.store.execute("DELETE FROM settings WHERE key=?", ("input:" + job["id"],))

    def reminders(self):
        with self.store.lock:
            rows = self.store.db.execute("SELECT * FROM reminders WHERE sent=0 AND due<=? "
                                         "AND available<=? AND attempts<5 LIMIT 20",
                                         (time.time(), time.time())).fetchall()
        for row in rows:
            try:
                self.api.send(row["user_id"], "Напоминание: " + row["text"])
                self.store.execute("UPDATE reminders SET sent=1 WHERE id=?", (row["id"],))
            except Exception as exc:
                LOG.warning("reminder_failed type=%s", type(exc).__name__)
                self.store.execute("UPDATE reminders SET attempts=attempts+1,available=? WHERE id=?",
                                   (time.time() + 30 * 2 ** row["attempts"], row["id"]))

    def worker(self):
        while not self.stop.is_set():
            job = self.store.next_job()
            if job:
                try:
                    self.process(job)
                except Exception as exc:
                    # Do not print request bodies, URLs, exception strings or tokens.
                    LOG.warning("job_failed attempts=%s type=%s", job["attempts"] + 1, type(exc).__name__)
                    self.store.execute("UPDATE jobs SET attempts=attempts+1,available=?,done=? WHERE id=?",
                                       (time.time() + min(300, 2 ** job["attempts"]),
                                        int(job["attempts"] >= 4), job["id"]))
            self.reminders()
            self.stop.wait(0.3)

    def polling(self):
        if self.api.call("GET", "/subscriptions").get("subscriptions"):
            raise ValueError("Remove webhook subscription before using polling")
        while not self.stop.is_set():
            try:
                marker = self.store.setting("marker")
                query = {"timeout": 25, "types": "message_created,message_callback,bot_started"}
                if marker is not None:
                    query["marker"] = marker
                batch = self.api.call("GET", "/updates", **query)
                for event in batch.get("updates", []):
                    self.store.enqueue(event)
                if batch.get("marker") is not None:
                    self.store.set("marker", batch["marker"])
            except Exception as exc:
                LOG.warning("poll_failed type=%s", type(exc).__name__)
                self.stop.wait(5)


def handler_for(bot):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, data):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.respond(200 if self.path == "/health" else 404,
                         {"status": "ok"} if self.path == "/health" else {"error": "not_found"})

        def do_POST(self):
            self.connection.settimeout(10)
            if self.path not in {"/webhook", "/internal/reminders"}:
                return self.respond(404, {"error": "not_found"})
            webhook = self.path == "/webhook"
            expected = os.getenv("WEBHOOK_SECRET" if webhook else "INTERNAL_API_KEY", "")
            actual = self.headers.get("X-Max-Bot-Api-Secret" if webhook else "Authorization", "")
            if not webhook:
                expected = "Bearer " + expected if expected else ""
            if not expected or not hmac.compare_digest(expected, actual):
                return self.respond(403, {"error": "forbidden"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 1_000_000:
                    return self.respond(413, {"error": "invalid_size"})
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("object required")
                if webhook:
                    bot.store.enqueue(data)  # Commit BEFORE acknowledging delivery.
                else:
                    bot.store.remind(data)
            except (ValueError, KeyError, TypeError):
                return self.respond(400, {"error": "invalid_payload"})
            self.respond(200, {"ok": True})
    return Handler


def main():
    load_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["polling", "webhook", "subscribe", "unsubscribe"])
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not os.getenv("MAX_BOT_TOKEN"):
        parser.error("Set MAX_BOT_TOKEN in .env")
    if args.mode in {"polling", "webhook"} and os.getenv("AGENT_MODE", "http") != "mock" and not os.getenv("AGENT_URL"):
        parser.error("Set AGENT_URL or AGENT_MODE=mock")
    http = HTTP()
    api = MaxAPI(http)
    if args.mode in {"subscribe", "unsubscribe"}:
        url = os.getenv("WEBHOOK_URL", "")
        if not url.startswith("https://") or urlsplit(url).port not in (None, 443):
            parser.error("Set HTTPS WEBHOOK_URL on port 443")
        if args.mode == "subscribe":
            secret = os.getenv("WEBHOOK_SECRET", "")
            if not re.fullmatch(r"[A-Za-z0-9_-]{5,256}", secret):
                parser.error("Set WEBHOOK_SECRET: 5..256 letters, digits, underscore or dash")
            api.call("POST", "/subscriptions", {"url": url, "secret": secret,
                     "update_types": ["message_created", "message_callback", "bot_started"]})
        else:
            api.call("DELETE", "/subscriptions", url=url)
        LOG.info("subscription_updated")
        return
    if args.mode == "webhook" and not os.getenv("WEBHOOK_SECRET"):
        parser.error("Set WEBHOOK_SECRET")
    store = Store(os.getenv("STATE_DB", str(ROOT / "state/bot.sqlite3")))
    bot = Bot(store, http, api)
    worker = threading.Thread(target=bot.worker, daemon=True)
    worker.start()
    try:
        if args.mode == "polling":
            bot.polling()
        else:
            server = ThreadingHTTPServer((os.getenv("HOST", "127.0.0.1"), int(os.getenv("PORT", "8080"))), handler_for(bot))
            LOG.info("webhook_server_started")
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop.set()
        worker.join(timeout=100)


if __name__ == "__main__":
    try:
        main()
    except (URLError, ssl.SSLError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, ssl.SSLCertVerificationError):
            print("Ошибка проверки TLS-сертификата. Для API MAX нужен доверенный сертификат "
                  "Минцифры. Скачайте официальный PEM-сертификат и укажите в .env "
                  "EXTRA_CA_FILE=russian_trusted_root_ca_pem.crt. Подробнее в README. "
                  "Проверка TLS остаётся включённой.")
        else:
            print("Ошибка подключения. Проверьте интернет, VPN/прокси и адрес сервиса. "
                  "Тип ошибки: " + type(reason).__name__)
        raise SystemExit(1)
