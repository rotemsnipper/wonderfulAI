"""Live FAA airport status: delay programs, ground stops, closures and delays from the FAA NAS status feed.

`fetch_status` is the only network call, so tests replace it. Live data is context beside the historical
data: it has its own update time and never feeds a score, label or report.
"""
import re
import xml.etree.ElementTree as ET

import requests

from backend.ingest._download import USER_AGENT
from backend.tools.envelope import Envelope, Meta, error_result

URL = "https://nasstatus.faa.gov/api/airport-status-information"
TYPES = {
    "Ground Stop Programs": "ground_stop",
    "Ground Delay Programs": "ground_delay_program",
    "General Arrival/Departure Delay Info": "arrival_departure_delay",
    "Airport Closures": "closure",
}
# Long-running NOTAMs that close an airport to non-scheduled transient general aviation only, not to airlines.
GA_ONLY = "CLSD TO NON SKED TRANSIENT GA"
GA_NOTE = "closed to non-scheduled general aviation only; airline flights are not affected"
FEED_NOTE = ("The FAA feed lists only FAA delay programs, ground stops, closures and delays above the FAA "
             "reporting threshold, so nothing listed is not the same as no delays.")
UNAVAILABLE = "live FAA status is unavailable right now; try again in a few minutes"
CODE = re.compile(r"[A-Z]{3}")


def fetch_status() -> bytes:
    r = requests.get(URL, headers={"User-Agent": USER_AGENT}, timeout=8)
    r.raise_for_status()
    return r.content


def _event(item: ET.Element, kind: str) -> dict:
    airport = (item.findtext("ARPT") or "").strip().upper()
    reason = (item.findtext("Reason") or "").strip()
    details, direction = {}, None
    for el in item.iter():
        if el.tag == "Arrival_Departure":
            direction = el.get("Type")
        elif el is not item and el.tag not in ("ARPT", "Reason") and len(el) == 0:
            details[el.tag.lower()] = (el.text or "").strip()
    if kind == "closure" and GA_ONLY in reason.upper():
        kind = "ga_restriction"
    event = {"airport": airport, "type": kind, "reason": reason, "details": details}
    if kind == "arrival_departure_delay":
        event["direction"] = direction
    return event


def parse(xml: bytes) -> dict:
    """The feed as {update_time, events}. Raises ValueError when the XML is not the status feed."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise ValueError(f"unparsable FAA feed: {e}") from e
    update_time = (root.findtext("Update_Time") or "").strip()
    if root.tag != "AIRPORT_STATUS_INFORMATION" or not update_time:
        raise ValueError("not the FAA airport status feed")
    events = []
    for delay_type in root.iter("Delay_type"):
        kind = TYPES.get((delay_type.findtext("Name") or "").strip(), "other")
        for lst in delay_type:
            if lst.tag != "Name":
                events += [_event(item, kind) for item in lst]
    return {"update_time": update_time, "events": events}


def _codes(codes) -> list[str] | None:
    if not isinstance(codes, list) or not all(isinstance(c, str) for c in codes):
        return None
    out = [c.strip().upper() for c in codes]
    return list(dict.fromkeys(out)) if all(CODE.fullmatch(c) for c in out) else None


def faa_airport_status(codes: list[str] | None = None) -> dict:
    wanted = None
    if codes:
        wanted = _codes(codes)
        if wanted is None:
            return error_result("codes must be a list of 3-letter airport codes, for example [\"BOS\", \"SFO\"]")
    try:
        feed = parse(fetch_status())
    except (requests.RequestException, ValueError):
        return error_result(UNAVAILABLE)
    events = [e for e in feed["events"] if wanted is None or e["airport"] in wanted]
    airline = [e for e in events if e["type"] != "ga_restriction"]
    ga_only = [{**e, "note": GA_NOTE} for e in events if e["type"] == "ga_restriction"]
    involved = wanted or list(dict.fromkeys(e["airport"] for e in events))
    with_airline = {e["airport"] for e in airline}
    result = {
        "update_time": feed["update_time"],
        "events": airline,
        "general_aviation_only": ga_only,
        "nothing_listed": [c for c in wanted or [] if c not in with_airline],
        "note": FEED_NOTE,
    }
    return Envelope(tool="faa_airport_status", inputs={"codes": wanted}, result=result,
                    meta=Meta(airports=involved, periods={"faa_nas_status": feed["update_time"]})).to_dict()
