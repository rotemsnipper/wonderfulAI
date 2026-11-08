import json

import pytest

from backend.ingest import _download
from backend.ingest._download import FormatError
from backend.ingest.fetch_ourairports import fetch
from backend.tests.ingest.fake_http import FakeSession, ok

AIRPORTS = (b'"id","ident","type","name","iso_country","iso_region","municipality","iata_code","scheduled_service"\n'
            b'1,"KSNA","large_airport","John Wayne","US","US-CA","Santa Ana","SNA","yes"\n')
RUNWAYS = b'"id","airport_ident","length_ft","surface","closed","le_ident"\n1,"KSNA",5700,"ASP",0,"02L"\n'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_download.time, "sleep", lambda s: None)


def test_fetch_into_empty_directory_writes_files_and_sidecars(tmp_path):
    out = fetch(tmp_path / "oa", session=FakeSession([ok(AIRPORTS), ok(RUNWAYS)]))
    assert (out / "airports.csv").read_bytes() == AIRPORTS
    assert (out / "runways.csv").read_bytes() == RUNWAYS
    side = json.loads((out / "airports.csv.json").read_text())
    assert side["bytes"] == len(AIRPORTS) and side["url"].endswith("/airports.csv") and "fetched_at" in side


def test_corrupted_download_leaves_existing_file_untouched(tmp_path):
    (tmp_path / "airports.csv").write_bytes(b"old good content")
    with pytest.raises(FormatError):
        fetch(tmp_path, session=FakeSession([ok(b"<html>error page</html>")]))
    assert (tmp_path / "airports.csv").read_bytes() == b"old good content"
    assert not list(tmp_path.glob("*.part"))


def test_user_agent_is_set(tmp_path):
    s = FakeSession([ok(AIRPORTS), ok(RUNWAYS)])
    fetch(tmp_path, session=s)
    assert "User-Agent" in s.headers
