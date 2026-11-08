from pathlib import Path

import pytest

from backend.tools import resolver as resolver_module
from backend.tools.resolver import Resolver
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(scope="module")
def resolver():
    return Resolver(load_store(FIXTURE))


def codes(r):
    return [c["code"] for c in r["candidates"]]


def test_city_name_resolves(resolver):
    r = resolver.resolve("Sandy Orange airport")
    assert r["status"] == "resolved" and r["code"] == "SAA"


def test_same_city_in_two_states_asks_largest_first(resolver):
    r = resolver.resolve("Portland")
    assert r["status"] == "ambiguous" and r["code"] is None
    assert codes(r) == ["PMW", "PME"]
    assert r["ask"].index("PMW") < r["ask"].index("PME")


def test_small_uncovered_airport_is_not_offered_next_to_a_covered_one(resolver):
    r = resolver._choose("springfield-like", ["SPA", "TNY"])
    assert r["status"] == "resolved" and r["code"] == "SPA"


def test_many_matches_list_at_most_three_largest(resolver):
    r = resolver._choose("west coast", ["SAA", "PMW", "LAA", "BAY"])
    assert codes(r) == ["LAA", "BAY", "PMW"]
    assert r["more_matches"] == 1 and "SAA" not in r["ask"]


def test_abbreviation_expands_to_its_city_not_to_name_words(monkeypatch, resolver):
    # without the expansion "LA" would match airports with "La" in their name
    monkeypatch.setitem(resolver_module.ABBREVIATIONS, "LK", "Lakeshore")
    r = resolver.resolve("lk")
    assert r["status"] == "resolved" and r["code"] == "LAA"


def test_unknown_airport_not_found(resolver):
    r = resolver.resolve("Atlantis Spaceport")
    assert r["status"] == "not_found" and r["candidates"] == []


def test_three_letter_place_name_is_not_accepted_as_code(resolver):
    r = resolver.resolve("Rio")
    assert r["status"] == "not_found" and r["code"] is None


def test_empty_query(resolver):
    assert resolver.resolve("  ")["status"] == "not_found"
