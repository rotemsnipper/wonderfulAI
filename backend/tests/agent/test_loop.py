from backend.agent import llm
from backend.agent.loop import ADVICE_LINE, CAP_PREFIX, NUMBER_CHECK_PREFIX, Agent
from backend.agent.llm import ModelReply, ToolCall
from backend.agent.session import InMemorySessionStore

RESULT = {
    "tool": "airport_profile", "inputs": {"code": "SFO"},
    "result": {"code": "SFO", "delay_rate_pct": 31.65, "excess_delayed_flights": 14821},
    "definitions": [], "warnings": [{"airport": "SFO", "type": "partial_data", "severity": "high", "message": "m"}],
    "data_quality": {"SFO": {"tier": "full", "confidence": "high", "reason": ""}}, "notes": [],
    "meta": {"airports": ["SFO"], "uses_proxy": True, "periods": {"t100_summary": "2025-08..2026-07"},
             "score_version": "0.1"},
}


def tool_reply(i=0, name="airport_profile"):
    return ModelReply(text="", tool_calls=[ToolCall(id=f"c{i}", name=name, args={"code": "SFO"})], stop_reason="tool_use",
                      input_tokens=10, output_tokens=2, model="fake")


def text_reply(text, stop="end_turn"):
    return ModelReply(text=text, stop_reason=stop, input_tokens=10, output_tokens=5, model="fake")


