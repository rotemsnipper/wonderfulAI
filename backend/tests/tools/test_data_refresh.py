from pathlib import Path

import pytest

from backend.tools import data_refresh, tools
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(autouse=True)
def fixture_data(monkeypatch):
    tools.configure(load_store(FIXTURE))
    refreshes = []
    monkeypatch.setattr(data_refresh.ingest_refresh, "refresh", lambda: refreshes.append(1) or {})
    yield refreshes
    tools._ctx = None


def latest(t100, delay):
    return lambda after_ym: {"t100_summary": t100, "delay_causes": delay}


def test_newer_data_needs_every_checked_source_past_the_window(monkeypatch):
    monkeypatch.setattr(data_refresh, "latest_months", latest(202607, 202608))
    r = tools.call("check_data_updates", {})["result"]
    assert r["current_window"] == "2025-08..2026-07" and r["newer_data"] is False
    assert r["latest_available"] == {"t100_summary": "2026-07", "delay_causes": "2026-08"}
    monkeypatch.setattr(data_refresh, "latest_months", latest(202608, None))
    assert tools.call("check_data_updates", {})["result"]["latest_available"]["delay_causes"] == "unknown"


def test_refresh_without_newer_data_downloads_nothing(monkeypatch, fixture_data):
    monkeypatch.setattr(data_refresh, "latest_months", latest(202607, 202608))
    r = tools.call("refresh_data", {})
    assert r["result"]["status"] == "no_newer_data" and fixture_data == []
