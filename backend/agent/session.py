"""Session-store interface, the Turn record, an in-memory store, and the number-pool rebuild used on resume."""
import copy
import json
from dataclasses import asdict, dataclass, field
from typing import Protocol

from backend.agent.safeguards import numbers_in_data


@dataclass
class Turn:
    question: str
    model_messages: list[dict]
    tool_trace: list[dict]
    check_outcome: dict
    footer: dict
    warnings: list[dict]
    display_text: str
    tokens: dict = field(default_factory=dict)
    timings: dict = field(default_factory=dict)
    model: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Turn":
        return cls(**data)


class SessionStore(Protocol):
    def load(self, user_id: str, conv_id: str) -> list[Turn]: ...

    def append_turn(self, user_id: str, conv_id: str, turn: Turn) -> None: ...


class InMemorySessionStore:
    """Keeps turns as serialized JSON, so a turn is stored whole or not at all and loads as an independent copy."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], list[str]] = {}

    def load(self, user_id: str, conv_id: str) -> list[Turn]:
        return [Turn.from_dict(json.loads(s)) for s in self._data.get((user_id, conv_id), [])]

    def append_turn(self, user_id: str, conv_id: str, turn: Turn) -> None:
        serialized = json.dumps(turn.to_dict())  # raises before anything is stored
        self._data.setdefault((user_id, conv_id), []).append(serialized)


def history_messages(turns: list[Turn]) -> list[dict]:
    """The model messages of all stored turns, in order, ready to send with the next question."""
    return [copy.deepcopy(m) for t in turns for m in t.model_messages]


def rebuild_pool(turns: list[Turn]) -> set[float]:
    """Number-check pool from reloaded tool inputs and results; equals the pool built live from the same traces."""
    pool: set[float] = set()
    for t in turns:
        pool |= pool_from_trace(t.tool_trace)
    return pool


def pool_from_trace(trace: list[dict]) -> set[float]:
    pool: set[float] = set()
    for call in trace:
        pool |= numbers_in_data(call.get("args"))
        pool |= numbers_in_data(call.get("result"))
    return pool
