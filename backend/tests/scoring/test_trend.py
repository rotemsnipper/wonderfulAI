"""airport_trend on the fixture. Hand-checked from serving/spec/airports_spec.csv (monthly rows run 2024-08..2026-07):
DPX passengers 350,000 a month in 2024-08..2025-07 and 360,000 in 2025-08..2026-07, seats 430,000 throughout.
- passengers vs a year earlier: 360,000 / 350,000 - 1 = +2.857%
- load factor 350/430 = 81.395% then 360/430 = 83.721%: +2.326 points
- seasonal average per calendar month over the 2 full years: (350,000 + 360,000) / 2 = 355,000
- delay rate 520 / 2,600 = 20.0% in every month (no change)
"""
from pathlib import Path

import pytest

from backend.tools import tools
from backend.tools.store import load_store
from backend.tools.trend import airport_trend

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(autouse=True, scope="module")
def fixture_data():
    tools.configure(load_store(FIXTURE))
    yield
    tools._ctx = None


def test_monthly_values_and_changes_vs_the_same_month_a_year_earlier():
    env = airport_trend("DPX", "passengers", 24)
    res = env["result"]
    first, aug = res["months"][0], res["months"][12]
    assert (first["month"], first["value"], first["prior_year_value"], first["change_vs_prior_year"]) == ("2024-08", 350000, None, None)
    assert (aug["month"], aug["value"], aug["prior_year_value"]) == ("2025-08", 360000, 350000)
    assert aug["change_vs_prior_year"] == pytest.approx(2.86, abs=0.005) and aug["change_display"] == "+2.9%"
    s = res["summary"]
    assert s["highest"]["month"] == "2025-08" and s["lowest"]["month"] == "2024-08"
    assert s["first_vs_last_12"]["change"] == pytest.approx(2.86, abs=0.005)
    assert s["seasonal_profile"]["years"] == 2 and s["seasonal_profile"]["months"][0]["value"] == 355000
    assert env["meta"]["airports"] == ["DPX"] and env["meta"]["periods"] == {"t100_summary": "2024-08..2026-07"}


def test_rate_change_is_in_percentage_points():
    res = airport_trend("DPX", "load_factor", 24)["result"]
    assert res["change_unit"] == "percentage points"
    assert res["months"][12]["change_vs_prior_year"] == pytest.approx(2.33, abs=0.005)
    assert res["months"][12]["change_display"] == "+2.3 pp"


def test_delay_metric_before_the_first_delay_month_is_cut_with_a_note():
    env = airport_trend("DPX", "delay_rate", 30)
    assert env["result"]["months_shown"] == 24 and env["result"]["first_month"] == "2024-08"
    assert any("delay data starts 2024-08" in n for n in env["notes"])
    assert env["result"]["months"][0]["value"] == 20.0


def test_airport_without_delay_data_gives_unknown_months_and_the_partial_data_warning():
    env = airport_trend("NHV", "system_delay_rate", 12)
    assert all(m["value"] is None and m["display"] is None for m in env["result"]["months"])
    assert env["result"]["summary"]["unknown_months"] == 12 and env["result"]["summary"]["highest"] is None
    assert [w["type"] for w in env["warnings"]] == ["partial_data"]


def test_traffic_trend_at_an_airport_without_delay_data_is_not_marked_partial():
    env = airport_trend("NHV", "passengers", 12)
    assert all(m["value"] is not None for m in env["result"]["months"])
    assert env["warnings"] == [] and env["data_quality"]["NHV"]["confidence"] == "high"


@pytest.mark.parametrize("args", [{"months": 5}, {"months": 12.5}, {"metric": "revenue"}, {"code": "XXX"}])
def test_bad_input_is_rejected_with_an_error(args):
    assert "error" in airport_trend(**{"code": "DPX", **args})
