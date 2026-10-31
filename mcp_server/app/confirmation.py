"""Подтверждение конкретной операции с устойчивым ключом повторов."""
import asyncio
from .memory import ConversationStore, MemoryStorageError

class ConfirmationError(ValueError):
    pass

async def save_confirmed_event(memory: ConversationStore, mcp_client, user_id: str, expected_key: str) -> dict:
    pending = (await asyncio.to_thread(memory.get_context, user_id))["pending_event"]
    if pending is None or pending["idempotency_key"] != expected_key:
        raise ConfirmationError("Предложение изменилось или истекло. Запросите его заново.")
    action = pending.get("action", "create")
    args = {"user_id": user_id, "idempotency_key": expected_key}
    if action == "create":
        name, flag = "create_event", "created"
        args.update({key: pending[key] for key in ("event_type", "name", "description", "datetime")})
    elif action == "delete":
        name, flag = "delete_event", "deleted"
        args["event_id"] = pending["event_id"]
    elif action == "reschedule":
        name, flag = "update_event_time", "updated"
        args.update(event_id=pending["event_id"], datetime=pending["datetime"])
    else:
        raise ConfirmationError("Неизвестная операция.")
    result = await mcp_client.call_tool(name, args)
    data = result.structured_content
    if result.is_error or not isinstance(data, dict) or data.get("error"):
        raise ConfirmationError("Операция не подтверждена. Повторите подтверждение.")
    if not isinstance(data.get("event"), dict) or type(data.get(flag)) is not bool:
        raise ConfirmationError("Некорректный ответ инструмента.")
    if action != "create" and data[flag] is not True:
        raise ConfirmationError("Изменение не подтверждено.")
    try:
        cleared = await asyncio.to_thread(memory.clear_pending_event, user_id, expected_key)
    except MemoryStorageError:
        cleared = False
    return {**data, "context_cleared": cleared}
