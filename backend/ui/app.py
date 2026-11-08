"""Local chat UI. Run from the project root: uv run --env-file .env streamlit run backend/ui/app.py

Drawing only; the logic is in chat_backend. A question is queued by a widget callback, the next run draws the page
with every input disabled and then runs the turn, and a final rerun enables the inputs again. So a second click or
a refresh can never send the same question twice or interrupt a running turn.
"""
import json
import sys
from pathlib import Path

# `streamlit run` puts only this file's folder on sys.path; the project is not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from backend.agent.session import InMemorySessionStore  # noqa: E402
from backend.ui.chat_backend import ChatBackend, spoken_text  # noqa: E402

SAMPLE_QUESTIONS = [
    "Which airports in New England are strong candidates for terminal expansion?",
    "Compare LA and Santa Ana airport congestion levels.",
    "What is the percentage of long-haul flights out of Anchorage airport?",
    "What is the unmet flight demand in SFO airport and why?",
]
SCOPE_NOTE = "The score ranks capacity need, a proxy for profit, not a return estimate."
DEMO_NOTE = "Local demo with a single user. Conversations last only while the server runs."
CHECK_COLORS = {"passed": "green", "rewritten": "blue", "flagged": "red"}
SPEECH_JS = (Path(__file__).parent / "speech.js").read_text(encoding="utf-8")


@st.cache_resource
def get_backend() -> ChatBackend:
    return ChatBackend(InMemorySessionStore())


def _say(text: str, speaking: tuple | None = None) -> None:
    """Queue one call to the page's speech layer for the next run: read `text` aloud, or stop when it is empty."""
    st.session_state["speech"] = text
    st.session_state["speaking"] = speaking


def _queue(backend: ChatBackend, question: str, spoken: bool = False) -> None:
    if st.session_state.get("selected") is None:
        st.session_state["selected"] = backend.new_conversation()
    st.session_state["pending"] = question
    st.session_state["pending_spoken"] = spoken
    st.session_state["notice"] = None
    st.session_state["voice_error"] = None
    if st.session_state.get("speaking"):
        _say("")


def _queue_chat(backend: ChatBackend) -> None:
    """Ask the typed text; a recording sent with no text is transcribed first and then asked the same way."""
    value = st.session_state.get("typed")
    if value is None:
        return
    if value.text.strip() or value.audio is None:
        _queue(backend, value.text)
        return
    result = backend.transcribe(value.audio.getvalue(), value.audio.type or "audio/wav")
    if "text" in result:
        _queue(backend, result["text"], spoken=True)
    else:
        st.session_state["voice_error"] = result["display_text"]


def _toggle_listen(key: tuple, text: str) -> None:
    if st.session_state.get("speaking") == key:
        _say("")
    else:
        _say(text, key)


def _load_speech() -> None:
    """Put speech.js into the app page once; a changed file replaces the old copy. Script frames are rebuilt
    on every rerun, so speech started inside one would be cut off."""
    st.iframe("<script>const w = window.parent, v = " + json.dumps(str(hash(SPEECH_JS))) + ";"
              "if (w.__speechVersion !== v) { w.__speechVersion = v; const s = w.document.createElement('script');"
              "s.textContent = " + json.dumps(SPEECH_JS).replace("</", "<\\/") + ";"
              "w.document.head.appendChild(s); }</script>", height="content")


def _speech_call() -> None:
    """Send the queued speech call once; the token makes a repeated call a new frame, so it runs again."""
    text = st.session_state["speech"]
    if text is None:
        return
    st.session_state["speech"] = None
    st.session_state["speech_n"] += 1
    call = "S.speak(" + json.dumps(text).replace("</", "<\\/") + ")" if text else "S.stop()"
    st.iframe(f"<script>/* {st.session_state['speech_n']} */ const S = window.parent.__speech; "
              f"if (S) {call};</script>", height="content")


def _select(conv_id: str | None) -> None:
    st.session_state["selected"] = conv_id
    st.session_state["notice"] = None


def _new(backend: ChatBackend) -> None:
    _select(backend.new_conversation())


def _sidebar(backend: ChatBackend, busy: bool) -> None:
    with st.sidebar:
        st.button("New conversation", on_click=_new, args=(backend,), disabled=busy, width="stretch")
        st.subheader("Conversations")
        for conv in backend.conversations():
            selected = conv["id"] == st.session_state.get("selected")
            st.button(conv["title"], key=f"conv-{conv['id']}", on_click=_select, args=(conv["id"],), disabled=busy,
                      type="primary" if selected else "secondary", width="stretch")
        st.subheader("Sample questions")
        for i, q in enumerate(SAMPLE_QUESTIONS):
            st.button(q, key=f"sample-{i}", on_click=_queue, args=(backend, q), disabled=busy,
                      width="stretch")
        st.caption(f"Data: {backend.data_window()}")
        st.caption(SCOPE_NOTE)


