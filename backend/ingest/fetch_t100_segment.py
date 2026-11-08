"""Fetch one year of BTS T-100 Segment (All Carriers) by replaying the TranStats download form."""
import re
import zipfile
from pathlib import Path

import requests

from backend.ingest._download import (
    BROWSER_USER_AGENT, DownloadError, FormatError, csv_header, get_bytes, require_columns, with_retries,
    write_atomic,
)

URL = "https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FMG&QO_fu146_anzr=Nv4%20Pn44vr45"
CSV_NAME = "T_T100_SEGMENT_ALL_CARRIER.csv"
FIELDS = ["YEAR", "MONTH", "UNIQUE_CARRIER", "UNIQUE_CARRIER_NAME", "ORIGIN_AIRPORT_ID", "ORIGIN",
          "ORIGIN_CITY_NAME", "ORIGIN_STATE_ABR", "ORIGIN_COUNTRY", "DEST_AIRPORT_ID", "DEST", "DEST_CITY_NAME",
          "DEST_STATE_ABR", "DEST_COUNTRY", "DEPARTURES_SCHEDULED", "DEPARTURES_PERFORMED", "SEATS",
          "PASSENGERS", "FREIGHT", "DISTANCE", "AIR_TIME", "AIRCRAFT_TYPE", "CLASS", "DATA_SOURCE"]
EXPECTED = {"YEAR", "MONTH", "ORIGIN", "DEST", "DEST_COUNTRY", "DEPARTURES_PERFORMED", "SEATS", "PASSENGERS",
            "FREIGHT", "DISTANCE", "CLASS"}
_HIDDEN = ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION")


def check_zip(path: Path) -> None:
    if not zipfile.is_zipfile(path):
        raise FormatError("T-100 segment download is not a zip file")
    with zipfile.ZipFile(path) as z:
        if CSV_NAME not in z.namelist():
            raise FormatError(f"T-100 segment zip has no {CSV_NAME}")
        with z.open(CSV_NAME) as fh:
            require_columns(csv_header(fh.read(4096)), EXPECTED, "T-100 segment")


def _form(page: str, year: int) -> dict:
    form = {}
    for key in _HIDDEN:
        m = re.search(r'id="%s" value="([^"]*)"' % key, page)
        if not m:
            raise DownloadError(f"TranStats form field {key} not found; the page layout may have changed")
        form[key] = m.group(1)
    form.update({"__EVENTTARGET": "", "__EVENTARGUMENT": "", "__LASTFOCUS": "", "cboGeography": "All",
                 "cboPeriod": "All", "chkDownloadZip": "on", "btnDownload": "Download", "cboYear": str(year)})
    form.update({f: "on" for f in FIELDS})
    return form


def fetch(dest_dir: Path | str, year: int, session: requests.Session | None = None) -> Path:
    """Download the segment zip for `year`; return its path (t100_segment_<year>.zip)."""
    dest_dir = Path(dest_dir)
    session = session or requests.Session()
    session.headers["User-Agent"] = BROWSER_USER_AGENT

    def attempt() -> bytes:
        page = get_bytes(session, URL, timeout=120).decode("utf-8", errors="replace")
        return get_bytes(session, URL, method="POST", data=_form(page, year), timeout=900, headers={"Referer": URL})

    content = with_retries(attempt)
    return write_atomic(dest_dir / f"t100_segment_{year}.zip", content, check_zip, URL)
