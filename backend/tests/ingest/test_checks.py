import json

import pytest

from backend.config import load_settings
from backend.ingest.build import BuildFailed, build, window
from backend.ingest.build_routes import CSV_NAME
from backend.tests.ingest.fake_http import zip_bytes

MONTHS = window(202607, 12)


# ---- end-to-end build on a tiny raw directory ----

def write_raw(raw, *, duplicate=False, drop_bbb=False, shift_segment=False):
    (raw / "bts_t100_summary").mkdir(parents=True)
    (raw / "bts_delay_causes").mkdir()
    (raw / "bts_t100_segment").mkdir()
    (raw / "ourairports").mkdir()
    codes = ["AAA"] if drop_bbb else ["AAA", "BBB"]
    t = ["origin_airport_id,year,reporting_month,origin_airport_code,total_departures,total_passengers,total_seats,total_freight_lbs"]
    for i, c in enumerate(codes):
        for m in MONTHS:
            t.append(f"{100 + i},{m // 100},{m // 100}-{m % 100:02d}-01T00:00:00.000,{c},10,30000,40000,0")
    if duplicate:
        t.append(t[1])
    (raw / "bts_t100_summary" / "t100_by_origin.csv").write_text("\n".join(t) + "\n")
    d = ["year,month,carrier,airport,arr_flights,arr_del15,carrier_ct,weather_ct,nas_ct,security_ct,late_aircraft_ct,arr_cancelled,arr_delay"]
    d += [f"{m // 100},{m % 100},AA,{c},100,20,5,1,8,0,6,1,900" for c in codes for m in MONTHS]
    (raw / "bts_delay_causes" / "Airline_Delay_Cause.csv").write_text("\n".join(d) + "\n")
    dep = 11 if shift_segment else 10
    s = ["DEPARTURES_PERFORMED,SEATS,PASSENGERS,FREIGHT,DISTANCE,ORIGIN,DEST,DEST_COUNTRY,YEAR,MONTH,CLASS"]
    s += [f"{dep},40000,30000,0,500,{c},ZZZ,US,{m // 100},{m % 100},F" for c in codes for m in MONTHS]
    (raw / "bts_t100_segment" / "t100_segment_2026.zip").write_bytes(zip_bytes(CSV_NAME, "\n".join(s) + "\n"))
    (raw / "ourairports" / "airports.csv").write_text(
        "ident,type,name,iso_country,iso_region,municipality,iata_code,scheduled_service\n"
        "KAAA,large_airport,Alpha,US,US-CA,Alpha City,AAA,yes\nKBBB,large_airport,Beta,US,US-MA,Beta City,BBB,yes\n")
    (raw / "ourairports" / "runways.csv").write_text(
        "airport_ident,length_ft,surface,closed,le_ident\nKAAA,9000,ASP,0,01\nKBBB,9000,ASP,0,01\n")


@pytest.fixture
def settings():
    return {**load_settings(), "universe_min_passengers_12m": 100_000}


def run(tmp_path, settings, **raw_opts):
    raw = tmp_path / "raw"
    write_raw(raw, **raw_opts)
    return build(raw, tmp_path / "serving", settings, named=["AAA", "BBB"])


def test_clean_build_writes_serving_files_and_manifest(tmp_path, settings):
    manifest = run(tmp_path, settings)
    out = tmp_path / "serving"
    for f in ("airports.parquet", "airport_month.parquet", "routes.parquet", "manifest.json", "settings.yaml"):
        assert (out / f).exists()
    import yaml
    assert yaml.safe_load((out / "settings.yaml").read_text()) == settings  # the settings this build used
    on_disk = json.loads((out / "manifest.json").read_text())
    assert on_disk["window"]["current"] == "2025-08..2026-07"
    assert on_disk["checks"] == {"duplicate_keys": "pass", "named_airports": "pass", "reconciliation": "pass"}
    assert manifest["row_counts"]["airport_month"] == 24
    assert set(on_disk["periods"]) == {"t100_summary", "delay_causes", "t100_segment"}


@pytest.fixture
def previous_serving(tmp_path):
    out = tmp_path / "serving"
    out.mkdir()
    (out / "airports.parquet").write_bytes(b"previous build")
    (out / "manifest.json").write_text('{"previous": true}')
    return out


def assert_untouched(serving):
    assert (serving / "airports.parquet").read_bytes() == b"previous build"
    assert json.loads((serving / "manifest.json").read_text()) == {"previous": True}
    assert not (serving / "routes.parquet").exists()


@pytest.mark.parametrize("opts,failed", [
    ({"drop_bbb": True}, "named_airports"),
    ({"shift_segment": True}, "reconciliation"),
])
def test_corrupted_input_fails_build_without_touching_serving_files(tmp_path, settings, previous_serving, opts, failed):
    with pytest.raises(BuildFailed, match=failed):
        run(tmp_path, settings, **opts)
    assert_untouched(previous_serving)


def test_duplicate_raw_rows_fail_build(tmp_path, settings, previous_serving):
    with pytest.raises(BuildFailed, match="duplicate_keys"):
        run(tmp_path, settings, duplicate=True)
    assert_untouched(previous_serving)