def _check_badges(outcome: dict) -> None:
    status = outcome.get("status", "")
    if status in CHECK_COLORS:
        label = f"Check: {status}"
        if status == "flagged" and outcome.get("unverified"):
            label += f" (unverified: {', '.join(outcome['unverified'])})"
        st.badge(label, color=CHECK_COLORS[status])
    if outcome.get("cut_off"):
        st.badge("cut off at the token limit", color="orange")


def _answer(backend: ChatBackend, turn: dict, key: tuple, suggestions: bool, busy: bool) -> None:
    report = turn.get("report")
    if report:
        for s in report["sections"]:
            st.markdown(f"**{s['title']}**\n\n{s['markdown']}")
    else:
        st.markdown(turn["display_text"])
    if turn.get("tool_trace"):
        with st.expander("Tools used"):
            for call in turn["tool_trace"]:
                st.code(f"{call['tool']}({json.dumps(call['args'])})", language=None)
    _check_badges(turn.get("check_outcome") or {})
    reading = st.session_state["speaking"] == key
    st.button("Stop" if reading else "Listen", key=f"listen-{key[1]}", on_click=_toggle_listen,
              args=(key, spoken_text(turn)), disabled=busy, type="tertiary",
              icon=":material/stop_circle:" if reading else ":material/volume_up:")
    if suggestions and report and report.get("suggestions"):
        st.caption("You could ask next")
        for i, q in enumerate(report["suggestions"]):
            st.button(q, key=f"suggest-{i}", on_click=_queue, args=(backend, q), disabled=busy)


def _run_pending(backend: ChatBackend, conv_id: str, question: str) -> None:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        status = st.status("Working…")

        def on_event(kind: str, data: dict) -> None:
            if kind == "tool_start" and data["name"] == "refresh_data":
                status.update(label="Downloading and rebuilding the data (about two minutes)…")
            elif kind == "tool_start":
                status.update(label=f"Calling {data['name']}…")
            elif kind == "rewrite":
                status.update(label="Checking numbers…")

        result = backend.ask(conv_id, question, on_event=on_event)
        status.update(label="Done", state="complete")
    if st.session_state["pending_spoken"]:
        # A spoken question gets a spoken answer; the next run sends the call.
        _say(spoken_text(result), (conv_id, len(backend.history(conv_id)) - 1) if result.get("saved") else None)
    st.session_state["pending"] = None
    st.session_state["pending_spoken"] = False
    st.session_state["notice"] = None if result.get("saved") else {"conv": conv_id, "question": question,
                                                                    "text": result["display_text"]}
    st.rerun()


def main(backend: ChatBackend) -> None:
    st.session_state.setdefault("selected", None)
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("notice", None)
    st.session_state.setdefault("pending_spoken", False)
    st.session_state.setdefault("voice_error", None)
    st.session_state.setdefault("speaking", None)
    st.session_state.setdefault("speech", None)
    st.session_state.setdefault("speech_n", 0)
    busy = st.session_state["pending"] is not None
    conv_id = st.session_state["selected"]

    _load_speech()
    st.title("Airport investment agent")
    st.caption(DEMO_NOTE)
    _sidebar(backend, busy)

    turns = backend.history(conv_id) if conv_id else []
    if not turns and not busy:
        st.info("Ask a question below or pick a sample question in the sidebar.")
    for i, turn in enumerate(turns):
        with st.chat_message("user"):
            st.markdown(turn["question"])
        with st.chat_message("assistant"):
            _answer(backend, turn, (conv_id, i), suggestions=i == len(turns) - 1, busy=busy)
    notice = st.session_state["notice"]
    if notice and notice["conv"] == conv_id:
        with st.chat_message("user"):
            st.markdown(notice["question"])
        with st.chat_message("assistant"):
            st.warning(notice["text"])

    if st.session_state["voice_error"]:
        st.warning(st.session_state["voice_error"])
    st.chat_input("Ask about US airports", key="typed", accept_audio=True, on_submit=_queue_chat, args=(backend,),
                  disabled=busy)
    _speech_call()
    if busy:
        _run_pending(backend, conv_id, st.session_state["pending"])


if __name__ == "__main__":
    main(get_backend())
