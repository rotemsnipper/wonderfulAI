"""Chat logic behind the local UI: create, list, ask and reopen conversations. The Streamlit script only draws.

Conversations live in the session store passed in (in memory for M6), so they last only while the server runs.
Every ask returns a dict in the shape of `run_turn`'s result; a refused or failed ask carries `error`,
a user-facing `display_text` and `saved: False`.
"""
import itertools
import re
from collections.abc import Callable

from backend.agent import llm
from backend.agent.loop import Agent, Event
from backend.agent.prompt import build_system_prompt
from backend.agent.session import SessionStore
from backend.report.sections import VERDICT
from backend.tools import tools
from backend.tools.specs import TOOL_SPECS

USER_ID = "local-user"
TITLE_CHARS = 40
UNTITLED = "New conversation"

EMPTY_TEXT = "Please type a question."
SETUP_TEXT = ("The model is not set up: set the GEMINI_API_KEY variable in the .env file at the project root, "
              "then restart the app.")
NOT_HEARD_TEXT = "I couldn't make out a question in that recording. Please try again or type it."
VOICE_FAILED_TEXT = "The recording could not be transcribed right now. Please type your question."
# Words a spoken airport question is likely to contain, so the transcriber does not mishear them.
VOICE_HINT = ("terminal expansion, congestion, long-haul flights, unmet flight demand, load factor, delays, "
              "New England, LA, LAX, Santa Ana, John Wayne, SNA, Anchorage, ANC, SFO, San Francisco, Boston Logan, "
              "BOS, JFK, LaGuardia, LGA, Newark, EWR, Portland, PWM, PDX, Bangor, BGR, New Haven, HVN")

SPOKEN_CHARS = 420
SPOKEN_CLOSING = "The details, warnings and confidence are on screen."

MakeAgent = Callable[[Event], Agent]
Transcriber = Callable[[bytes, str, str], str]


def _plain(markdown: str) -> str:
    """Markdown as text to read aloud: no tables, emphasis, headings or bullets; a minus on a number stays."""
    text = re.sub(r"(?m)^\s*\|.*$", " ", markdown)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "", text)
    text = re.sub(r"[*_`#>]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _cap(text: str, max_chars: int = SPOKEN_CHARS) -> str:
    """The whole sentences that fit in max_chars; a first sentence longer than that is cut."""
    out = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if len(out) + len(sentence) + 1 > max_chars:
            break
        out += f"{sentence} "
    return out.strip() or text[:max_chars]


def spoken_text(turn: dict) -> str:
    """What the Listen button reads: a report's Verdict plus a pointer to the screen, else the capped answer text."""
    report = turn.get("report")
    verdict = next((s for s in report["sections"] if s["id"] == VERDICT), None) if report else None
    if verdict:
        return f"{_plain(verdict['markdown'])} {SPOKEN_CLOSING}"
    return _cap(_plain(turn.get("display_text") or ""))


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
                 user_id: str = USER_ID, transcriber: Transcriber = llm.transcribe) -> None:
        self._store = store
        self._make_agent = make_agent
        self._transcriber = transcriber
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

    def transcribe(self, audio: bytes, mime_type: str) -> dict:
        """{"text": question} from a recording, or {"error", "display_text"}; the question is then asked as typed."""
        try:
            text = self._transcriber(audio, mime_type, VOICE_HINT).strip()
        except llm.ConfigError:
            return {"error": "ConfigError", "display_text": SETUP_TEXT}
        except llm.RateLimitError as e:
            return {"error": "RateLimitError", "display_text": str(e)}
        except llm.ModelError:
            return {"error": "ModelError", "display_text": VOICE_FAILED_TEXT}
        return {"text": text} if text else {"error": "not_heard", "display_text": NOT_HEARD_TEXT}

    @staticmethod
    def data_window() -> str:
        """The current data window, for example "2025-08 to 2026-07"."""
        return tools.ctx().store.window_label("current").replace("..", " to ")

    def _check(self, conv_id: str) -> None:
        if conv_id not in self._conv_ids:
            raise KeyError(f"unknown conversation: {conv_id}")
