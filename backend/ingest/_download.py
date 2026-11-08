"""Shared download helper for the fetchers: temp file, format check, atomic swap, retries, sidecar JSON."""
import json
import logging
import os
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

USER_AGENT = "airport-investment-agent/0.1 (public-data ingest)"
# TranStats rejects non-browser user agents, so its fetchers pass this one instead.
BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126 Safari/537.36"


class FormatError(ValueError):
    """The downloaded bytes are not the expected file format."""


class DownloadError(RuntimeError):
    pass


def with_retries(fn: Callable[[], bytes], attempts: int = 3, backoff_s: float = 2.0) -> bytes:
    last = None
    for i in range(attempts):
        try:
            return fn()
        except (requests.RequestException, DownloadError) as e:
            last = e
            log.warning("download attempt %d/%d failed: %s", i + 1, attempts, e)
            if i + 1 < attempts:
                time.sleep(backoff_s * 2**i)
    raise DownloadError(f"download failed after {attempts} attempts: {last}") from last


def get_bytes(session: requests.Session, url: str, *, method: str = "GET", timeout: float = 300, **kwargs) -> bytes:
    resp = session.request(method, url, timeout=timeout, **kwargs)
    if resp.status_code != 200:
        raise DownloadError(f"HTTP {resp.status_code} from {url}")
    return resp.content


def write_atomic(dest: Path, content: bytes, check: Callable[[Path], None], url: str) -> Path:
    """Write `content` to a temp file next to `dest`, run `check` on it, and swap it in only if the check passes.

    On a failed check the temp file is removed and any existing `dest` is left untouched.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)
        check(tmp)
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    write_sidecar(dest, url, content)
    return dest


def write_sidecar(dest: Path, url: str, content: bytes) -> Path:
    side = dest.with_name(dest.name + ".json")
    side.write_text(json.dumps({
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bytes": len(content),
    }, indent=2), encoding="utf-8")
    return side


def csv_header(raw: bytes) -> list[str]:
    first = raw.split(b"\n", 1)[0].decode("utf-8-sig", errors="replace").strip()
    return [c.strip().strip('"').strip() for c in first.split(",")]


def require_columns(header: list[str], expected: set[str], what: str) -> None:
    got = {c.lower() for c in header}
    missing = sorted(c for c in expected if c.lower() not in got)
    if missing:
        raise FormatError(f"{what}: header is missing expected columns {missing}")
