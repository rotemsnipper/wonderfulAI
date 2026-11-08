"""Fetch OurAirports airports.csv and runways.csv (public domain)."""
from pathlib import Path

import requests

from backend.ingest._download import USER_AGENT, csv_header, get_bytes, require_columns, with_retries, write_atomic

BASE_URL = "https://davidmegginson.github.io/ourairports-data"
FILES = {
    "airports.csv": {"ident", "type", "name", "iso_country", "iso_region", "municipality", "iata_code", "scheduled_service"},
    "runways.csv": {"airport_ident", "length_ft", "surface", "closed", "le_ident"},
}


def _checker(name: str):
    def check(path: Path) -> None:
        with path.open("rb") as fh:
            require_columns(csv_header(fh.read(4096)), FILES[name], f"OurAirports {name}")
    return check


def fetch(dest_dir: Path | str, session: requests.Session | None = None) -> Path:
    """Download both OurAirports files into `dest_dir`; return the directory."""
    dest_dir = Path(dest_dir)
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", USER_AGENT)
    for name in FILES:
        url = f"{BASE_URL}/{name}"
        content = with_retries(lambda: get_bytes(session, url))
        write_atomic(dest_dir / name, content, _checker(name), url)
    return dest_dir
