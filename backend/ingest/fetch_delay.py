"""Fetch BTS Airline On-Time delay causes (monthly, per carrier and airport) from TranStats.

The TranStats download endpoint takes a ROT13-style encoded `where` clause over yearmonth
(year * 12 + month). The zip holds Airline_Delay_Cause.csv, which is also extracted next to it.
"""
import string
import zipfile
from pathlib import Path

import requests

from backend.ingest._download import (
    BROWSER_USER_AGENT, FormatError, csv_header, get_bytes, require_columns, with_retries, write_atomic,
)

URL = "https://www.transtats.bts.gov/OT_Delay/ot_delaycause1_DL.aspx"
CSV_NAME = "Airline_Delay_Cause.csv"
EXPECTED = {"year", "month", "carrier", "airport", "arr_flights", "arr_del15", "carrier_ct", "weather_ct",
            "nas_ct", "security_ct", "late_aircraft_ct", "arr_cancelled", "arr_delay"}
_ALPHA = string.ascii_uppercase + string.ascii_lowercase + string.digits


def encode(text: str) -> str:
    return "".join(_ALPHA[(_ALPHA.index(c) + 13) % 62] if c in _ALPHA else c for c in text)


def check_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise FormatError("delay causes download is not a zip file")
    with zipfile.ZipFile(path) as z:
        if CSV_NAME not in z.namelist():
            raise FormatError(f"delay causes zip has no {CSV_NAME}")
        with z.open(CSV_NAME) as fh:
            require_columns(csv_header(fh.read(4096)), EXPECTED, "delay causes")


def fetch(dest_dir: Path | str, start: tuple[int, int], end: tuple[int, int],
          session: requests.Session | None = None) -> Path:
    """Download delay causes for months start..end (inclusive, (year, month)); return the CSV path."""
    dest_dir = Path(dest_dir)
    session = session or requests.Session()
    session.headers["User-Agent"] = BROWSER_USER_AGENT
    (y0, m0), (y1, m1) = start, end
    params = {"8n4": encode(f"where yearmonth between {y0 * 12 + m0} AND {y1 * 12 + m1}")}
    content = with_retries(lambda: get_bytes(session, URL, params=params))
    zip_path = write_atomic(dest_dir / f"delay_{y0}{m0:02d}_{y1}{m1:02d}.zip", content, check_zip, URL)
    with zipfile.ZipFile(zip_path) as z:
        csv_bytes = z.read(CSV_NAME)
    return write_atomic(dest_dir / CSV_NAME, csv_bytes,
                        lambda p: require_columns(csv_header(csv_bytes[:4096]), EXPECTED, "delay causes"), URL)
