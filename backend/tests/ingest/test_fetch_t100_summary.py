import pytest

from backend.ingest import _download
from backend.ingest._download import FormatError
from backend.ingest.fetch_t100_summary import FILE_NAME, fetch
from backend.tests.ingest.fake_http import FakeSession, ok

HEADER = (b'"origin_airport_id","year","reporting_month","origin_airport_code","total_departures",'
          b'"total_passengers","total_seats","total_freight_lbs"\n')
ROW = b'"12892","2026","2026-07-01T00:00:00.000","LAX","100","1000","1200","5"\n'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(_download.time, "sleep", lambda s: None)


def test_bad_header_leaves_existing_file_untouched(tmp_path):
    (tmp_path / FILE_NAME).write_bytes(b"previous")
    with pytest.raises(FormatError):
        fetch(tmp_path, session=FakeSession([ok(b'"error"\n"rate limited"\n')]))
    assert (tmp_path / FILE_NAME).read_bytes() == b"previous"
