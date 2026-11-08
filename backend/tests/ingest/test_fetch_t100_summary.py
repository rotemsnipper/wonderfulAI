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


def test_pages_until_short_page_and_keeps_one_header(tmp_path):
    s = FakeSession([ok(HEADER + ROW * 2), ok(HEADER + ROW * 2), ok(HEADER + ROW)])
    path = fetch(tmp_path, start_year=2019, session=s, page_size=2)
    lines = path.read_bytes().splitlines()
    assert path.name == FILE_NAME
    assert len(lines) == 6 and lines.count(HEADER.strip()) == 1
    assert [c[2]["params"]["$offset"] for c in s.calls] == [0, 2, 4]
    assert s.calls[0][2]["params"]["$where"] == "year >= '2019'"


def test_bad_header_leaves_existing_file_untouched(tmp_path):
    (tmp_path / FILE_NAME).write_bytes(b"previous")
    with pytest.raises(FormatError):
        fetch(tmp_path, session=FakeSession([ok(b'"error"\n"rate limited"\n')]))
    assert (tmp_path / FILE_NAME).read_bytes() == b"previous"


def test_empty_result_is_rejected(tmp_path):
    with pytest.raises(FormatError, match="no data rows"):
        fetch(tmp_path, session=FakeSession([ok(HEADER)]))
