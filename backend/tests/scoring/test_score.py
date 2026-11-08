from pathlib import Path

import pytest

from backend.config import load_settings
from backend.scoring.score import ranked, score_all
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"


@pytest.fixture(scope="module")
def settings():
    return load_settings()


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


def test_effective_weights_equal_config_for_full_scores(scores, settings):
    assert scores["LAA"]["effective_weights"] == settings["weights"]
    assert scores["LAA"]["data_tier"] == "full"


def test_no_delay_airport_gets_partial_score_not_total(scores):
    b = scores["NHV"]
    assert b["total_score"] is None
    assert b["data_tier"] == "partial"
    assert b["partial_scores"]["components_missing"] == ["congestion"]
    assert sum(b["effective_weights"].values()) == pytest.approx(1.0)
    used = [c for c in b["components"] if c["contribution"] is not None]
    assert sum(c["contribution"] for c in used) == pytest.approx(b["partial_scores"]["score"])


def test_missing_component_not_ranked_at_bottom(scores):
    pcts = [next(c for c in b["components"] if c["name"] == "congestion")["percentile"] for b in scores.values()]
    present = sorted(p for p in pcts if p is not None)
    assert len(present) == 10 and present[0] == 0.0 and present[-1] == 100.0


def test_load_factor_percentile_highest_for_pme(scores):
    lf = next(c for c in scores["PME"]["components"] if c["name"] == "load_factor")
    assert lf["raw_value"] == pytest.approx(1_320_000 / 1_464_000)
    assert lf["percentile"] == 100.0


def test_scoring_is_deterministic(settings):
    store = load_store(FIXTURE)
    assert score_all(store, settings) == score_all(store, settings)


def test_ranked_lists_only_full_scores_best_first(scores):
    r = ranked(scores)
    assert {b["airport_code"] for b in r} == {c for c, b in scores.items() if b["data_tier"] == "full"}
    assert [b["total_score"] for b in r] == sorted((b["total_score"] for b in r), reverse=True)


def test_score_version_is_carried(scores, settings):
    assert all(b["score_version"] == settings["score_version"] for b in scores.values())
