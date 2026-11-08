from pathlib import Path

from backend.agent import llm
from backend.agent.llm import ModelReply
from backend.agent.loop import MODEL_ERROR_TEXT, Agent
from backend.agent.session import InMemorySessionStore
from backend.tools import tools
from backend.tools.store import load_store
from backend.ui.chat_backend import (
    EMPTY_TEXT, NOT_HEARD_TEXT, SETUP_TEXT, SPOKEN_CHARS, SPOKEN_CLOSING, TITLE_CHARS, UNTITLED, USER_ID,
    VOICE_FAILED_TEXT, ChatBackend, spoken_text,
)

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


def test_recording_is_transcribed_with_the_airport_vocabulary_hint():
    heard = []

    def transcriber(audio, mime_type, hint):
        heard.append((audio, mime_type, hint))
        return " What is the unmet demand at SFO? "

    backend = ChatBackend(InMemorySessionStore(), transcriber=transcriber)
    assert backend.transcribe(b"wav", "audio/wav") == {"text": "What is the unmet demand at SFO?"}
    assert heard[0][:2] == (b"wav", "audio/wav") and "Santa Ana" in heard[0][2]


def test_failed_or_empty_transcription_returns_a_message_and_no_question():
    def failing(audio, mime_type, hint):
        raise llm.ModelError("model call failed with HTTP 500")

    assert backend_for(failing).transcribe(b"wav", "audio/wav") == {"error": "ModelError", "display_text": VOICE_FAILED_TEXT}
    assert backend_for(lambda a, m, h: "  ").transcribe(b"wav", "audio/wav")["display_text"] == NOT_HEARD_TEXT


def backend_for(transcriber):
    return ChatBackend(InMemorySessionStore(), transcriber=transcriber)


def test_spoken_report_reads_the_verdict_without_markdown_then_points_to_the_screen():
    verdict = ("**BOS** leads the region.\n\n| Airport | Score |\n|---|---|\n| BOS | 71 |\n\n"
               "- Seats grew *-0.7%* at `PWM`.")
    turn = {"display_text": "unused", "report": {"sections": [
        {"id": "details", "title": "Details", "written_by": "code", "markdown": "Not read."},
        {"id": "verdict", "title": "Verdict", "written_by": "model", "markdown": verdict}]}}

    assert spoken_text(turn) == f"BOS leads the region. Seats grew -0.7% at PWM. {SPOKEN_CLOSING}"


def test_spoken_plain_answer_stops_at_the_last_sentence_that_fits():
    sentence = "Anchorage carries a large share of cargo flights. "
    spoken = spoken_text({"display_text": sentence * 20, "report": None})

    assert len(spoken) <= SPOKEN_CHARS and spoken.endswith("flights.")
    assert len(spoken) > SPOKEN_CHARS - len(sentence)
