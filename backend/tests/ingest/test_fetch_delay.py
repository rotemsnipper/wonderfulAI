import pytest

from backend.ingest import _download
from backend.ingest._download import FormatError
from backend.ingest.fetch_delay import CSV_NAME, fetch
from backend.tests.ingest.fake_http import FakeSession, ok

CSV = ("year,month,carrier,airport,arr_flights,arr_del15,carrier_ct,weather_ct,nas_ct,security_ct,"
       "late_aircraft_ct,arr_cancelled,arr_delay\n2026,7,AA,LAX,100,20,5,1,8,0,6,1,900\n")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_download.time, "sleep", lambda s: None)


def test_corrupted_zip_leaves_existing_files_untouched(tmp_path):
    (tmp_path / CSV_NAME).write_text("previous")
    (tmp_path / "delay_202508_202607.zip").write_bytes(b"previous zip")
    with pytest.raises(FormatError):
        fetch(tmp_path, (2025, 8), (2026, 7), session=FakeSession([ok(b"not a zip")]))
    assert (tmp_path / CSV_NAME).read_text() == "previous"
    assert (tmp_path / "delay_202508_202607.zip").read_bytes() == b"previous zip"
