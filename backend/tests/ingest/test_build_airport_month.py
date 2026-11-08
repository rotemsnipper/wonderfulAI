import pytest

from backend.ingest.build_airport_month import build_airport_month

T100_HEADER = "origin_airport_id,year,reporting_month,origin_airport_code,total_departures,total_passengers,total_seats,total_freight_lbs\n"
DELAY_HEADER = ("year,month,carrier,airport,arr_flights,arr_del15,carrier_ct,weather_ct,nas_ct,security_ct,"
                "late_aircraft_ct,arr_cancelled,arr_delay\n")
MONTHS = [202601, 202602, 202603]


def t100_row(code, ym, pax=1000):
    y, m = divmod(ym, 100)
    return f'1,"{y}",{y}-{m:02d}-01T00:00:00.000,{code},10,{pax},1200,5\n'


def delay_row(code, ym, carrier, arr=100, del15=20):
    y, m = divmod(ym, 100)
    return f"{y},{m},{carrier},{code},{arr},{del15},5,1.5,8.25,0,5.25,1,900\n"


@pytest.fixture
def built(tmp_path):
    t = T100_HEADER + "".join(t100_row(c, ym) for c in ("LAX", "HVN") for ym in MONTHS)
    d = DELAY_HEADER + "".join(delay_row("LAX", ym, car) for ym in MONTHS for car in ("AA", "DL"))
    d += delay_row("LAX", 202604, "AA")
    (tmp_path / "t100.csv").write_text(t)
    (tmp_path / "delay.csv").write_text(d)
    return build_airport_month(tmp_path / "t100.csv", tmp_path / "delay.csv", start_year=2019)


def test_delay_rows_summed_across_carriers(built):
    lax = built[0][(built[0].code == "LAX") & (built[0].ym == 202601)].iloc[0]
    assert lax.arr_flights == 200 and lax.arr_del15 == 40 and lax.nas_ct == pytest.approx(16.5)
    assert lax.arr_delay_min == 1800 and lax.has_delay_data


def test_airport_without_delay_rows_is_unknown_not_zero(built):
    hvn = built[0][built[0].code == "HVN"]
    assert hvn.passengers.sum() == 3000
    assert not hvn.has_delay_data.any()
    assert hvn.arr_flights.isna().all() and hvn.nas_ct.isna().all()
