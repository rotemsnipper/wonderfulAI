from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from backend.agent.session import InMemorySessionStore, Turn
from backend.tools import tools
from backend.tools.store import load_store
from backend.ui.app import SAMPLE_QUESTIONS
from backend.ui.chat_backend import NOT_HEARD_TEXT, ChatBackend

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(autouse=True)
def fixture_store():
    tools.configure(load_store(FIXTURE))
    yield
    tools._ctx = None


class StubAgent:
    """Saves a report turn per question, like the real loop, and reports one tool call."""

    def __init__(self, on_event, asked):
        self.on_event = on_event
        self.asked = asked

    def run_turn(self, store, user_id, conv_id, question):
        self.asked.append(question)
        self.on_event("tool_start", {"name": "rank_airports", "args": {"region": "new_england"}})
        report = {"kind": "ranking", "mode": "report", "subject": "ranking",
                  "sections": [{"id": "verdict", "title": "Verdict", "written_by": "model",
                                "markdown": f"Answer to: {question}"}],
                  "suggestions": ["Compare BOS and BDL."]}
        turn = Turn(question=question, model_messages=[], tool_trace=[{"tool": "rank_airports",
                                                                       "args": {"region": "new_england"}, "result": {}}],
                    check_outcome={"status": "passed", "unverified": [], "cut_off": False}, footer={}, warnings=[],
                    display_text="unused for report turns", report=report)
        store.append_turn(user_id, conv_id, turn)
        return {**turn.to_dict(), "saved": True}


def _script(backend):
    from backend.ui.app import main

    main(backend)


def make_app():
    asked = []
    backend = ChatBackend(InMemorySessionStore(), lambda on_event: StubAgent(on_event, asked))
    return AppTest.from_function(_script, args=(backend,), default_timeout=10), asked


def markdown_text(at):
    return [m.value for m in at.markdown]


def test_first_load_shows_samples_data_window_and_no_conversation():
    at, asked = make_app()
    at.run()

    assert not at.exception
    assert [at.sidebar.button(key=f"sample-{i}").label for i in range(4)] == SAMPLE_QUESTIONS
    assert "Data: 2025-08 to 2026-07" in [c.value for c in at.sidebar.caption]
    assert at.info and asked == []


def test_sample_question_button_asks_it_and_shows_the_report_sections():
    at, asked = make_app()
    at.run()

    at.sidebar.button(key="sample-0").click().run()

    assert not at.exception
    assert asked == [SAMPLE_QUESTIONS[0]]
    assert f"**Verdict**\n\nAnswer to: {SAMPLE_QUESTIONS[0]}" in markdown_text(at)
    assert at.button(key="suggest-0").label == "Compare BOS and BDL."
    assert not at.chat_input[0].disabled


def test_switching_conversations_shows_the_selected_history():
    at, _ = make_app()
    at.run()
    at.sidebar.button(key="sample-0").click().run()
    at.sidebar.button(key="sample-1").click().run()
    at.sidebar.button[0].click().run()  # New conversation
    at.sidebar.button(key="sample-2").click().run()

    at.sidebar.button(key="conv-conv-1").click().run()

    shown = markdown_text(at)
    assert SAMPLE_QUESTIONS[0] in shown and SAMPLE_QUESTIONS[1] in shown
    assert SAMPLE_QUESTIONS[2] not in shown


class FakeRecording:
    type = "audio/wav"

    def getvalue(self):
        return b"wav"


def _chat_submit_script(backend, value):
    import streamlit as st

    from backend.ui.app import _queue_chat

    st.session_state["typed"] = value
    _queue_chat(backend)


def submit_recording(transcriber):
    """AppTest cannot attach audio to st.chat_input, so the on_submit callback gets the value the widget would give."""
    backend = ChatBackend(InMemorySessionStore(), transcriber=transcriber)
    value = SimpleNamespace(text="", audio=FakeRecording())
    at = AppTest.from_function(_chat_submit_script, args=(backend, value), default_timeout=10)
    at.run()
    assert not at.exception
    return at


def test_recording_sent_from_the_chat_bar_is_transcribed_and_queued_as_a_spoken_question():
    at = submit_recording(lambda audio, mime_type, hint: "Compare LA and Santa Ana.")

    assert at.session_state["pending"] == "Compare LA and Santa Ana."
    assert at.session_state["pending_spoken"]


def test_failed_transcription_shows_the_message_and_asks_nothing():
    at = submit_recording(lambda audio, mime_type, hint: "")

    assert "pending" not in at.session_state
    assert at.session_state["voice_error"] == NOT_HEARD_TEXT
