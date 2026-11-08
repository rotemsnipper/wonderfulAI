import pytest

from backend.ingest import _download
from backend.ingest._download import DownloadError, FormatError
from backend.ingest.fetch_delay import CSV_NAME, encode, fetch
from backend.tests.ingest.fake_http import CONNECTION_ERROR, FakeResponse, FakeSession, ok, zip_bytes

CSV = ("year,month,carrier,airport,arr_flights,arr_del15,carrier_ct,weather_ct,nas_ct,security_ct,"
       "late_aircraft_ct,arr_cancelled,arr_delay\n2026,7,AA,LAX,100,20,5,1,8,0,6,1,900\n")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_download.time, "sleep", lambda s: None)


def test_encode_rotates_by_13_over_upper_lower_digits():
    assert encode("A") == "N" and encode("Z") == "m" and encode("x") == "A" and encode("9") == "M"
    assert encode("where 1 AND") == "9ur4r E NaQ"


def test_fetch_writes_zip_and_extracted_csv(tmp_path):
    s = FakeSession([ok(zip_bytes(CSV_NAME, CSV))])
    path = fetch(tmp_path, (2025, 8), (2026, 7), session=s)
    assert path == tmp_path / CSV_NAME and path.read_text() == CSV
    assert (tmp_path / "delay_202508_202607.zip").exists()
    assert (tmp_path / f"{CSV_NAME}.json").exists()
    assert s.calls[0][2]["params"]["8n4"] == encode("where yearmonth between 24308 AND 24319")


def test_retries_then_succeeds(tmp_path):
    s = FakeSession([CONNECTION_ERROR, FakeResponse(503, b""), ok(zip_bytes(CSV_NAME, CSV))])
    assert fetch(tmp_path, (2025, 8), (2026, 7), session=s).exists()
    assert len(s.calls) == 3


def test_gives_up_after_retries(tmp_path):
    with pytest.raises(DownloadError):
        fetch(tmp_path, (2025, 8), (2026, 7), session=FakeSession([CONNECTION_ERROR] * 3))


def test_corrupted_zip_leaves_existing_files_untouched(tmp_path):
    (tmp_path / CSV_NAME).write_text("previous")
    (tmp_path / "delay_202508_202607.zip").write_bytes(b"previous zip")
    with pytest.raises(FormatError):
        fetch(tmp_path, (2025, 8), (2026, 7), session=FakeSession([ok(b"not a zip")]))
    assert (tmp_path / CSV_NAME).read_text() == "previous"
    assert (tmp_path / "delay_202508_202607.zip").read_bytes() == b"previous zip"


def test_zip_with_wrong_header_is_rejected(tmp_path):
    with pytest.raises(FormatError, match="nas_ct"):
        fetch(tmp_path, (2025, 8), (2026, 7), session=FakeSession([ok(zip_bytes(CSV_NAME, "year,month\n1,2\n"))]))
    assert not (tmp_path / CSV_NAME).exists()
