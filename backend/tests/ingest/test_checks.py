import json

import pandas as pd
import pytest

from backend.config import load_settings
from backend.ingest import build as build_mod
from backend.ingest.build import BuildFailed, build, window
from backend.ingest.build_routes import CSV_NAME
from backend.ingest.checks import check_duplicate_keys, check_named_airports, check_reconciliation
from backend.tests.ingest.fake_http import zip_bytes

MONTHS = window(202607, 12)


def am_frame(codes=("AAA", "BBB"), months=MONTHS, dep=10, pax=1000):
    return pd.DataFrame([{"code": c, "ym": m, "departures": dep, "passengers": pax} for c in codes for m in months])


def routes_frame(codes=("AAA", "BBB"), months=MONTHS, dep=10):
    return pd.DataFrame([{"code": c, "year": m // 100, "month": m % 100, "dest": "ZZZ", "dest_country": "US",
                          "distance_mi": 500, "class": "F", "departures": dep} for c in codes for m in months])


AIRPORTS = pd.DataFrame({"code": ["AAA", "BBB"], "in_universe": [True, True]})


def test_duplicate_keys_detected():
    am = pd.concat([am_frame(), am_frame(codes=("AAA",), months=[202607])])
    r = check_duplicate_keys({"airport_month": am, "airports": AIRPORTS})
    assert not r["passed"] and r["detail"]["airport_month"] == 1


def test_duplicate_keys_pass_on_clean_tables():
    assert check_duplicate_keys({"airport_month": am_frame(), "routes": routes_frame()})["passed"]


def test_named_airport_missing_fails():
    r = check_named_airports(AIRPORTS, am_frame(), MONTHS, named=["AAA", "CCC"])
    assert not r["passed"] and r["detail"] == {"CCC": "missing from airports"}


def test_named_airport_below_universe_fails():
    airports = pd.DataFrame({"code": ["AAA"], "in_universe": [False]})
    assert not check_named_airports(airports, am_frame(), MONTHS, named=["AAA"])["passed"]


def test_named_airport_with_a_missing_month_fails():
    am = am_frame()
    am = am[~((am.code == "AAA") & (am.ym == 202601))]
    r = check_named_airports(AIRPORTS, am, MONTHS, named=["AAA"])
    assert not r["passed"] and "1 window month" in r["detail"]["AAA"]


def test_reconciliation_passes_when_totals_match():
    assert check_reconciliation(am_frame(), routes_frame(), ["AAA", "BBB"], MONTHS)["passed"]


def test_reconciliation_fails_on_shifted_totals():
    r = check_reconciliation(am_frame(), routes_frame(dep=11), ["AAA"], MONTHS)
    assert not r["passed"] and r["detail"]["AAA"] == {"summary": 120.0, "segment": 132.0}


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


def test_built_files_load_through_the_store(tmp_path, settings):
    from backend.tools.store import load_store
    run(tmp_path, settings)
    store = load_store(tmp_path / "serving")
    assert store.window_label("current") == "2025-08..2026-07"


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


def test_duplicate_rows_in_built_table_fail_build(tmp_path, settings, previous_serving, monkeypatch):
    original = build_mod.build_airport_month

    def with_duplicate(*args, **kwargs):
        df, build_log = original(*args, **kwargs)
        return pd.concat([df, df.head(1)], ignore_index=True), build_log

    monkeypatch.setattr(build_mod, "build_airport_month", with_duplicate)
    with pytest.raises(BuildFailed, match="duplicate_keys"):
        run(tmp_path, settings)
    assert_untouched(previous_serving)


def test_duplicate_raw_rows_fail_build(tmp_path, settings, previous_serving):
    with pytest.raises(BuildFailed, match="duplicate_keys"):
        run(tmp_path, settings, duplicate=True)
    assert_untouched(previous_serving)
