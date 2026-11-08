import math

import pytest

from backend.scoring import formulas as f


def test_load_factor_is_passengers_over_seats():
    assert f.load_factor(36_000_000, 43_200_000) == pytest.approx(0.833333, rel=1e-5)


@pytest.mark.parametrize("pax,seats", [(None, 100), (100, 0)])
def test_load_factor_unknown_when_inputs_missing_or_zero_seats(pax, seats):
    assert f.load_factor(pax, seats) is None


def test_growth_pct_negative_change():
    assert f.growth_pct(36_000_000, 37_500_000) == pytest.approx(-4.0)


def test_growth_pct_unknown_without_prior():
    assert f.growth_pct(100, 0) is None
    assert f.growth_pct(100, None) is None


@pytest.mark.parametrize(
    "ratio,expected", [(1.2, 2.808)]
)
def test_compound_growth_matches_fixture_readme(ratio, expected):
    assert f.compound_growth_pct(ratio * 1000, 1000, 79 / 12) == pytest.approx(expected, abs=0.001)


def test_compound_growth_unknown_without_baseline():
    assert f.compound_growth_pct(100, None, 6.0) is None
    assert f.compound_growth_pct(100, 0, 6.0) is None
    assert f.compound_growth_pct(100, 50, 0) is None


def test_rate_pct_basic():
    assert f.rate_pct(38_400, 192_000) == pytest.approx(20.0)


NRC_ROUTES = [
    (1500, 200, "F"), (2200, 60, "F"), (2700, 30, "F"), (3200, 10, "F"),
    (3500, 150, "G"), (5500, 100, "G"), (1800, 40, "G"), (2600, 10, "L"), (4000, 20, "P"),
]


@pytest.mark.parametrize("cutoff,pax_only,all_flights", [(3000, 3.333, 45.161)])
def test_long_haul_share_differs_by_basis_for_cargo_hub(cutoff, pax_only, all_flights):
    assert f.long_haul_share(NRC_ROUTES, cutoff, ["F"]) == pytest.approx(pax_only, abs=0.001)
    assert f.long_haul_share(NRC_ROUTES, cutoff, ["F", "G", "L", "P"]) == pytest.approx(all_flights, abs=0.001)


def test_long_haul_share_unknown_when_no_departures_on_basis():
    assert f.long_haul_share([(3000, 10, "G")], 2000, ["F"]) is None
    assert f.long_haul_share([], 2000, ["F"]) is None


def test_percentile_ranks_single_value_and_empty():
    assert f.percentile_ranks({"a": 5}) == {"a": 100.0}
    assert f.percentile_ranks({"a": None}) == {"a": None}


def test_weighted_score_sums_weighted_components():
    w = {"growth": 0.4, "load_factor": 0.35, "congestion": 0.25}
    assert f.weighted_score({"growth": 100, "load_factor": 50, "congestion": 0}, w) == pytest.approx(57.5)


def test_weighted_score_none_if_any_component_missing():
    w = {"growth": 0.5, "congestion": 0.5}
    assert f.weighted_score({"growth": 80, "congestion": None}, w) is None
    assert f.weighted_score({"growth": 80}, w) is None


def test_seat_gap_positive_case_from_fixture():
    assert f.seat_gap(1_320_000, 1_464_000, 0.85) == pytest.approx(88_941.18, abs=0.01)


def test_seat_gap_unknown_without_seats():
    assert f.seat_gap(100, None, 0.85) is None


def test_excess_delayed_flights_against_median():
    assert f.excess_delayed_flights(36_000, 144_000, 19.375) == pytest.approx(8_100)


def test_excess_delayed_flights_unknown_without_delay_data():
    assert f.excess_delayed_flights(None, None, 19.375) is None
    assert f.excess_delayed_flights(100, 1000, None) is None


def test_median_odd_even_and_missing():
    assert f.median([3, 1, 2]) == 2
    assert f.median([4, 1, 3, 2]) == 2.5
    assert f.median([None, 5, math.nan]) == 5
    assert f.median([None]) is None
