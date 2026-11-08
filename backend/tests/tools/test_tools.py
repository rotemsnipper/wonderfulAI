import json
from pathlib import Path

import pytest

from backend.config import load_settings
from backend.tools import tools
from backend.tools.envelope import Envelope
from backend.tools.specs import TOOL_SPECS
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(autouse=True, scope="module")
def fixture_data():
    tools.configure(load_store(FIXTURE))
    yield
    tools._ctx = None


def is_error(r):
    return set(r) == {"error", "valid_options"}


def assert_envelope(r):
    assert not is_error(r), r
    Envelope.model_validate(r)
    json.dumps(r)


# ---- dispatcher ----

def test_specs_match_tool_names_and_parameters():
    import inspect
    assert [s["name"] for s in TOOL_SPECS] == list(tools.TOOLS)
    for s in TOOL_SPECS:
        assert set(s["parameters"]["properties"]) == set(inspect.signature(tools.TOOLS[s["name"]]).parameters)


@pytest.mark.parametrize("name,args", [
    ("nope", {}),
    ("rank_airports", {"metric": "roi"}),
    ("compare_airports", {"codes": ["LAA"]}),
    ("airport_profile", {"code": "LAA", "long_haul_cutoff_mi": 1234}),
])
def test_bad_input_returns_error_with_options_and_never_raises(name, args):
    r = tools.call(name, args)
    assert is_error(r)


def test_dispatcher_catches_internal_errors(monkeypatch):
    def boom(code, long_haul_cutoff_mi=None):
        raise RuntimeError("bug")
    monkeypatch.setitem(tools.TOOLS, "airport_profile", boom)
    r = tools.call("airport_profile", {"code": "LAA"})
    assert is_error(r) and "RuntimeError" in r["error"]


def test_unknown_airport_code_points_to_resolver():
    r = tools.call("airport_profile", {"code": "XYZ"})
    assert is_error(r) and "resolve_airport" in r["error"]


# ---- resolve ----

def test_resolve_envelope():
    r = tools.call("resolve_airport", {"query": "Portland"})
    assert_envelope(r)
    assert r["result"]["status"] == "ambiguous" and r["meta"]["airports"] == ["PMW", "PME"]


# ---- rank ----

def test_rank_groups_by_size_tier_with_robustness_and_partial_scores():
    r = tools.call("rank_airports", {})
    assert_envelope(r)
    res = r["result"]
    assert set(res["groups"]) <= {"large", "medium", "small", "nonhub"}
    for tier, rows in res["groups"].items():
        assert all(row["size_tier"] == tier for row in rows)
        assert [row["value"] for row in rows] == sorted((row["value"] for row in rows), reverse=True)
    assert res["robustness"]["summary"].startswith("Robustness:")
    not_ranked = {x["code"]: x for x in res["not_ranked"]}
    assert set(not_ranked) == {"NHV"}
    assert "partial score" in not_ranked["NHV"]["reason"] and not_ranked["NHV"]["partial_score"] is not None
    assert "TNY" not in json.dumps(res["groups"])


def test_rank_cut_flag_and_named_exclusions():
    r = tools.call("rank_airports", {"limit": 1})
    res = r["result"]
    assert res["list_was_cut"] is True
    assert all(len(rows) == 1 for rows in res["groups"].values())
    assert "BAY" in res["cut_airports"] or "PMW" in res["cut_airports"]


def test_rank_state_filter_and_metric():
    r = tools.call("rank_airports", {"state": "CA", "metric": "delay_rate"})
    rows = [row for rows in r["result"]["groups"].values() for row in rows]
    assert {row["code"] for row in rows} == {"LAA", "SAA", "BAY"}
    bay = next(row for row in rows if row["code"] == "BAY")
    assert bay["rank"] == 1 and bay["display"] == "25.0%"
    assert "robustness" not in r["result"]


def test_rank_accepts_whole_float_limit_from_model():
    assert not is_error(tools.call("rank_airports", {"limit": 3.0}))


def test_rank_no_match_is_error():
    assert is_error(tools.call("rank_airports", {"state": "NE"}))  # only TNY, which is not covered


# ---- compare ----

