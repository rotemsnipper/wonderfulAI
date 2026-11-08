"""Chat logic behind the local UI: create, list, ask and reopen conversations. The Streamlit script only draws.

Conversations live in the session store passed in (in memory for M6), so they last only while the server runs.
Every ask returns a dict in the shape of `run_turn`'s result; a refused or failed ask carries `error`,
a user-facing `display_text` and `saved: False`.
"""
import itertools
from collections.abc import Callable

from backend.agent import llm
from backend.agent.loop import Agent, Event
from backend.agent.prompt import build_system_prompt
from backend.agent.session import SessionStore
from backend.tools import tools
from backend.tools.specs import TOOL_SPECS

USER_ID = "local-user"
TITLE_CHARS = 40
UNTITLED = "New conversation"

EMPTY_TEXT = "Please type a question."
SETUP_TEXT = ("The model is not set up: set the GEMINI_API_KEY variable in the .env file at the project root, "
              "then restart the app.")

MakeAgent = Callable[[Event], Agent]


def default_make_agent(on_event: Event) -> Agent:
    """The same prompt, tool specs and tools as `loop.default_agent()`, with a progress callback."""
    store = tools.ctx().store
    return Agent(system=build_system_prompt(store.manifest, store.settings), tool_specs=TOOL_SPECS,
                 call_tool=tools.call, on_event=on_event)


def _not_answered(error: str, text: str) -> dict:
    return {"error": error, "display_text": text, "saved": False,
            "check_outcome": {"status": "error", "unverified": []}, "tool_trace": [], "report": None}


def _ignore(kind: str, data: dict) -> None:
    pass


class ChatBackend:
    def __init__(self, store: SessionStore, make_agent: MakeAgent = default_make_agent,
                 user_id: str = USER_ID) -> None:
        self._store = store
        self._make_agent = make_agent
        self._user_id = user_id
        self._ids = itertools.count(1)
        self._conv_ids: list[str] = []

    def new_conversation(self) -> str:
        conv_id = f"conv-{next(self._ids)}"
        self._conv_ids.append(conv_id)
        return conv_id

    def conversations(self) -> list[dict]:
        """This server session's conversations, newest first; the title is the first saved question."""
        out = []
        for conv_id in reversed(self._conv_ids):
            turns = self._store.load(self._user_id, conv_id)
            title = turns[0].question[:TITLE_CHARS] if turns else UNTITLED
            out.append({"id": conv_id, "title": title, "turns": len(turns)})
        return out

    def history(self, conv_id: str) -> list[dict]:
        self._check(conv_id)
        return [t.to_dict() for t in self._store.load(self._user_id, conv_id)]

    def ask(self, conv_id: str, question: str, on_event: Event | None = None) -> dict:
        self._check(conv_id)
        question = question.strip()
        if not question:
            return _not_answered("empty_question", EMPTY_TEXT)
        try:
            agent = self._make_agent(on_event or _ignore)
            return agent.run_turn(self._store, self._user_id, conv_id, question)
        except llm.ConfigError:
            # Fixed text: the exception message is never shown, so nothing from the environment reaches the page.
            return _not_answered("ConfigError", SETUP_TEXT)

    @staticmethod
    def data_window() -> str:
        """The current data window, for example "2025-08 to 2026-07"."""
        return tools.ctx().store.window_label("current").replace("..", " to ")

    def _check(self, conv_id: str) -> None:
        if conv_id not in self._conv_ids:
            raise KeyError(f"unknown conversation: {conv_id}")
