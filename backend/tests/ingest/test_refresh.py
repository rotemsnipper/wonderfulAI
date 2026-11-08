import json
from datetime import date

import pytest

from backend.ingest.build import BuildFailed
from backend.ingest.refresh import refresh

OLD = {"current": "2025-08..2026-07", "prior": "2024-08..2025-07", "baseline_year": 2019}
NEW = {"current": "2025-09..2026-08", "prior": "2024-09..2025-08", "baseline_year": 2019}


@pytest.fixture
def data(tmp_path):
    raw, out = tmp_path / "raw", tmp_path / "serving"
    raw.mkdir()
    (raw / "old.csv").write_text("old")
    out.mkdir()
    (out / "manifest.json").write_text(json.dumps({"window": OLD}))
    return raw, out


def fake_fetch(raw, current_raw, today, progress):
    raw.mkdir(parents=True)
    (raw / "new.csv").write_text("new")


def fake_build(window):
    def build(raw, out):
        out.mkdir(parents=True)
        (out / "manifest.json").write_text(json.dumps({"window": window}))
        return {"window": window, "checks": [{"name": "keys", "passed": True}]}
    return build


def run(data, build_fn):
    raw, out = data
    return refresh(raw, out, fetch=fake_fetch, build_fn=build_fn, today=date(2026, 11, 8))


def window_of(out):
    return json.loads((out / "manifest.json").read_text())["window"]["current"]


def test_newer_window_replaces_raw_and_serving(data):
    result = run(data, fake_build(NEW))
    raw, out = data
    assert result["status"] == "refreshed" and result["new_window"] == NEW
    assert window_of(out) == NEW["current"] and (raw / "new.csv").exists() and not (raw / "old.csv").exists()


def test_same_window_leaves_everything_in_place(data):
    assert run(data, fake_build(OLD))["status"] == "no_newer_data"
    raw, out = data
    assert window_of(out) == OLD["current"] and (raw / "old.csv").exists()


def test_failed_build_leaves_everything_in_place(data):
    def failing(raw, out):
        raise BuildFailed([{"name": "keys", "passed": False, "detail": "duplicates"}])

    with pytest.raises(BuildFailed):
        run(data, failing)
    raw, out = data
    assert window_of(out) == OLD["current"] and (raw / "old.csv").exists()
    assert [p.name for p in raw.parent.iterdir()] == ["raw", "serving"]  # temp folder removed
