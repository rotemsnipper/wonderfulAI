import pytest

from backend.ingest import _download
from backend.ingest._download import FormatError
from backend.ingest.fetch_t100_segment import fetch
from backend.tests.ingest.fake_http import FakeSession, ok

PAGE = (b'<input id="__VIEWSTATE" value="vs1" /><input id="__VIEWSTATEGENERATOR" value="gen" />'
        b'<input id="__EVENTVALIDATION" value="ev" />')
CSV = ("YEAR,MONTH,ORIGIN,DEST,DEST_COUNTRY,DEPARTURES_PERFORMED,SEATS,PASSENGERS,FREIGHT,DISTANCE,CLASS\n"
       "2026,7,ANC,NRT,JP,10,0,0,500000,3460,G\n")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_download.time, "sleep", lambda s: None)


def test_corrupted_zip_leaves_existing_file_untouched(tmp_path):
    (tmp_path / "t100_segment_2026.zip").write_bytes(b"previous")
    with pytest.raises(FormatError):
        fetch(tmp_path, 2026, session=FakeSession([ok(PAGE), ok(b"<html>timeout</html>")]))
    assert (tmp_path / "t100_segment_2026.zip").read_bytes() == b"previous"
