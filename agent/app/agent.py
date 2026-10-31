"""Цикл диалога: история Redis → GigaChat с инструментами → MCP → ответ пользователю."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime as DateTime, timedelta
import re
from uuid import NAMESPACE_URL, uuid5
from pydantic import ValidationError
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.config import Settings
from app.history import ChatHistory
from app.mcp_client import CalendarMCP
from app.prompt import render_system_prompt, server_now
from app.tools import CalendarTools, build_tools

FALLBACK_REPLY = "Не удалось завершить запрос. Пожалуйста, повторите сообщение короче или точнее."

_YES = {"да", "подтверждаю", "создавай", "сохрани", "подтвердить", "ок", "окей", "yes", "👍", "точно", "давай", "конечно"}
_NO  = {"нет", "отмена", "не надо", "отменить", "стоп", "no", "👎", "не создавай", "не удаляй", "не переноси"}


def _fmt_dt(iso: str, zone) -> str:
    """Форматирует ISO 8601 в читаемую строку на языке пользователя."""
    try:
        dt = DateTime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(zone)
        MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
        DAYS   = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
        return f"{dt.day} {MONTHS[dt.month-1]}, {DAYS[dt.weekday()]}, {dt.strftime('%H:%M')}"
    except Exception:
        return iso


def _confirm_text(pending: dict, zone) -> str:
    """Читаемый текст предложения для показа пользователю."""
    action   = pending.get("action", "create")
    name     = pending.get("name", "?")
    dt_str   = _fmt_dt(pending.get("datetime", ""), zone)
    TYPE_MAP = {"task": "Задача", "meeting": "Встреча", "project": "Проект", "reminder": "Напоминание"}
    kind     = TYPE_MAP.get(pending.get("event_type", "task"), "Событие")

    if action == "delete":
        return f"Удалить событие?\n\n{kind}: {name}\nКогда: {dt_str}\n\nПодтвердите кнопкой ниже или ответьте «да» / «нет»."
    if action == "reschedule":
        return f"Перенести событие?\n\n{kind}: {name}\nНовое время: {dt_str}\n\nПодтвердите кнопкой ниже или ответьте «да» / «нет»."
    return f"Создать событие?\n\n{kind}: {name}\nКогда: {dt_str}\n\nПодтвердите кнопкой ниже или ответьте «да» / «нет»."


class Reply(str):
    def __new__(cls, text, confirmation_key=None):
        obj = super().__new__(cls, text)
        obj.confirmation_key = confirmation_key
        return obj


class CalendarAgent:
    def __init__(self, *, llm, mcp: CalendarMCP, history: ChatHistory, settings: Settings, clock=None, confirmations=None):
        self.llm = llm
        self.mcp = mcp
        self.history = history
        self.settings = settings
        self.clock = clock
        from app.confirmation import Confirmations
        self.confirmations = confirmations or Confirmations()

    async def reply(self, *, user_id: str, message_id: str, text: str, timezone_name: str, source: str = "text") -> str:
        zone = ZoneInfo(timezone_name)
        now = server_now(zone, clock=self.clock)
        user_text = f"[голос] {text}" if source == "voice" else text

        if self.confirmations is not None:
            pending = await self.confirmations.pending(user_id)
            normalized = text.strip().lower().rstrip(".!? ")
            expected = None
            if normalized.startswith(("confirm:", "cancel:")):
                verb, expected = normalized.split(":", 1)
                if not pending or expected != pending["idempotency_key"]:
                    return "Эта кнопка устарела. Используйте кнопки последнего предложения."
                normalized = "да" if verb == "confirm" else "нет"
            # Compatibility with callbacks sent by the previous bot version.
            if normalized in {"/да", "/нет"}:
                normalized = normalized[1:]
            if normalized in _YES:
                if pending is None:
                    return "Нет события, ожидающего подтверждения. Напишите, что нужно сделать."
                action = pending.get("action", "create")
                try:
                    result = await self.confirmations.confirm(self.mcp, user_id, pending)
                except Exception:
                    return Reply("Не удалось выполнить действие. Попробуйте подтвердить ещё раз.", pending["idempotency_key"])
                if not isinstance(result.get("event"), dict):
                    return Reply("Результат не подтверждён. Попробуйте ещё раз.", pending["idempotency_key"])
                name = pending["name"]
                if action == "delete":
                    answer = f"Удалено: «{name}»."
                elif action == "reschedule":
                    answer = f"Перенесено: «{name}».\n{_fmt_dt(pending['datetime'], zone)}"
                elif result.get("created") is False:
                    answer = f"Такое событие уже есть: «{name}».\n{_fmt_dt(pending['datetime'], zone)}"
                else:
                    answer = f"Сохранено: «{name}».\n{_fmt_dt(pending['datetime'], zone)}"
                await asyncio.to_thread(self.history.append, user_id, [("user", user_text), ("assistant", answer)])
                return answer
            if normalized in _NO and pending:
                await asyncio.to_thread(self.confirmations.memory.clear_pending_event, user_id, pending["idempotency_key"])
                answer = "Отменено. События не изменены."
                await asyncio.to_thread(self.history.append, user_id, [("user", user_text), ("assistant", answer)])
                return answer

        history = await asyncio.to_thread(self.history.get, user_id)
        messages: list[BaseMessage] = [SystemMessage(content=render_system_prompt(
            now=now, timezone_name=timezone_name, user_id=user_id))]
        for item in history:
            cls = HumanMessage if item["role"] == "user" else AIMessage
            messages.append(cls(content=item["content"]))
        messages.append(HumanMessage(content=user_text))

        tools = build_tools(CalendarTools(self.mcp, user_id=user_id, message_id=message_id, zone=zone))
        by_name = {tool.name: tool for tool in tools}
        model = self.llm.bind_tools(tools)

        answer = ""
        for _ in range(self.settings.max_tool_rounds):
            messages[0] = SystemMessage(content=render_system_prompt(
                now=server_now(zone, clock=self.clock), timezone_name=timezone_name, user_id=user_id))
            ai = await model.ainvoke(messages)
            calls = list(ai.tool_calls or [])
            if not calls:
                answer = str(ai.content or "").strip()
                break
            if len(calls) > 1:
                answer = "Обрабатываю по одному. Уточните первое действие и подтвердите его."
                break

            call = calls[0]
            call_name = call["name"]

            if call_name in {"create_event", "delete_event", "update_event_time"} and self.confirmations is not None:
                from app.tools import CreateEventInput, DeleteEventInput, UpdateEventTimeInput
                schema = {"create_event": CreateEventInput, "delete_event": DeleteEventInput,
                          "update_event_time": UpdateEventTimeInput}[call_name]
                try:
                    payload = schema.model_validate(call.get("args") or {}).model_dump()
                except ValidationError:
                    answer = "Уточните название события, дату и время. Для удаления или переноса сначала нужно найти событие."
                    break
                if call_name != "create_event":
                    # Labels/dates in a destructive confirmation come from the DB,
                    # not a model-generated description of an arbitrary UUID.
                    found = await self.mcp.call("get_event_by_query", {"user_id": user_id, "text": payload["name"]})
                    event = next((item for item in found.get("items", []) if str(item["id"]) == payload["event_id"]), None)
                    if event is None:
                        answer = "Не удалось найти выбранное событие. Уточните название."
                        break
                    payload.update(name=event["name"], event_type=event["event_type"])
                    if call_name == "delete_event":
                        payload.update(action="delete", datetime=event["event_at"])
                    else:
                        payload["action"] = "reschedule"
                        relative = re.search(r"на\s+(?:(\d+)\s+)?(недел\w*|день|дня|дней)\b", text.lower())
                        if relative:
                            days = int(relative.group(1) or 1) * (7 if relative.group(2).startswith("недел") else 1)
                            previous = DateTime.fromisoformat(event["event_at"].replace("Z", "+00:00")).astimezone(zone)
                            payload["datetime"] = (previous + timedelta(days=days)).isoformat(timespec="seconds")
                stable_key = str(uuid5(NAMESPACE_URL, json.dumps([user_id, message_id, payload], sort_keys=True, ensure_ascii=False)))
                pending = await self.confirmations.propose(user_id, **payload, idempotency_key=stable_key)
                answer = Reply(_confirm_text(pending, zone), pending["idempotency_key"])
                break

            # Обычные read-only инструменты (get_event, get_event_by_query)
            call_id = call.get("id") or f"call_{len(messages)}"
            messages.append(AIMessage(content="", tool_calls=[{**call, "id": call_id}]))
            tool = by_name.get(call_name)
            if tool is None:
                result = {"error": "Неизвестный инструмент."}
            else:
                try:
                    result = await tool.ainvoke(call.get("args") or {})
                except Exception:
                    result = {"error": "Некорректные аргументы инструмента."}
            messages.append(ToolMessage(content=json.dumps(result, ensure_ascii=False),
                                        tool_call_id=call_id, name=call_name))
        if not answer:
            answer = FALLBACK_REPLY

        await asyncio.to_thread(self.history.append, user_id, [("user", user_text), ("assistant", answer)])
        return answer
