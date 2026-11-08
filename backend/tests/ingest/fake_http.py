"""A stand-in for requests.Session that replays canned responses (no network in tests)."""
import io
import zipfile
from dataclasses import dataclass, field

import requests


@dataclass
class FakeResponse:
    status_code: int
    content: bytes


@dataclass
class FakeSession:
    responses: list  # FakeResponse, or an exception instance to raise
    headers: dict = field(default_factory=dict)
    calls: list = field(default_factory=list)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(content: bytes) -> FakeResponse:
    return FakeResponse(200, content)


def zip_bytes(name: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(name, text)
    return buf.getvalue()


CONNECTION_ERROR = requests.ConnectionError("connection reset")
