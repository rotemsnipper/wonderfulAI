"""The two data-update tools: check whether BTS has months newer than the serving data, and refresh it.

`latest_months` is the only network call in the check, so tests replace it. A refresh reloads the tools'
store, so the next question (and the UI's next agent, whose prompt carries the data period) uses the new data.
Only one refresh runs at a time.
"""
import tempfile
import threading
from pathlib import Path

import pandas as pd
import requests

from backend.ingest import fetch_delay, fetch_t100_summary
from backend.ingest import refresh as ingest_refresh
from backend.ingest._download import USER_AGENT, DownloadError, FormatError
from backend.ingest.build import BuildFailed
from backend.tools.envelope import Envelope, error_result

SOURCES = ("t100_summary", "delay_causes")
SEGMENT_NOTE = "T-100 segment (routes) has no quick check; a refresh confirms it."
_lock = threading.Lock()


def _ym(text: str) -> int:
    return int(text[:4]) * 100 + int(text[5:7])


def _label(ym: int | None) -> str:
    return "unknown" if ym is None else f"{ym // 100}-{ym % 100:02d}"


def latest_months(after_ym: int) -> dict[str, int | None]:
    """Newest month each source has (None when the check fails). Delay causes are probed by downloading only
    the months after `after_ym`; T-100 answers a max() query."""
    out: dict[str, int | None] = {}
    try:
        r = requests.get(fetch_t100_summary.URL, params={"$select": "max(reporting_month)"},
                         headers={"User-Agent": USER_AGENT}, timeout=60)
        r.raise_for_status()
        out["t100_summary"] = _ym(r.text.splitlines()[1].strip('"'))
    except (requests.RequestException, IndexError, ValueError):
        out["t100_summary"] = None
    y, m = divmod(after_ym, 100)
    start = (y + m // 12, m % 12 + 1)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            d = pd.read_csv(fetch_delay.fetch(Path(tmp), start, (start[0] + 1, 12)), usecols=["year", "month"])
        out["delay_causes"] = int((d["year"] * 100 + d["month"]).max()) if len(d) else after_ym
    except (requests.RequestException, DownloadError, FormatError, ValueError):
        out["delay_causes"] = None
    return out


def _store():
    from backend.tools import tools
    return tools.ctx().store


def _check() -> dict:
    store = _store()
    end = store.latest_ym
    latest = latest_months(end)
    newer = all(v is not None and v > end for v in latest.values())
    return {"current_window": store.window_label("current"),
            "latest_available": {s: _label(latest.get(s)) for s in SOURCES},
            "newer_data": newer, "note": SEGMENT_NOTE}


def check_data_updates() -> dict:
    return Envelope(tool="check_data_updates", inputs={}, result=_check()).to_dict()


def refresh_data() -> dict:
    if not _lock.acquire(blocking=False):
        return error_result("a data refresh is already running; try again when it finishes")
    try:
        check = _check()
        if not check["newer_data"]:
            return Envelope(tool="refresh_data", inputs={}, result={"status": "no_newer_data", **check}).to_dict()
        try:
            out = ingest_refresh.refresh()
        except (requests.RequestException, DownloadError, FormatError, BuildFailed) as e:
            return error_result(f"the refresh failed and the data was left unchanged: {type(e).__name__}: {e}"[:400])
        if out["status"] == "refreshed":
            from backend.tools import tools
            tools.configure()
        result = {"status": out["status"], "old_window": out["old_window"]["current"],
                  "new_window": out["new_window"]["current"],
                  "note": "Answers given earlier in this conversation used the old window."}
        return Envelope(tool="refresh_data", inputs={}, result=result).to_dict()
    finally:
        _lock.release()
