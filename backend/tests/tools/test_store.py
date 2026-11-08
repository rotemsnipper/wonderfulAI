import shutil
from pathlib import Path

import pandas as pd
import pytest

from backend.tools.store import SchemaError, load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture
def store():
    return load_store(FIXTURE)


def test_loads_fixture_tables_and_manifest(store):
    assert len(store.airports) == 12
    assert store.manifest["row_counts"]["airport_month"] == len(store.airport_month)


def test_windows_match_fixture_periods(store):
    assert store.window_label("current") == "2025-08..2026-07"
    assert store.window_label("prior") == "2024-08..2025-07"
    assert store.window_label("baseline") == "2019-01..2019-12"
    assert len(store.window("current")) == 12


def test_years_since_baseline_is_79_months(store):
    assert store.years_since_baseline() == pytest.approx(79 / 12)


def test_month_selector_filters_window_and_codes(store):
    laa = store.months("current", ["LAA"])
    assert len(laa) == 12
    assert laa["passengers"].sum() == 36_000_000


def test_routes_selector(store):
    assert store.routes_in("current", ["NRC"])["departures"].sum() == 7_440


def test_unknown_window_raises(store):
    with pytest.raises(ValueError):
        store.window("next")


def test_missing_column_raises_clear_error(tmp_path):
    for f in FIXTURE.iterdir():
        if f.is_file():
            shutil.copy(f, tmp_path / f.name)
    df = pd.read_parquet(tmp_path / "routes.parquet").drop(columns=["distance_mi"])
    df.to_parquet(tmp_path / "routes.parquet", index=False)
    with pytest.raises(SchemaError, match="routes.*distance_mi"):
        load_store(tmp_path)


def test_missing_table_raises(tmp_path):
    with pytest.raises(SchemaError, match="airports"):
        load_store(tmp_path)


def test_settings_come_from_the_serving_folder(store):
    assert store.settings["window_months"] == 12 and store.window_months == 12


@pytest.mark.parametrize("name", ["manifest.json", "settings.yaml"])
def test_missing_support_file_fails_instead_of_falling_back_to_config(tmp_path, name):
    for f in FIXTURE.iterdir():
        if f.is_file() and f.name != name:
            shutil.copy(f, tmp_path / f.name)
    with pytest.raises(SchemaError, match=name):
        load_store(tmp_path)
