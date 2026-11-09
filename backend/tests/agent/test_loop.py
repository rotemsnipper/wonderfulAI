from pathlib import Path

import pytest

from backend.agent import llm
from backend.agent.llm import ModelReply, ToolCall
from backend.agent.loop import ADVICE_LINE, CAP_PREFIX, NUMBER_CHECK_PREFIX, Agent
from backend.agent.session import InMemorySessionStore
from backend.tools import tools
from backend.tools.store import load_store

RESULT = {
    "tool": "lookup", "inputs": {"code": "SFO"},
    "result": {"code": "SFO", "delay_rate_pct": 31.65, "excess_delayed_flights": 14821},
    "definitions": [], "warnings": [{"airport": "SFO", "type": "partial_data", "severity": "high", "message": "m"}],
    "data_quality": {"SFO": {"tier": "full", "confidence": "high", "reason": ""}}, "notes": [],
    "meta": {"airports": ["SFO"], "uses_proxy": True, "periods": {"t100_summary": "2025-08..2026-07"},
             "score_version": "0.1"},
}


def tool_reply(i=0, name="lookup"):
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

    agent = Agent(system="system prompt", tool_specs=[{"name": "lookup"}], call_tool=call_tool,
                  complete=model, round_cap=cap,
                  on_event=(lambda k, d: events.append(k)) if events is not None else (lambda k, d: None))
    return agent, calls


def test_tool_use_then_answer_is_saved_with_footer_and_warnings():
    model = FakeModel(tool_reply(), text_reply("SFO has about 14,821 excess delayed flights (SFO)."))
    events = []
    agent, calls = make_agent(model, events=events)
    store = InMemorySessionStore()
    out = agent.run_turn(store, "u", "c", "What is SFO's unmet demand?")
    assert calls == [("lookup", {"code": "SFO"})]
    assert out["saved"] and out["check_outcome"]["status"] == "passed"
    assert out["footer"]["confidence"] == "low"  # partial_data warning on a mentioned airport
    assert out["warnings"][0]["type"] == "partial_data"
    assert [m["role"] for m in out["model_messages"]] == ["user", "assistant", "tool", "assistant"]
    assert events == ["tool_start", "tool_end", "done"]
    assert len(store.load("u", "c")) == 1
    assert out["tokens"] == {"input": 20, "output": 7, "thinking": 0}


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


def test_follow_up_without_tools_reuses_earlier_data_after_resume():
    store = InMemorySessionStore()
    agent, _ = make_agent(FakeModel(tool_reply(), text_reply("SFO delay rate is 31.7%.")))
    agent.run_turn(store, "u", "c", "SFO delays?")
    agent, calls = make_agent(FakeModel(text_reply("As before, SFO has 14,821 excess delayed flights.")))
    out = agent.run_turn(store, "u", "c", "And the excess delays?")
    assert calls == [] and out["check_outcome"]["status"] == "passed"  # pool rebuilt from the stored turn
    assert out["footer"]["notes"] and "reused" in out["footer"]["notes"][0]
    assert "Figures reused" in out["display_text"] and out["report"] is None


# ---- reports, with real tool results from the fixture dataset ----

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"
REPORT_TEXT = "**Verdict**\nNRC is a cargo-heavy hub.\n\n**Why**\n- Cargo is 50.0% of departures."


@pytest.fixture
def fixture_tools():
    tools.configure(load_store(FIXTURE))
    yield
    tools._ctx = None


def profile_call(i=0, **args):
    return ModelReply(text="", tool_calls=[ToolCall(id=f"p{i}", name="airport_profile", args={"code": "NRC", **args})],
                      stop_reason="tool_use", model="fake")


def fixture_agent(*replies):
    return Agent(system="system prompt", tool_specs=[], call_tool=tools.call, complete=FakeModel(*replies))


