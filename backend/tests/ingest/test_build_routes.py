import pytest

from backend.ingest.build_routes import COLUMNS, CSV_NAME, build_routes
from backend.tests.ingest.fake_http import zip_bytes

HEADER = ("DEPARTURES_SCHEDULED,DEPARTURES_PERFORMED,SEATS,PASSENGERS,FREIGHT,DISTANCE,UNIQUE_CARRIER,ORIGIN,"
          "DEST,DEST_COUNTRY,YEAR,MONTH,CLASS\n")
ROWS = [
    # two carriers on the same ANC-SEA passenger route: summed into one row
    "10,10,1500,1200,0,1448,AS,ANC,SEA,US,2026,1,F",
    "5,5,700,600,0,1448,DL,ANC,SEA,US,2026,1,F",
    # cargo to Japan and China
    "0,30,0,0,3000000,3460,5X,ANC,NRT,JP,2026,1,G",
    "0,20,0,0,2000000,5300,FX,ANC,PVG,CN,2026,1,G",
    "0,4,0,0,100000,2600,KH,ANC,ORD,US,2026,1,P",
    # empty row and out-of-window row
    "3,0,0,0,0,1448,AS,ANC,SEA,US,2026,1,F",
    "10,10,1500,1200,0,1448,AS,ANC,SEA,US,2025,7,F",
]


@pytest.fixture
def segment_zip(tmp_path):
    p = tmp_path / "t100_segment_2026.zip"
    p.write_bytes(zip_bytes(CSV_NAME, HEADER + "\n".join(ROWS) + "\n"))
    return p


def test_aggregates_carriers_and_keeps_cargo_classes(segment_zip):
    routes, log = build_routes([segment_zip], start_ym=202508)
    assert list(routes.columns) == COLUMNS
    sea = routes[routes.dest == "SEA"].iloc[0]
    assert sea.departures == 15 and sea.passengers == 1800 and sea.seats == 2200 and sea.distance_mi == 1448
    assert set(routes["class"]) == {"F", "G", "P"}
    assert log["departures_by_class"] == {"F": 15, "G": 50, "P": 4}


def test_international_legs_present_and_counted(segment_zip):
    routes, log = build_routes([segment_zip], start_ym=202508)
    assert set(routes.dest_country) == {"US", "JP", "CN"}
    assert log["international_departures"] == 50


def test_empty_and_out_of_window_rows_dropped(segment_zip):
    routes, log = build_routes([segment_zip], start_ym=202508)
    assert log["empty_rows_dropped"] == 1
    assert (routes.year * 100 + routes.month).min() == 202601


def test_long_haul_shares_from_aggregated_rows(segment_zip):
    routes, _ = build_routes([segment_zip])
    jan = routes[routes.month == 1]
    longhaul_all = jan[jan.distance_mi >= 3000].departures.sum() / jan.departures.sum()
    assert longhaul_all == pytest.approx(50 / 69)


def test_reads_plain_csv_and_normalizes_codes(tmp_path):
    p = tmp_path / "seg.csv"
    p.write_text(HEADER + "1,1,100,90,0,500,AA,pbi,ATL,US,2026,2,F\n")
    routes, _ = build_routes([p])
    assert routes.iloc[0].code == "PBI"
