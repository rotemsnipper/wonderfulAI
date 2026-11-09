from pathlib import Path

import pytest

from backend.config import load_settings
from backend.scoring.score import ranked, reweight, score_all
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"
# Both growth weights doubled, then normalized: 2, 1, 2, 1 over 6.
GROWTH_X2 = {"passenger_growth": 1 / 3, "load_factor": 1 / 6, "flight_growth": 1 / 3, "congestion": 1 / 6}


@pytest.fixture(scope="module")
def settings():
    return load_settings()


@pytest.fixture(scope="module")
def scores(settings):
    return score_all(load_store(FIXTURE), settings)


def test_default_weights_reproduce_score_all(scores, settings):
    assert reweight(scores, settings["weights"], settings) == scores


def test_doubling_growth_weights_moves_cargo_hub_to_first(scores, settings):
    # Hand-checked from the fixture README percentiles, total = (2 pg + lf + 2 fg + cg) / 6:
    # NRC (200 + 30 + 200 + 0) / 6 = 71.67, DPX 411.11 / 6 = 68.52, SMP 410 / 6 = 68.33, PME 63.70,
    # SPA 58.52, LAA 56.85. Default order is DPX, SMP, PME, LAA, NRC, SPA, so NRC goes from 5th to 1st
    # and SPA passes LAA.
    out = reweight(scores, GROWTH_X2, settings)
    assert [b["airport_code"] for b in ranked(out)][:6] == ["NRC", "DPX", "SMP", "PME", "SPA", "LAA"]
    assert out["NRC"]["total_score"] == pytest.approx(71.667, abs=0.001)
    # side scores: passenger side (2 x 100 + 30) / 3 = 76.67; flight side (2 x 100 + 0) / 3 = 66.67
    assert out["NRC"]["passenger_score"] == pytest.approx(76.667, abs=0.001)
    assert out["NRC"]["flight_score"] == pytest.approx(66.667, abs=0.001)
    assert sum(c["contribution"] for c in out["NRC"]["components"]) == pytest.approx(out["NRC"]["total_score"])


def test_partial_score_uses_custom_weights_for_available_components(scores, settings):
    # NHV lacks congestion: pg 50, lf 10, fg 90 over weights 2, 1, 2 -> (100 + 10 + 180) / 5 = 58.0
    p = reweight(scores, GROWTH_X2, settings)["NHV"]["partial_scores"]
    assert p["score"] == pytest.approx(58.0)