def test_data_turn_is_shown_as_a_report_and_checks_only_the_model_text(fixture_tools):
    out = fixture_agent(profile_call(), text_reply(REPORT_TEXT)).run_turn(InMemorySessionStore(), "u", "c", "Should NRC expand?")
    assert out["report"]["kind"] == "profile" and out["report"]["mode"] == "report"
    assert out["display_text"].startswith("**The airports**")
    assert "**Verdict**\n\nNRC is a cargo-heavy hub." in out["display_text"]
    assert "Long-haul share and unmet demand" in out["display_text"] and ADVICE_LINE in out["display_text"]
    assert out["check_outcome"]["status"] == "passed"
    assert out["model_messages"][-1]["content"] == REPORT_TEXT


def test_follow_up_on_the_same_subject_is_short_after_a_resume(fixture_tools):
    store = InMemorySessionStore()
    fixture_agent(profile_call(), text_reply(REPORT_TEXT)).run_turn(store, "u", "c", "Profile NRC")
    later = fixture_agent(profile_call(1, long_haul_cutoff_mi=2000), text_reply("**Verdict**\nAt 2,000 miles it is 33.3%."))
    out = later.run_turn(store, "u", "c", "And at 2,000 miles?")
    assert out["report"]["mode"] == "follow_up"
    assert "Capacity evidence" not in out["display_text"] and "Confidence" in out["display_text"]


def test_refresh_runs_only_when_the_user_asks_to_update_the_data():
    for question, runs in (("Is there newer data?", False), ("Please update the data.", True),
                           ("No, do not update the data.", False), ("What's the latest data update?", False)):
        agent, calls = make_agent(FakeModel(tool_reply(name="refresh_data"), text_reply("Done.")))
        out = agent.run_turn(InMemorySessionStore(), "u", "c", question)
        assert bool(calls) is runs, question
        assert ("error" in out["tool_trace"][0]["result"]) is not runs


def test_reply_to_a_clarifying_question_is_reported_for_the_original_question(fixture_tools):
    store = InMemorySessionStore()
    fixture_agent(text_reply("Which airport do you mean?")).run_turn(store, "u", "c", "Should the cargo hub expand?")
    out = fixture_agent(profile_call(), text_reply(REPORT_TEXT)).run_turn(store, "u", "c", "NRC")
    assert out["report"]["investment"] is True and ADVICE_LINE in out["display_text"]


def test_plain_reply_has_no_report(fixture_tools):
    out = fixture_agent(text_reply("Which Portland do you mean?")).run_turn(InMemorySessionStore(), "u", "c", "Portland?")
    assert out["report"] is None and out["display_text"] == "Which Portland do you mean?"


def test_answer_stopped_by_the_token_limit_is_marked_cut_off():
    agent, _ = make_agent(FakeModel(tool_reply(), text_reply("SFO has about 14,821 excess", stop="max_tokens")))
    assert agent.run_turn(InMemorySessionStore(), "u", "c", "SFO?")["check_outcome"]["cut_off"] is True
    agent, _ = make_agent(FakeModel(tool_reply(), text_reply("SFO has about 14,821 excess delayed flights.")))
    assert agent.run_turn(InMemorySessionStore(), "u", "c", "SFO?")["check_outcome"]["cut_off"] is False


def test_number_given_for_the_wrong_airport_triggers_a_rewrite(fixture_tools):
    compare = ModelReply(text="", tool_calls=[ToolCall(id="k", name="compare_airports", args={"codes": ["LAA", "SAA"]})],
                         stop_reason="tool_use", model="fake")
    model = FakeModel(compare, text_reply("**Verdict**\nSAA runs 66,000 departures per usable runway (SAA)."),
                      text_reply("**Verdict**\nSAA runs 51,600 departures per usable runway (SAA)."))
    out = Agent(system="s", tool_specs=[], call_tool=tools.call, complete=model).run_turn(
        InMemorySessionStore(), "u", "c", "Compare LAA and SAA delays.")
    assert out["check_outcome"]["status"] == "rewritten" and out["check_outcome"]["first_unverified"] == ["66,000"]
    assert "not values of the airport named" in model.requests[-1]["messages"][-1]["content"]
