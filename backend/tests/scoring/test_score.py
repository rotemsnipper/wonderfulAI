from pathlib import Path

import pytest

from backend.config import load_settings
from backend.scoring.score import ranked, score_all
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(scope="module")
def settings():
    return load_settings(FIXTURE / "settings.yaml")


@pytest.fixture(scope="module")
def scores(settings):
    return score_all(load_store(FIXTURE), settings)


def test_universe_excludes_airport_below_threshold(scores):
    assert "TNY" not in scores
    assert len(scores) == 11


def test_contributions_sum_to_total_score(scores):
    for b in scores.values():
        if b["total_score"] is not None:
            assert sum(c["contribution"] for c in b["components"]) == pytest.approx(b["total_score"])


def test_no_delay_airport_gets_partial_score_not_total(scores):
    b = scores["NHV"]
    assert b["total_score"] is None
    assert b["data_tier"] == "partial"
    assert b["partial_scores"]["components_missing"] == ["congestion"]
    assert sum(b["effective_weights"].values()) == pytest.approx(1.0)
    used = [c for c in b["components"] if c["contribution"] is not None]
    assert sum(c["contribution"] for c in used) == pytest.approx(b["partial_scores"]["score"])


def test_scoring_is_deterministic(settings):
    store = load_store(FIXTURE)
    assert score_all(store, settings) == score_all(store, settings)


def test_ranked_lists_only_full_scores_best_first(scores):
    r = ranked(scores)
    assert {b["airport_code"] for b in r} == {c for c, b in scores.items() if b["data_tier"] == "full"}
    assert [b["total_score"] for b in r] == sorted((b["total_score"] for b in r), reverse=True)


@pytest.mark.parametrize("code,passenger,flight,total", [("DPX", 70.0, 70.556, 70.278)])
def test_side_scores_match_fixture_hand_calculation(scores, code, passenger, flight, total):
    b = scores[code]
    assert b["passenger_score"] == pytest.approx(passenger, abs=0.001)
    assert b["flight_score"] == pytest.approx(flight, abs=0.001)
    assert b["total_score"] == pytest.approx(total, abs=0.001)


def test_no_delay_airport_has_passenger_side_but_no_flight_side(scores):
    b = scores["NHV"]
    assert b["passenger_score"] == pytest.approx(30.0)
    assert b["flight_score"] is None
    fg = next(c for c in b["components"] if c["name"] == "flight_growth")
    assert fg["percentile"] == pytest.approx(90.0)
