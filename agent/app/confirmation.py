"""Server-side proposal and confirmation boundary, independent of model claims."""
import asyncio
from types import SimpleNamespace

try:
    from calendar_storage.memory import ConversationStore
    from calendar_storage.confirmation import save_confirmed_event
except ModuleNotFoundError:
    from mcp_server.app.memory import ConversationStore
    from mcp_server.app.confirmation import save_confirmed_event


class ClientAdapter:
    def __init__(self, mcp):
        self.mcp = mcp

    async def call_tool(self, name, arguments):
        result = await self.mcp.call(name, arguments)
        return SimpleNamespace(is_error=False, structured_content=result)


class Confirmations:
    def __init__(self, memory=None):
        self.memory = memory or ConversationStore()

    async def pending(self, user_id):
        return (await asyncio.to_thread(self.memory.get_context, user_id))["pending_event"]

    async def propose(self, user_id, **payload):
        return await asyncio.to_thread(self.memory.set_pending_event, user_id, **payload)

    async def confirm(self, mcp, user_id, pending):
        return await save_confirmed_event(self.memory, ClientAdapter(mcp), user_id, pending["idempotency_key"])
