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


def test_corrupted_download_leaves_existing_file_untouched(tmp_path):
    (tmp_path / "airports.csv").write_bytes(b"old good content")
    with pytest.raises(FormatError):
        fetch(tmp_path, session=FakeSession([ok(b"<html>error page</html>")]))
    assert (tmp_path / "airports.csv").read_bytes() == b"old good content"
    assert not list(tmp_path.glob("*.part"))
