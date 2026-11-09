from pathlib import Path

import pytest

from backend.tools import tools
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"
GROWTH_X2 = {"w_passenger_growth": 0.5, "w_flight_growth": 0.5}  # defaults 0.25: growth doubled


@pytest.fixture(autouse=True, scope="module")
def fixture_data():
    tools.configure(load_store(FIXTURE))
    yield
    tools._ctx = None


def rows(r):
    return {x["code"]: x for g in r["result"]["groups"].values() for x in g}


def test_growth_weights_rerank_and_relabel_with_default_rank():
    # Hand-checked in test_reweight.py: NRC 71.67 is first with growth doubled, 5th by default (57.5).
    # Its potential becomes high, and with medium confidence (cargo-heavy) the recommendation is
    # "Investigate further" instead of "Monitor".
    r = tools.call("rank_airports", GROWTH_X2)
    nrc = rows(r)["NRC"]
    assert (nrc["rank"], nrc["default_rank"]) == (1, 5)
    assert nrc["score"]["total_score"] == 71.7
    assert nrc["score"]["recommendation"] == "Investigate further"
    assert r["result"]["weights_used"] == {"passenger_growth": 0.3333, "load_factor": 0.1667,
                                           "flight_growth": 0.3333, "congestion": 0.1667}
    assert sum(r["result"]["weights_used"].values()) == pytest.approx(1, abs=1e-3)
    assert r["result"]["default_weights"]["congestion"] == 0.25
    assert r["inputs"]["w_passenger_growth"] == 0.5


def test_robustness_draws_center_on_custom_weights():
    default = tools.call("rank_airports", {})["result"]["robustness"]["per_airport"]["NRC"]
    custom = tools.call("rank_airports", GROWTH_X2)["result"]["robustness"]["per_airport"]["NRC"]
    assert custom["top_k_share"] > default["top_k_share"]


def test_no_weights_leaves_result_without_weight_keys():
    r = tools.call("rank_airports", {})
    assert "weights_used" not in r["result"]
    assert all("default_rank" not in x for x in rows(r).values())


@pytest.mark.parametrize("args", [
    {"w_congestion": -0.1},
    {"w_congestion": "high"},
    {"w_passenger_growth": 0, "w_load_factor": 0, "w_flight_growth": 0, "w_congestion": 0},
    {"metric": "passengers", "w_congestion": 0.5},
])
def test_invalid_weights_are_rejected(args):
    r = tools.call("rank_airports", args)
    assert set(r) == {"error", "valid_options"}
    assert r["valid_options"]
