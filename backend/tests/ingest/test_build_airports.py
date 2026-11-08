import logging

import pandas as pd
import pytest

from backend.config import load_settings
from backend.ingest.build_airports import build_airports, size_tier

AIRPORTS_CSV = """id,ident,type,name,iso_country,iso_region,municipality,iata_code,scheduled_service
1,KLAX,large_airport,Los Angeles International Airport,US,US-CA,Los Angeles,LAX,yes
2,KSNA,large_airport,John Wayne Airport,US,US-CA,Santa Ana,SNA,yes
3,KHVN,medium_airport,Tweed New Haven Airport,US,US-CT,New Haven,HVN,yes
4,KPBI,large_airport,Palm Beach International Airport,US,US-FL,West Palm Beach,PBI,yes
5,TJSJ,large_airport,Luis Munoz Marin International Airport,PR,PR-U-A,San Juan,SJU,yes
6,XOLD,closed,Old Los Angeles Field,US,US-CA,Los Angeles,LAX,no
7,EGLL,large_airport,Heathrow,GB,GB-ENG,London,LHR,yes
8,KSML,small_airport,Small Strip,US,US-AK,Nowhere,SML,no
"""
RUNWAYS_CSV = """id,airport_ident,length_ft,surface,closed,le_ident
1,KLAX,12923,CON,0,06L
2,KLAX,10885,CON,0,06R
3,KLAX,12091,CON,0,07L
4,KLAX,11095,CON,0,07R
5,KSNA,5700,ASP,0,02L
6,KSNA,2887,ASP,0,02R
7,KHVN,5600,ASP,0,02
8,KHVN,3000,ASP,1,14
9,KPBI,10001,ASP,0,10L
10,KPBI,3000,ASP,0,10R
"""
T100 = pd.DataFrame({
    "code": ["LAX", "SNA", "HVN", "PBI", "SJU", "ZZZ"],
    "airport_id": [12892, 14908, 12244, 14027, 14843, 99999],
    "passengers_12m": [36_039_571, 5_527_071, 700_000, 4_000_000, 6_000_000, 300_000],
})


@pytest.fixture
def oa_dir(tmp_path):
    (tmp_path / "airports.csv").write_text(AIRPORTS_CSV)
    (tmp_path / "runways.csv").write_text(RUNWAYS_CSV)
    return tmp_path


@pytest.fixture
def built(oa_dir):
    return build_airports(oa_dir, T100, load_settings())


def row(df, code):
    return df[df.code == code].iloc[0]


def test_contract_columns(built):
    airports, _ = built
    assert list(airports.columns) == ["airport_id", "code", "name", "city", "state", "runways_total",
                                      "runways_usable", "max_runway_ft", "size_tier", "in_universe"]


def test_sna_has_one_usable_runway_under_3000ft_rule(built):
    sna = row(built[0], "SNA")
    assert sna.runways_total == 2 and sna.runways_usable == 1 and sna.max_runway_ft == 5700


def test_lax_counts_four_runways(built):
    lax = row(built[0], "LAX")
    assert lax.runways_total == 4 and lax.runways_usable == 4
    assert lax["name"] == "Los Angeles International Airport"


def test_closed_runway_not_counted(built):
    hvn = row(built[0], "HVN")
    assert hvn.runways_total == 1 and hvn.runways_usable == 1


def test_runway_at_exactly_the_minimum_is_usable(built):
    pbi = row(built[0], "PBI")
    assert pbi.airport_id == 14027 and pbi.state == "FL"
    assert pbi.runways_total == 2 and pbi.runways_usable == 2


def test_airport_without_scheduled_service_is_not_matched(oa_dir):
    t100 = pd.DataFrame({"code": ["SML"], "airport_id": [1], "passengers_12m": [500]})
    airports, unmatched = build_airports(oa_dir, t100, load_settings())
    assert airports.empty and unmatched == ["SML"]


def test_non_us_airports_are_not_matched(built):
    assert "SJU" not in set(built[0].code) and "SJU" in built[1]


def test_unmatched_t100_airport_is_listed_and_logged(oa_dir, caplog):
    with caplog.at_level(logging.INFO):
        airports, unmatched = build_airports(oa_dir, T100, load_settings())
    assert unmatched == ["SJU", "ZZZ"] and "ZZZ" not in set(airports.code)
    assert "2 T-100 airports" in caplog.text


def test_size_tier_and_universe_from_passengers(built):
    airports = built[0]
    assert row(airports, "LAX").size_tier == "large"
    assert row(airports, "SNA").size_tier == "medium"
    assert row(airports, "HVN").size_tier == "nonhub"
    assert bool(row(airports, "HVN").in_universe)


@pytest.mark.parametrize("pax,tier", [(10_000_000, "large"), (9_999_999, "medium"), (1_000_000, "small"), (0, "nonhub")])
def test_size_tier_band_edges(pax, tier):
    assert size_tier(pax, load_settings()["size_bands"]) == tier
