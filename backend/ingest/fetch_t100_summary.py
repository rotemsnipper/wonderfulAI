"""Fetch the BTS T-100 airport-month summary (all carriers, domestic plus international) from data.bts.gov.

Socrata dataset r495-tyji, paged CSV. Year is stored as text in this dataset; the builder coerces it.
"""
import io
from pathlib import Path

import requests

from backend.ingest._download import (
    USER_AGENT, FormatError, csv_header, get_bytes, require_columns, with_retries, write_atomic,
)

URL = "https://data.bts.gov/resource/r495-tyji.csv"
FILE_NAME = "t100_by_origin.csv"
EXPECTED = {"origin_airport_id", "year", "reporting_month", "origin_airport_code", "total_departures",
            "total_passengers", "total_seats", "total_freight_lbs"}
PAGE_SIZE = 50_000


def check_csv(path: Path) -> None:
    with path.open("rb") as fh:
        head = fh.read(8192)
    require_columns(csv_header(head), EXPECTED, "T-100 summary")
    if head.count(b"\n") < 2:
        raise FormatError("T-100 summary has no data rows")


def fetch(dest_dir: Path | str, start_year: int = 2014, end_year: int | None = None,
          session: requests.Session | None = None, page_size: int = PAGE_SIZE) -> Path:
    """Download all rows with start_year <= year (<= end_year) into one CSV; return its path."""
    dest_dir = Path(dest_dir)
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    where = f"year >= '{start_year}'" + (f" AND year <= '{end_year}'" if end_year else "")
    out = io.BytesIO()
    offset = 0
    while True:
        params = {"$where": where, "$order": "reporting_month, origin_airport_id", "$limit": page_size, "$offset": offset}
        page = with_retries(lambda: get_bytes(session, URL, params=params))
        header, _, body = page.partition(b"\n")
        if offset == 0:
            out.write(header + b"\n")
        rows = body.count(b"\n") + (1 if body and not body.endswith(b"\n") else 0)
        out.write(body if body.endswith(b"\n") or not body else body + b"\n")
        if rows < page_size:
            break
        offset += page_size
    return write_atomic(dest_dir / FILE_NAME, out.getvalue(), check_csv, URL)
