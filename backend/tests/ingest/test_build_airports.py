import pandas as pd
import pytest

from backend.config import load_settings
from backend.ingest.build_airports import build_airports

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


def test_sna_has_one_usable_runway_under_3000ft_rule(built):
    sna = row(built[0], "SNA")
    assert sna.runways_total == 2 and sna.runways_usable == 1 and sna.max_runway_ft == 5700


def test_airport_without_scheduled_service_is_not_matched(oa_dir):
    t100 = pd.DataFrame({"code": ["SML"], "airport_id": [1], "passengers_12m": [500]})
    airports, unmatched = build_airports(oa_dir, t100, load_settings())
    assert airports.empty and unmatched == ["SML"]


def test_size_tier_and_universe_from_passengers(built):
    airports = built[0]
    assert row(airports, "LAX").size_tier == "large"
    assert row(airports, "SNA").size_tier == "medium"
    assert row(airports, "HVN").size_tier == "nonhub"
    assert bool(row(airports, "HVN").in_universe)