def test_compare_differences_from_displayed_values_and_cross_size_note():
    r = tools.call("compare_airports", {"codes": ["LAA", "SAA"]})
    assert_envelope(r)
    d = {x["metric"]: x for x in r["result"]["differences"]}
    assert d["delay_rate_pct"]["difference"] == 2.0 and d["delay_rate_pct"]["difference_unit"] == "percentage points"
    assert d["delay_rate_pct"]["ratio"] == 1.11
    assert d["passengers"]["a_value"] == 36_000_000 and d["passengers"]["b_value"] == 5_500_000
    assert r["result"]["size_tiers_differ"] is True and any("size tiers" in n for n in r["notes"])
    lax = r["result"]["airports"][0]
    assert lax["display"]["delay_rate_pct"] == "20.0%" and lax["runways_usable"] == 4


def test_compare_no_delay_airport_gives_unknown_not_zero():
    r = tools.call("compare_airports", {"codes": ["LAA", "NHV"]})
    d = {x["metric"]: x for x in r["result"]["differences"]}
    assert d["delay_rate_pct"]["difference"] is None
    nhv = r["result"]["airports"][1]
    assert nhv["metrics"]["delay_rate_pct"] is None and "delay_rate_pct" not in nhv["display"]
    assert r["data_quality"]["NHV"]["confidence"] == "low"
    assert any(w["airport"] == "NHV" and w["type"] == "partial_data" for w in r["warnings"])


# ---- profile ----

def test_profile_long_haul_both_bases_and_cargo_warning():
    r = tools.call("airport_profile", {"code": "NRC"})
    assert_envelope(r)
    lh = r["result"]["long_haul"]
    assert lh["headline_cutoff_mi"] == 3000 and lh["display"] == {"passenger_flights": "3.3%", "all_flights": "45.2%"}
    assert [x["cutoff_mi"] for x in lh["table"]] == [2000, 2500, 3000]
    assert lh["cargo_share_of_departures_pct"] == 50.0
    assert [w["type"] for w in r["warnings"]] == ["cargo_heavy"]
    assert r["meta"]["periods"]["t100_segment"] == "2025-08..2026-07"


def test_profile_cutoff_override_from_float():
    r = tools.call("airport_profile", {"code": "NRC", "long_haul_cutoff_mi": 2000.0})
    assert r["result"]["long_haul"]["display"]["passenger_flights"] == "33.3%"
    assert r["inputs"]["long_haul_cutoff_mi"] == 2000


def test_profile_unmet_demand_zero_seat_gap_and_proxy_flag():
    r = tools.call("airport_profile", {"code": "BAY"})
    u = r["result"]["unmet_demand"]
    assert u["seat_gap"] == 0 and "zero seat gap" in u["seat_gap_interpretation"]
    assert u["excess_delayed_flights"] == 7200 and u["national_median_delay_rate_pct"] == 20.0
    assert "Lower bound" in u["lower_bound_note"]
    assert r["meta"]["uses_proxy"] is True
    assert any(d["name"] == "seat_gap" and d["proxy_note"] for d in r["definitions"])


def test_assumption_text_comes_from_config():
    r = tools.call("airport_profile", {"code": "LAA"})
    defs = {d["name"]: d for d in r["definitions"]}
    s = load_settings()
    assert f"{s['load_factor_ceiling']:.0%}" in defs["seat_gap"]["definition"]
    assert f"{s['usable_runway_min_ft']:,}" in defs["departures_per_usable_runway"]["definition"]


def test_profile_full_airport_has_side_scores_and_label():
    s = tools.call("airport_profile", {"code": "DPX"})["result"]["score"]
    assert s["passenger_score"] == 70.0 and s["flight_score"] == 70.6
    assert s["potential"] == "high" and s["confidence"] == "high"
    assert s["recommendation"] == "Prioritize for due diligence"
    assert [x["component"] for x in s["strengths"]] == ["load_factor", "flight_growth"]
    assert s["weaknesses"] == []


def test_profile_partial_airport_is_not_scored_and_low_confidence():
    r = tools.call("airport_profile", {"code": "NHV"})
    s = r["result"]["score"]
    assert s["potential"] == "not scored" and s["confidence"] == "low"
    assert s["passenger_score"] == 30.0 and s["flight_score"] is None
    assert r["data_quality"]["NHV"]["confidence"] == "low"
