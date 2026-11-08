import dataclasses
from pathlib import Path

import pytest

from backend.scoring import metrics
from backend.scoring.warnings import airport_warnings, sort_warnings
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(scope="module")
def store():
    return load_store(FIXTURE)


@pytest.fixture(scope="module")
def settings(store):
    return store.settings


def test_national_median_delay_rate_excludes_no_data_and_out_of_universe(store):
    assert metrics.national_median_delay_rate(store) == pytest.approx(20.0)


@pytest.mark.parametrize(
    "code,delay,system,cancel,dep_per_rwy",
    [("LAA", 20.0, 5.0, 1.0, 66_000), ("SAA", 18.0, 4.0, 1.0, 51_600), ("BAY", 25.0, 10.0, 1.0, 45_000),
     ("SMP", 40.0, 16.0, 4.0, 6_000)],
)
def test_congestion_block_matches_fixture(store, code, delay, system, cancel, dep_per_rwy):
    c = metrics.congestion(store, code)
    assert c["delay_rate_pct"] == pytest.approx(delay)
    assert c["system_delay_rate_pct"] == pytest.approx(system)
    assert c["cancel_rate_pct"] == pytest.approx(cancel)
    assert c["departures_per_usable_runway"] == pytest.approx(dep_per_rwy)


def test_congestion_unknown_not_zero_without_delay_data(store):
    c = metrics.congestion(store, "NHV")
    assert c["delay_rate_pct"] is None and c["arrivals"] is None
    assert "unknown, not zero" in c["note"]
    assert c["departures_per_usable_runway"] == pytest.approx(4_200)


@pytest.mark.parametrize("cutoff,pax,all_", [(2000, 33.333, 61.290), (2500, 13.333, 51.613), (3000, 3.333, 45.161)])
def test_long_haul_cargo_hub_bases_differ(store, settings, cutoff, pax, all_):
    lh = metrics.long_haul(store, "NRC", settings)
    row = next(r for r in lh["table"] if r["cutoff_mi"] == cutoff)
    assert row["passenger_flights_pct"] == pytest.approx(pax, abs=0.001)
    assert row["all_flights_pct"] == pytest.approx(all_, abs=0.001)
    assert lh["cargo_share_of_departures_pct"] == pytest.approx(50.0)


def test_long_haul_passenger_only_airport_same_on_both_bases(store, settings):
    lh = metrics.long_haul(store, "LAA", settings)
    assert [r["passenger_flights_pct"] for r in lh["table"]] == pytest.approx([31.818, 31.818, 9.091], abs=0.001)
    assert all(r["passenger_flights_pct"] == r["all_flights_pct"] for r in lh["table"])


def test_zero_seat_gap_is_returned_with_interpretation(store, settings):
    u = metrics.unmet_demand(store, "BAY", settings)
    assert u["seat_gap"] == 0.0
    assert "zero seat gap" in u["seat_gap_interpretation"]
    assert u["load_factor"] == pytest.approx(0.80)


def test_positive_seat_gap(store, settings):
    assert metrics.unmet_demand(store, "PME", settings)["seat_gap"] == pytest.approx(88_941, abs=1)


@pytest.mark.parametrize("code,excess", [("BAY", 7_200), ("SMP", 120), ("LAA", 0), ("DPX", 0), ("NRC", 0),
                                         ("SAA", 0), ("PME", 0), ("PMW", 0), ("SPA", 0), ("SPB", 0)])
def test_excess_delayed_flights_vs_national_median(store, settings, code, excess):
    assert metrics.unmet_demand(store, code, settings)["excess_delayed_flights"] == pytest.approx(excess)


def test_unmet_demand_unknown_parts_for_no_delay_airport(store, settings):
    u = metrics.unmet_demand(store, "NHV", settings)
    assert u["excess_delayed_flights"] is None and u["delay_cause_shares"] is None
    assert u["seat_gap"] == 0.0


def test_delay_cause_shares_sum_to_100_and_are_sorted(store, settings):
    u = metrics.unmet_demand(store, "BAY", settings)
    causes = u["delay_cause_shares"]
    assert sum(c["share_pct"] for c in causes) == pytest.approx(100)
    assert causes[0]["cause"] == "nas_ct" and causes[0]["share_pct"] == pytest.approx(40.0)
    assert "Lower bound" in u["lower_bound_note"]


@pytest.mark.parametrize("code,compound,yoy", [("LAA", 2.808, -4.0), ("SAA", 2.146, 2.222), ("BAY", 0.709, -2.222)])
def test_growth_from_baseline_and_last_year(store, code, compound, yoy):
    g = metrics.growth(store, code)
    assert g["compound_growth_pct_per_year"] == pytest.approx(compound, abs=0.002)
    assert g["passengers_vs_prior_pct"] == pytest.approx(yoy, abs=0.002)


@pytest.mark.parametrize("code,compound,yoy", [("DPX", 3.821, 6.667), ("NRC", 6.884, 24.0), ("BAY", 0.0, -3.226),
                                               ("SPB", -1.588, -5.263)])
def test_departures_growth_from_baseline_and_last_year(store, code, compound, yoy):
    g = metrics.growth(store, code)
    assert g["departures_compound_growth_pct_per_year"] == pytest.approx(compound, abs=0.002)
    assert g["departures_vs_prior_pct"] == pytest.approx(yoy, abs=0.002)


def test_departures_growth_unknown_without_baseline_departures(store):
    am = store.airport_month.copy()
    am.loc[(am["code"] == "DPX") & (am["year"] == store.baseline_year), "departures"] = None
    g = metrics.growth(dataclasses.replace(store, airport_month=am), "DPX")
    assert g["departures_compound_growth_pct_per_year"] is None
    assert g["compound_growth_pct_per_year"] is not None


def _types(ws):
    return {w["type"]: w["severity"] for w in ws}


def test_warnings_per_fixture_case(store, settings):
    assert _types(airport_warnings(store, "NHV", settings)) == {"partial_data": "high"}
    assert _types(airport_warnings(store, "NRC", settings)) == {"cargo_heavy": "medium"}
    assert airport_warnings(store, "LAA", settings) == []
    assert airport_warnings(store, "SMP", settings) == []


def test_warnings_most_severe_first(store, settings):
    ws = airport_warnings(store, "NRC", settings) + airport_warnings(store, "NHV", settings)
    assert [w["severity"] for w in sort_warnings(ws)] == ["high", "medium"]
