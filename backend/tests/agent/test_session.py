import pytest

from backend.agent.session import InMemorySessionStore, Turn, history_messages, pool_from_trace, rebuild_pool

TRACE = [
    {"tool": "compare_airports", "args": {"codes": ["LAX", "SNA"], "cutoff_mi": 3000},
     "result": {"result": {"LAX": {"delay_rate_pct": 19.66, "load_factor": 0.822}, "SNA": {"display": "5.5 million"}}}},
]


def make_turn(q="Compare LAX and SNA", trace=TRACE):
    return Turn(
        question=q,
        model_messages=[{"role": "user", "content": q}, {"role": "assistant", "content": "LAX 19.7%"}],
        tool_trace=trace, check_outcome={"status": "passed", "unverified": []}, footer={"confidence": "high"},
        warnings=[], display_text="LAX 19.7%", tokens={"input": 100, "output": 20},
        timings={"total_ms": 900}, model="gemini-test",
    )


def test_saved_turn_reloads_identically():
    store = InMemorySessionStore()
    turn = make_turn()
    store.append_turn("u1", "c1", turn)
    assert store.load("u1", "c1") == [turn]


def test_loaded_turns_are_independent_copies():
    store = InMemorySessionStore()
    store.append_turn("u1", "c1", make_turn())
    store.load("u1", "c1")[0].model_messages.append({"role": "user", "content": "tampered"})
    assert len(store.load("u1", "c1")[0].model_messages) == 2


def test_conversations_and_users_are_isolated():
    store = InMemorySessionStore()
    store.append_turn("u1", "c1", make_turn("a"))
    store.append_turn("u2", "c1", make_turn("b"))
    assert [t.question for t in store.load("u1", "c1")] == ["a"]
    assert store.load("u1", "other") == []


def test_partial_turn_is_never_visible():
    store = InMemorySessionStore()
    store.append_turn("u1", "c1", make_turn())
    bad = make_turn(trace=[{"tool": "x", "args": {}, "result": {"unserializable": object()}}])
    with pytest.raises(TypeError):
        store.append_turn("u1", "c1", bad)
    assert len(store.load("u1", "c1")) == 1


def test_pool_rebuild_matches_live_pool():
    store = InMemorySessionStore()
    second = [{"tool": "airport_profile", "args": {"code": "SFO"}, "result": {"result": {"seat_gap": 0.0, "excess": 14821.2}}}]
    store.append_turn("u1", "c1", make_turn())
    store.append_turn("u1", "c1", make_turn("SFO?", second))
    live = pool_from_trace(TRACE) | pool_from_trace(second)
    assert rebuild_pool(store.load("u1", "c1")) == live
    assert {19.66, 5.5e6, 3000.0, 14821.2} <= live
    assert any(abs(x - 82.2) < 1e-9 for x in live)


def test_history_messages_concatenates_turns_in_order():
    turns = [make_turn("first"), make_turn("second")]
    assert [m["content"] for m in history_messages(turns) if m["role"] == "user"] == ["first", "second"]


def test_turn_round_trips_through_dict():
    t = make_turn()
    assert Turn.from_dict(t.to_dict()) == t