class FakeModel:
    """Replays scripted replies; records every request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, system, tool_specs=None):
        self.requests.append({"messages": [dict(m) for m in messages], "tools": tool_specs})
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_agent(model, cap=7, events=None):
    calls = []

    def call_tool(name, args):
        calls.append((name, args))
        return RESULT

    agent = Agent(system="system prompt", tool_specs=[{"name": "airport_profile"}], call_tool=call_tool,
                  complete=model, round_cap=cap,
                  on_event=(lambda k, d: events.append(k)) if events is not None else (lambda k, d: None))
    return agent, calls


def test_tool_use_then_answer_is_saved_with_footer_and_warnings():
    model = FakeModel(tool_reply(), text_reply("SFO has about 14,821 excess delayed flights (SFO)."))
    events = []
    agent, calls = make_agent(model, events=events)
    store = InMemorySessionStore()
    out = agent.run_turn(store, "u", "c", "What is SFO's unmet demand?")
    assert calls == [("airport_profile", {"code": "SFO"})]
    assert out["saved"] and out["check_outcome"]["status"] == "passed"
    assert out["footer"]["confidence"] == "low"  # partial_data warning on a mentioned airport
    assert out["warnings"][0]["type"] == "partial_data"
    assert [m["role"] for m in out["model_messages"]] == ["user", "assistant", "tool", "assistant"]
    assert events == ["tool_start", "tool_end", "done"]
    assert len(store.load("u", "c")) == 1
    assert out["tokens"] == {"input": 20, "output": 7}


def test_rewrite_path_fixes_invented_number():
    model = FakeModel(tool_reply(), text_reply("SFO delay rate is 40.2%."), text_reply("SFO delay rate is 31.7%."))
    agent, _ = make_agent(model)
    out = agent.run_turn(InMemorySessionStore(), "u", "c", "SFO delays?")
    assert out["check_outcome"]["status"] == "rewritten" and out["check_outcome"]["first_unverified"] == ["40.2%"]
    assert out["display_text"] == "SFO delay rate is 31.7%."
    rewrite_request = model.requests[-1]["messages"][-1]
    assert rewrite_request["role"] == "user" and rewrite_request["content"].startswith(NUMBER_CHECK_PREFIX)
    assert model.requests[-1]["tools"] is None
    assert not any(NUMBER_CHECK_PREFIX in str(m.get("content")) for m in out["model_messages"])


def test_flagged_path_shows_answer_with_unverified_numbers():
    model = FakeModel(tool_reply(), text_reply("SFO delay rate is 40.2%."), text_reply("SFO delay rate is 40.2%."))
    agent, _ = make_agent(model)
    out = agent.run_turn(InMemorySessionStore(), "u", "c", "SFO delays?")
    assert out["check_outcome"]["status"] == "flagged" and out["check_outcome"]["unverified"] == ["40.2%"]
    assert "could not be matched to our data: 40.2%" in out["display_text"]


def test_cap_path_forces_answer_without_tools():
    model = FakeModel(*[tool_reply(i) for i in range(3)], text_reply("I could not finish; SFO excess delays are missing."))
    agent, calls = make_agent(model, cap=3)
    out = agent.run_turn(InMemorySessionStore(), "u", "c", "SFO?")
    assert len(calls) == 3
    assert out["check_outcome"]["capped"] is True and out["check_outcome"]["rounds"] == 4
    last = model.requests[-1]
    assert last["tools"] is None and last["messages"][-1]["content"].startswith(CAP_PREFIX)
    assert out["display_text"].startswith("I could not finish")


def test_cap_counts_only_the_current_turn_across_five_turns():
    store = InMemorySessionStore()
    for n in range(5):
        model = FakeModel(*[tool_reply(i) for i in range(2)], text_reply(f"Answer {n} about SFO."))
        agent, calls = make_agent(model, cap=3)
        out = agent.run_turn(store, "u", "c", f"Question {n}")
        assert out["check_outcome"]["capped"] is False, n
        assert len(calls) == 2
        assert model.requests[0]["tools"] is not None
    assert len(store.load("u", "c")) == 5


def test_rollback_on_model_error_saves_nothing_and_next_turn_is_valid():
    store = InMemorySessionStore()
    agent, _ = make_agent(FakeModel(text_reply("First answer.")))
    agent.run_turn(store, "u", "c", "first")
    agent, _ = make_agent(FakeModel(tool_reply(), llm.ModelError("boom")))
    out = agent.run_turn(store, "u", "c", "second")
    assert out["saved"] is False and out["check_outcome"]["status"] == "error"
    assert len(store.load("u", "c")) == 1
    model = FakeModel(text_reply("Third answer."))
    agent, _ = make_agent(model)
    agent.run_turn(store, "u", "c", "third")
    roles = [m["role"] for m in model.requests[0]["messages"]]
    assert roles == ["user", "assistant", "user"]  # the failed turn left no dangling tool call


def test_rate_limit_message_is_clear():
    agent, _ = make_agent(FakeModel(llm.RateLimitError("The model is rate limited right now; please try again in a minute.")))
    out = agent.run_turn(InMemorySessionStore(), "u", "c", "x")
    assert "rate limited" in out["display_text"] and out["saved"] is False


def test_advice_line_added_by_code_for_recommendations_with_data():
    model = FakeModel(tool_reply(), text_reply("SFO looks constrained."))
    agent, _ = make_agent(model)
    out = agent.run_turn(InMemorySessionStore(), "u", "c", "Should SFO expand?")
    assert out["display_text"].endswith(ADVICE_LINE)
    agent, _ = make_agent(FakeModel(text_reply("Which airport do you mean?")))
    assert ADVICE_LINE not in agent.run_turn(InMemorySessionStore(), "u", "c", "Should Portland expand?")["display_text"]


def test_follow_up_without_tools_reuses_earlier_data_after_resume():
    store = InMemorySessionStore()
    agent, _ = make_agent(FakeModel(tool_reply(), text_reply("SFO delay rate is 31.7%.")))
    agent.run_turn(store, "u", "c", "SFO delays?")
    agent, calls = make_agent(FakeModel(text_reply("As before, SFO has 14,821 excess delayed flights.")))
    out = agent.run_turn(store, "u", "c", "And the excess delays?")
    assert calls == [] and out["check_outcome"]["status"] == "passed"  # pool rebuilt from the stored turn
    assert out["footer"]["notes"] and "reused" in out["footer"]["notes"][0]
