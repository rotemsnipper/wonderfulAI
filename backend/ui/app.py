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
from backend.ui.chat_backend import ChatBackend  # noqa: E402

SAMPLE_QUESTIONS = [
    "Which airports in New England are strong candidates for terminal expansion?",
    "Compare LA and Santa Ana airport congestion levels.",
    "What is the percentage of long-haul flights out of Anchorage airport?",
    "What is the unmet flight demand in SFO airport and why?",
]
SCOPE_NOTE = "The score ranks capacity need, a proxy for profit, not a return estimate."
DEMO_NOTE = "Local demo with a single user. Conversations last only while the server runs."
CHECK_COLORS = {"passed": "green", "rewritten": "blue", "flagged": "red"}


@st.cache_resource
def get_backend() -> ChatBackend:
    return ChatBackend(InMemorySessionStore())


def _queue(backend: ChatBackend, question: str) -> None:
    if st.session_state.get("selected") is None:
        st.session_state["selected"] = backend.new_conversation()
    st.session_state["pending"] = question
    st.session_state["notice"] = None


def _queue_typed(backend: ChatBackend) -> None:
    _queue(backend, st.session_state.get("typed") or "")


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


def _answer(backend: ChatBackend, turn: dict, suggestions: bool, busy: bool) -> None:
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
    st.session_state["pending"] = None
    st.session_state["notice"] = None if result.get("saved") else {"conv": conv_id, "question": question,
                                                                    "text": result["display_text"]}
    st.rerun()


def main(backend: ChatBackend) -> None:
    st.session_state.setdefault("selected", None)
    st.session_state.setdefault("pending", None)
    st.session_state.setdefault("notice", None)
    busy = st.session_state["pending"] is not None
    conv_id = st.session_state["selected"]

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
            _answer(backend, turn, suggestions=i == len(turns) - 1, busy=busy)
    notice = st.session_state["notice"]
    if notice and notice["conv"] == conv_id:
        with st.chat_message("user"):
            st.markdown(notice["question"])
        with st.chat_message("assistant"):
            st.warning(notice["text"])

    st.chat_input("Ask about US airports", key="typed", on_submit=_queue_typed, args=(backend,), disabled=busy)
    if busy:
        _run_pending(backend, conv_id, st.session_state["pending"])


if __name__ == "__main__":
    main(get_backend())
