from pathlib import Path

from backend.agent import llm
from backend.agent.llm import ModelReply
from backend.agent.loop import MODEL_ERROR_TEXT, Agent
from backend.agent.session import InMemorySessionStore
from backend.tools import tools
from backend.tools.store import load_store
from backend.ui.chat_backend import EMPTY_TEXT, SETUP_TEXT, TITLE_CHARS, UNTITLED, USER_ID, ChatBackend

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


class FakeModel:
    """Replays scripted replies (or raises scripted errors); records every request."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, system, tool_specs=None):
        self.requests.append([dict(m) for m in messages])
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def text_reply(text):
    return ModelReply(text=text, stop_reason="end_turn", input_tokens=10, output_tokens=5, model="fake")


def make_backend(model):
    store = InMemorySessionStore()

    def make_agent(on_event):
        return Agent(system="system prompt", tool_specs=[], call_tool=lambda name, args: {}, complete=model,
                     on_event=on_event)

    return ChatBackend(store, make_agent), store


def test_conversations_are_listed_newest_first_with_first_saved_question_as_title():
    backend, _ = make_backend(FakeModel(text_reply("Hello."), text_reply("Sure.")))
    first = backend.new_conversation()
    second = backend.new_conversation()
    long_question = "Which New England airport has the most capacity need right now?"
    backend.ask(first, long_question)
    backend.ask(first, "and at long range?")

    assert backend.conversations() == [
        {"id": second, "title": UNTITLED, "turns": 0},
        {"id": first, "title": long_question[:TITLE_CHARS], "turns": 2},
    ]


def test_follow_up_is_sent_with_the_earlier_turn():
    model = FakeModel(text_reply("Boston is in New England."), text_reply("It is in Massachusetts."))
    backend, store = make_backend(model)
    conv = backend.new_conversation()

    first = backend.ask(conv, "  Where is Boston?  ")
    backend.ask(conv, "Which state?")

    assert first["saved"] is True and first["display_text"] == "Boston is in New England."
    assert [t.question for t in store.load(USER_ID, conv)] == ["Where is Boston?", "Which state?"]
    assert [m["content"] for m in model.requests[1]] == ["Where is Boston?", "Boston is in New England.",
                                                         "Which state?"]


def test_reopened_conversation_shows_exactly_the_saved_turns():
    backend, store = make_backend(FakeModel(text_reply("Boston is in New England.")))
    conv = backend.new_conversation()
    backend.new_conversation()
    backend.ask(conv, "Where is Boston?")

    assert backend.history(conv) == [t.to_dict() for t in store.load(USER_ID, conv)]


def test_empty_question_is_rejected_without_calling_the_model():
    model = FakeModel()
    backend, _ = make_backend(model)
    conv = backend.new_conversation()

    result = backend.ask(conv, "   ")

    assert result["error"] == "empty_question" and result["saved"] is False
    assert result["display_text"] == EMPTY_TEXT
    assert model.requests == []


def test_model_error_returns_the_loop_message_and_saves_nothing():
    backend, store = make_backend(FakeModel(llm.ModelError("boom")))
    conv = backend.new_conversation()

    result = backend.ask(conv, "Where is Boston?")

    assert result["saved"] is False and result["display_text"] == MODEL_ERROR_TEXT
    assert store.load(USER_ID, conv) == []


def test_missing_api_key_returns_setup_message_without_the_error_text():
    backend, _ = make_backend(FakeModel(llm.ConfigError("GEMINI_API_KEY is not set in the environment")))
    conv = backend.new_conversation()

    result = backend.ask(conv, "Where is Boston?")

    assert result["error"] == "ConfigError" and result["saved"] is False
    assert result["display_text"] == SETUP_TEXT and "GEMINI_API_KEY" in SETUP_TEXT


def test_on_event_callback_reaches_the_agent():
    backend, _ = make_backend(FakeModel(text_reply("Boston is in New England.")))
    conv = backend.new_conversation()
    events = []

    backend.ask(conv, "Where is Boston?", on_event=lambda kind, data: events.append(kind))

    assert events == ["done"]


def test_data_window_reads_the_tool_store():
    tools.configure(load_store(FIXTURE))
    try:
        assert ChatBackend.data_window() == "2025-08 to 2026-07"
    finally:
        tools._ctx = None
