import asyncio
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock
from uuid import uuid4
from langchain_core.messages import AIMessage
from app.agent import CalendarAgent, Reply
from app.config import Settings
from app.confirmation import Confirmations
from tests.fakes import FakeMCP, MemoryHistory, ScriptedGigaChat

class Memory:
    def __init__(self): self.value=None
    def get_context(self,user): return {"pending_event":self.value}
    def clear_pending_event(self,user,key):
        if self.value and self.value["idempotency_key"]==key:
            self.value=None
            return True
        return False
    def set_pending_event(self,user,**fields):
        self.value={"description":"",**fields}
        return self.value

class ConfirmationTests(unittest.TestCase):
    def agent(self,script,mcp=None,memory=None):
        self.memory=memory or Memory()
        return CalendarAgent(llm=ScriptedGigaChat(script=script),mcp=mcp or FakeMCP(),history=MemoryHistory(),settings=Settings(),confirmations=Confirmations(self.memory))
    def reply(self,agent,text,mid="m",source="text"):
        return asyncio.run(agent.reply(user_id="42",message_id=mid,text=text,timezone_name="Europe/Moscow",source=source))
    def test_create_proposal_and_confirm_exact_fields(self):
        model=AIMessage(content="",tool_calls=[{"id":"c","name":"create_event","args":{"event_type":"meeting","name":"Врач","datetime":"2035-01-02T15:00:00+03:00"}}])
        mcp=FakeMCP({"create_event":{"event":{"id":"test"},"created":True}})
        agent=self.agent([model],mcp)
        proposal=self.reply(agent,"Создай встречу")
        self.assertTrue(proposal.confirmation_key)
        answer=self.reply(agent,"confirm:"+proposal.confirmation_key,"confirm")
        self.assertIn("Сохранено",answer)
        self.assertEqual(set(mcp.calls[0][1]),{"user_id","event_type","name","description","datetime","idempotency_key"})
        self.assertIsNone(self.memory.value)
    def test_stale_button_does_not_confirm_new_proposal(self):
        agent=self.agent([])
        self.memory.value={"idempotency_key":"new"}
        self.assertIn("устарела",self.reply(agent,"confirm:old"))
        self.assertIsNotNone(self.memory.value)
    def test_failed_delete_preserves_pending_and_does_not_claim_success(self):
        mcp=FakeMCP({"delete_event":{"error":{"message":"denied"}}})
        agent=self.agent([],mcp)
        self.memory.value={"action":"delete","idempotency_key":"pending","event_id":"id","name":"Врач","datetime":"2035-01-02T15:00:00+03:00"}
        answer=self.reply(agent,"да")
        self.assertNotIn("Удалено",answer)
        self.assertIsNotNone(self.memory.value)
        self.assertEqual(answer.confirmation_key,"pending")
    def test_voice_reschedule_week_uses_existing_date_not_today(self):
        eid=str(uuid4())
        model=AIMessage(content="",tool_calls=[{"id":"c","name":"update_event_time","args":{"event_id":eid,"event_type":"meeting","name":"Врач","datetime":"2040-01-01T15:00:00+03:00"}}])
        mcp=FakeMCP({"get_event_by_query":{"items":[{"id":eid,"event_type":"meeting","name":"Врач","event_at":"2035-01-02T12:00:00Z"}]}})
        agent=self.agent([model],mcp)
        self.reply(agent,"Перенеси врача на неделю",source="voice")
        self.assertEqual(self.memory.value["datetime"],"2035-01-09T15:00:00+03:00")
    def test_voice_delete_requires_confirm(self):
        eid=str(uuid4())
        model=AIMessage(content="",tool_calls=[{"id":"c","name":"delete_event","args":{"event_id":eid,"event_type":"meeting","name":"Врач","datetime":"2035-01-02T15:00:00+03:00"}}])
        mcp=FakeMCP({"get_event_by_query":{"items":[{"id":eid,"event_type":"meeting","name":"Врач","event_at":"2035-01-02T12:00:00Z"}]},"delete_event":{"deleted":True,"event":{"id":eid}}})
        agent=self.agent([model],mcp)
        proposal=self.reply(agent,"Удали врача",source="voice")
        self.assertNotIn("delete_event",[name for name,_ in mcp.calls])
        answer=self.reply(agent,"да",mid="yes",source="voice")
        self.assertIn("Удалено",answer)
        self.assertIsNone(self.memory.value)
    def test_same_proposal_retry_has_same_key(self):
        model=AIMessage(content="",tool_calls=[{"id":"c","name":"create_event","args":{"event_type":"task","name":"Test","datetime":"2035-01-02T15:00:00+03:00"}}])
        agent=self.agent([model,model])
        one=self.reply(agent,"Создай задачу",mid="same")
        two=self.reply(agent,"Создай задачу",mid="same")
        self.assertEqual(one.confirmation_key,two.confirmation_key)
    def test_new_history_configuration_is_valid(self):
        settings=Settings.from_env({"AGENT_HISTORY_LIMIT":"40","AGENT_HISTORY_TTL_SECONDS":"86400"})
        self.assertEqual((settings.history_limit,settings.history_ttl_seconds),(40,86400))
