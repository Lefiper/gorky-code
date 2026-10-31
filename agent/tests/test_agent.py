import asyncio
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage

from app.agent import FALLBACK_REPLY, CalendarAgent
from app.config import Settings
from app.prompt import render_system_prompt, server_now
from app.tools import CalendarTools, build_tools
from tests.fakes import FakeMCP, MemoryHistory, ScriptedGigaChat, NoPending

MOSCOW = ZoneInfo("Europe/Moscow")
FIXED_NOW = datetime(2026, 10, 29, 21, 30, 15, 123456, tzinfo=MOSCOW)  # четверг


def tool_call(name, args, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def make_agent(script, mcp=None, history=None):
    llm = ScriptedGigaChat(script=list(script))
    mcp = mcp or FakeMCP()
    history = history or MemoryHistory()
    agent = CalendarAgent(llm=llm, mcp=mcp, history=history, settings=Settings(max_tool_rounds=3),
                          clock=lambda: FIXED_NOW, confirmations=NoPending())
    return agent, llm, mcp, history


def run(coro):
    return asyncio.run(coro)


class PromptTests(unittest.TestCase):
    def test_placeholders_are_filled_with_server_values(self):
        text = render_system_prompt(now=FIXED_NOW, timezone_name="Europe/Moscow", user_id="42",
                                    template="{{now}} {{weekday}} {{timezone}} {{user_id}} {{event_types}}")
        self.assertEqual(text, "2026-10-29T21:30:15+03:00 четверг Europe/Moscow 42 task, reminder, meeting, project")

    def test_server_now_is_second_precision_in_user_zone(self):
        now = server_now(ZoneInfo("UTC"), clock=lambda: FIXED_NOW)
        self.assertEqual(now.isoformat(), "2026-10-29T18:30:15+00:00")

    def test_real_prompt_file_has_no_unfilled_required_placeholders_after_render(self):
        text = render_system_prompt(now=FIXED_NOW, timezone_name="Europe/Moscow", user_id="42")
        self.assertNotIn("{{", text)
        self.assertNotIn("`", text)


class ToolTests(unittest.TestCase):
    def test_user_id_is_injected_and_model_cannot_override_it(self):
        mcp = FakeMCP({"create_event": {"event": {}, "created": True}})
        box = CalendarTools(mcp, user_id="trusted", message_id="m1", zone=MOSCOW)
        tools = {t.name: t for t in build_tools(box)}
        self.assertNotIn("user_id", tools["create_event"].args)
        run(tools["create_event"].ainvoke({"event_type": "meeting", "name": "Встреча",
                                            "datetime": "2026-10-30T15:00:00+03:00", "user_id": "evil"}))
        name, args = mcp.calls[0]
        self.assertEqual(name, "create_event")
        self.assertEqual(args["user_id"], "trusted")
        self.assertEqual(args["idempotency_key"], "m1:create:1")

    def test_create_idempotency_key_is_stable_per_message_and_counter(self):
        mcp = FakeMCP({"create_event": {"created": True}})
        box = CalendarTools(mcp, user_id="u", message_id="m7", zone=MOSCOW)
        run(box.create_event("task", "A", "2026-10-30T10:00:00+03:00"))
        run(box.create_event("task", "B", "2026-10-30T11:00:00+03:00"))
        self.assertEqual([args["idempotency_key"] for _, args in mcp.calls], ["m7:create:1", "m7:create:2"])

    def test_invalid_event_type_is_rejected_before_mcp(self):
        mcp = FakeMCP()
        tools = {t.name: t for t in build_tools(CalendarTools(mcp, user_id="u", message_id="m", zone=MOSCOW))}
        with self.assertRaises(Exception):
            run(tools["create_event"].ainvoke({"event_type": "party", "name": "x", "datetime": "2026-10-30T10:00:00+03:00"}))
        self.assertEqual(mcp.calls, [])

    def test_search_results_get_local_time_and_weekday(self):
        mcp = FakeMCP({"get_event": {"items": [{"event_at": "2026-10-30T12:00:00Z", "name": "Встреча"}],
                                      "has_more": False}})
        box = CalendarTools(mcp, user_id="u", message_id="m", zone=MOSCOW)
        data = run(box.get_event("2026-10-30T00:00:00+03:00", "2026-10-31T00:00:00+03:00"))
        item = data["items"][0]
        self.assertEqual(item["local_event_at"], "2026-10-30T15:00:00+03:00")
        self.assertEqual(item["local_weekday"], "пятница")

    def test_mcp_error_becomes_tool_result_not_success(self):
        box = CalendarTools(FakeMCP(error="VALIDATION_ERROR: плохо"), user_id="u", message_id="m", zone=MOSCOW)
        self.assertEqual(run(box.get_event_by_query("врач")), {"error": "VALIDATION_ERROR: плохо"})


class AgentLoopTests(unittest.TestCase):
    def test_small_talk_without_tools_is_saved_to_context(self):
        agent, llm, mcp, history = make_agent(["Здравствуйте! Чем могу помочь?"])
        reply = run(agent.reply(user_id="42", message_id="m1", text="привет", timezone_name="Europe/Moscow"))
        self.assertEqual(reply, "Здравствуйте! Чем могу помочь?")
        self.assertEqual(mcp.calls, [])
        self.assertEqual(sorted(llm.bound_tool_names), ["create_event", "delete_event", "get_event", "get_event_by_query", "update_event_time"])
        self.assertEqual([m["role"] for m in history.get("42")], ["user", "assistant"])

    def test_create_flow_calls_mcp_with_server_user_id(self):
        script = [tool_call("create_event", {"event_type": "meeting", "name": "Встреча",
                                              "datetime": "2026-10-30T15:00:00+03:00"}),
                  "Записал встречу в пятницу, 30 октября, в 15:00."]
        mcp = FakeMCP({"create_event": {"event": {"id": "x"}, "created": True}})
        agent, llm, _, history = make_agent(script, mcp=mcp)
        reply = run(agent.reply(user_id="42", message_id="m2", text="создай встречу завтра в 15:00",
                                timezone_name="Europe/Moscow"))
        self.assertIn("15:00", reply)
        self.assertEqual(mcp.calls, [])
        self.assertIn("Подтвердите", reply)
        system_prompt = llm.calls[0][0]
        self.assertIn("2026-10-29T21:30:15+03:00", system_prompt)
        self.assertIn("четверг", system_prompt)

    def test_voice_source_is_marked_for_the_model(self):
        agent, llm, _, history = make_agent(["Понял."])
        run(agent.reply(user_id="42", message_id="m3", text="в три", timezone_name="Europe/Moscow", source="voice"))
        self.assertEqual(llm.calls[0][-1], "[голос] в три")
        self.assertEqual(history.get("42")[0]["content"], "[голос] в три")

    def test_history_is_passed_back_to_model(self):
        history = MemoryHistory()
        history.append("42", [("user", "Встреча с Иваном"), ("assistant", "На какое время?")])
        agent, llm, _, _ = make_agent(["Записать на 15:00?"], history=history)
        run(agent.reply(user_id="42", message_id="m4", text="в три", timezone_name="Europe/Moscow"))
        self.assertIn("Встреча с Иваном", llm.calls[0])
        self.assertIn("На какое время?", llm.calls[0])

    def test_endless_tool_calls_stop_with_fallback(self):
        script = [tool_call("get_event", {"start_time": "2026-10-30T00:00:00+03:00",
                                          "end_time": "2026-10-31T00:00:00+03:00"}, call_id=f"c{i}")
                  for i in range(3)]
        agent, _, mcp, _ = make_agent(script)
        reply = run(agent.reply(user_id="42", message_id="m5", text="что завтра", timezone_name="Europe/Moscow"))
        self.assertEqual(reply, FALLBACK_REPLY)
        self.assertEqual(len(mcp.calls), 3)

    def test_multiple_creation_calls_are_reported_as_one_at_a_time(self):
        ai = AIMessage(content="", tool_calls=[{"id": str(i), "name": "create_event", "args": {
            "event_type": "meeting", "name": str(i), "datetime": "2030-01-02T15:00:00+03:00"}} for i in range(3)])
        agent, _, mcp, _ = make_agent([ai])
        reply = run(agent.reply(user_id="42", message_id="multi", text="создай три встречи", timezone_name="Europe/Moscow"))
        self.assertIn("по одному", reply)
        self.assertEqual(mcp.calls, [])

    def test_unknown_tool_is_reported_to_model(self):
        script = [tool_call("unknown_event", {"id": "1"}), "Не могу удалить события."]
        agent, llm, mcp, _ = make_agent(script)
        reply = run(agent.reply(user_id="42", message_id="m6", text="удали", timezone_name="Europe/Moscow"))
        self.assertEqual(reply, "Не могу удалить события.")
        self.assertEqual(mcp.calls, [])
        self.assertIn(json.dumps({"error": "Неизвестный инструмент."}, ensure_ascii=False), llm.calls[1])

    def test_mcp_failure_is_visible_and_not_hidden_as_success(self):
        script = [tool_call("get_event_by_query", {"text": "Звонок"}),
                  "Не удалось сохранить задачу, попробуйте ещё раз."]
        agent, llm, _, _ = make_agent(script, mcp=FakeMCP(error="STORAGE_ERROR: повторите"))
        reply = run(agent.reply(user_id="42", message_id="m7", text="напомни позвонить", timezone_name="Europe/Moscow"))
        self.assertIn("Не удалось", reply)
        self.assertIn("STORAGE_ERROR: повторите", llm.calls[1][-1])


if __name__ == "__main__":
    unittest.main()
