from pathlib import Path

import pytest
import requests

from backend.tools import faa_status

XML = (Path(__file__).resolve().parents[1] / "fixtures" / "faa_status.xml").read_bytes()
UPDATE = "Sun Nov 8 22:27:39 2026 GMT"


@pytest.fixture
def feed(monkeypatch):
    monkeypatch.setattr(faa_status, "fetch_status", lambda: XML)


def test_parser_types_every_fixture_event_with_its_details():
    out = faa_status.parse(XML)
    assert out["update_time"] == UPDATE
    types = [(e["airport"], e["type"]) for e in out["events"]]
    assert types == [("TEB", "ground_stop"), ("AUS", "ground_delay_program"), ("SAN", "ground_delay_program"),
                     ("OPF", "arrival_departure_delay"), ("LAX", "ga_restriction"), ("SAN", "ga_restriction"),
                     ("LAS", "ga_restriction")]
    by = {(e["airport"], e["type"]): e for e in out["events"]}
    assert by["AUS", "ground_delay_program"]["details"] == {"avg": "1 hour", "max": "2 hours and 29 minutes"}
    assert by["TEB", "ground_stop"]["details"] == {"end_time": "6:00 pm EST"}
    opf = by["OPF", "arrival_departure_delay"]
    assert opf["direction"] == "Departure"
    assert opf["details"] == {"min": "16 minutes", "max": "30 minutes", "trend": "Increasing"}
    assert by["LAS", "ga_restriction"]["details"] == {"start": "Oct 28 at 19:26 UTC.", "reopen": "Jan 27 at 23:00 UTC."}


def test_tool_returns_only_requested_airports_and_names_those_with_nothing_listed(feed):
    env = faa_status.faa_airport_status(["aus", "SFO"])
    r = env["result"]
    assert [e["airport"] for e in r["events"]] == ["AUS"] and r["nothing_listed"] == ["SFO"]
    assert env["meta"]["airports"] == ["AUS", "SFO"]
    assert env["meta"]["periods"] == {"faa_nas_status": UPDATE}
    assert "not the same as no delays" in r["note"]


def test_ga_only_closure_is_kept_out_of_airline_events(feed):
    r = faa_status.faa_airport_status(["LAX"])["result"]
    assert r["events"] == [] and r["nothing_listed"] == ["LAX"]
    assert [e["airport"] for e in r["general_aviation_only"]] == ["LAX"]
    assert "airline flights are not affected" in r["general_aviation_only"][0]["note"]


def test_bad_codes_return_an_error():
    assert "3-letter" in faa_status.faa_airport_status(["BOSTON"])["error"]


def test_unreachable_feed_returns_unavailable_error(monkeypatch):
    def down():
        raise requests.ConnectionError("no route")
    monkeypatch.setattr(faa_status, "fetch_status", down)
    assert "unavailable" in faa_status.faa_airport_status()["error"]
