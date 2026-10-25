"""Связка Redis → MCP для backend. Не распознаёт согласие и не реализует LLM."""

import asyncio

from app.memory import ConversationStore, MemoryStorageError


class ConfirmationError(ValueError):
    """Ожидаемое предложение отсутствует или изменилось."""


async def save_confirmed_event(memory: ConversationStore, mcp_client, user_id: str, expected_key: str) -> dict:
    """Backend вызывает только после явного согласия на конкретное предложение.

    Сообщения одного user_id backend должен обрабатывать последовательно.
    При MCP-ошибке pending остаётся для повтора с тем же ключом.
    """
    context = await asyncio.to_thread(memory.get_context, user_id)
    pending = context["pending_event"]
    if pending is None or pending["idempotency_key"] != expected_key:
        raise ConfirmationError("Предложение истекло или изменилось. Уточните детали и запросите подтверждение заново.")
    result = await mcp_client.call_tool("create_event", {"user_id": user_id, **pending})
    # Клиент по умолчанию поднимает исключение, но проверяем и режим raise_on_error=False.
    if result.is_error or not isinstance(result.structured_content, dict):
        raise ConfirmationError("MCP не подтвердил сохранение. Сохраните ключ для повтора.")
    data = result.structured_content
    if not isinstance(data.get("event"), dict) or type(data.get("created")) is not bool:
        raise ConfirmationError("Неожиданный ответ MCP. Сохраните ключ операции.")
    try:
        cleared = await asyncio.to_thread(memory.clear_pending_event, user_id, expected_key)
    except MemoryStorageError:
        # PostgreSQL уже подтвердил сохранение. Сбой очистки памяти не отменяет успех.
        cleared = False
    return {**data, "context_cleared": cleared}
