"""Заглушки внешних вызовов. LLM-заглушка имитирует интерфейс GigaChat (bind_tools), но не отвечает сама."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class ScriptedGigaChat(BaseChatModel):
    """Возвращает заранее заданные ответы по очереди и запоминает, что ему передали."""

    script: list = []
    bound_tool_names: list = []
    calls: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted-gigachat-test"

    def bind_tools(self, tools, **kwargs: Any):
        self.bound_tool_names = [tool.name for tool in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.calls.append([m.content for m in messages])
        if not self.script:
            raise AssertionError("Скрипт ответов исчерпан")
        reply = self.script.pop(0)
        return ChatResult(generations=[ChatGeneration(message=reply if isinstance(reply, AIMessage) else AIMessage(content=reply))])


class FakeMCP:
    """Запоминает вызовы инструментов и возвращает заданные ответы."""

    def __init__(self, responses: dict | None = None, error: str | None = None):
        self.responses = responses or {}
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def call(self, name: str, arguments: dict) -> dict:
        from app.mcp_client import MCPError

        self.calls.append((name, dict(arguments)))
        if self.error:
            raise MCPError(self.error)
        return self.responses.get(name, {})


class MemoryHistory:
    """Замена ChatHistory без Redis: та же семантика, живёт в памяти процесса."""

    def __init__(self, limit: int = 10):
        self.limit = limit
        self.messages: dict[str, list[dict]] = {}
        self.replies: dict[str, str] = {}

    def get(self, user_id):
        return list(self.messages.get(user_id, []))

    def append(self, user_id, messages):
        items = self.messages.setdefault(user_id, [])
        for role, content in messages:
            items.append({"role": role, "content": content})
        del items[:-self.limit]

    def get_reply(self, key):
        return self.replies.get(key)

    def put_reply(self, key, reply):
        self.replies[key] = reply

    def ping(self):
        return True


class NoPending:
    async def propose(self, user_id, **payload):
        return {**payload, "idempotency_key": "test-proposal"}

    async def pending(self, user_id):
        return None
