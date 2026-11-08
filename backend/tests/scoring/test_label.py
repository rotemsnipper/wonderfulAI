from pathlib import Path

import pytest

from backend.scoring.label import THESIS, confidence, label, scoring_text
from backend.scoring.score import score_all
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"
SETTINGS = {
    "weights": {"passenger_growth": 0.25, "load_factor": 0.25, "flight_growth": 0.25, "congestion": 0.25},
    "label": {"high_min": 65, "medium_min": 50, "strength_min": 70, "weakness_max": 40},
}
CARGO = {"airport": "AAA", "type": "cargo_heavy", "severity": "medium", "message": "cargo"}


def bd(total, pcts=(50, 50, 50, 50), code="AAA"):
    names = list(SETTINGS["weights"])
    return {
        "airport_code": code, "total_score": total,
        "data_tier": "full" if total is not None else "partial",
        "partial_scores": None if total is not None else {"score": 60.0, "components_missing": ["congestion"]},
        "components": [{"name": n, "percentile": p} for n, p in zip(names, pcts)],
    }


@pytest.mark.parametrize("total,warnings,potential,conf,rec", [
    (80, [], "high", "high", "Prioritize for due diligence"),
    (80, [CARGO], "high", "medium", "Investigate further"),
    (55, [], "medium", "high", "Investigate further"),
    (55, [CARGO], "medium", "medium", "Monitor"),
    (30, [CARGO], "low", "medium", "Deprioritize"),
])
def test_recommendation_table_cell(total, warnings, potential, conf, rec):
    out = label(bd(total), warnings, SETTINGS)
    assert (out["potential"], out["confidence"], out["recommendation"]) == (potential, conf, rec)


@pytest.mark.parametrize("total,potential", [(65, "high"), (49.999, "low")])
def test_potential_threshold_edges(total, potential):
    assert label(bd(total), [], SETTINGS)["potential"] == potential


def test_partial_score_is_not_scored_with_low_confidence():
    out = label(bd(None, (90, 90, 90, None)), [], SETTINGS)
    assert out["potential"] == "not scored"
    assert out["confidence"] == "low"
    assert out["recommendation"] == "Not scored: review the available metrics"


def test_strength_and_weakness_edges():
    out = label(bd(55, (70, 69.9, 40, 39.9)), [], SETTINGS)
    assert [s["component"] for s in out["strengths"]] == ["passenger_growth"]
    assert [w["component"] for w in out["weaknesses"]] == ["congestion"]


def test_strengths_strongest_first_and_weaknesses_weakest_first():
    out = label(bd(50, (75, 95, 10, 30)), [], SETTINGS)
    assert [s["percentile"] for s in out["strengths"]] == [95, 75]
    assert [w["percentile"] for w in out["weaknesses"]] == [10, 30]
    assert out["strengths"][0] == {"component": "load_factor", "label": "load factor", "percentile": 95}


def test_partial_airport_still_lists_strengths_from_available_components():
    out = label(bd(None, (90, 10, 80, None)), [], SETTINGS)
    assert [s["component"] for s in out["strengths"]] == ["passenger_growth", "flight_growth"]
    assert [w["component"] for w in out["weaknesses"]] == ["load_factor"]


def test_warnings_for_other_airports_do_not_lower_confidence():
    other = {**CARGO, "airport": "BBB"}
    assert confidence(bd(80), [other])[0] == "high"


def test_fixture_labels_match_readme():
    store = load_store(FIXTURE)
    scores = score_all(store, store.settings)
    nrc_warn = [{"airport": "NRC", "type": "cargo_heavy", "severity": "medium", "message": "x"}]
    dpx = label(scores["DPX"], [], store.settings)
    assert (dpx["potential"], dpx["recommendation"]) == ("high", "Prioritize for due diligence")
    assert label(scores["NRC"], nrc_warn, store.settings)["recommendation"] == "Monitor"
    pme = label(scores["PME"], [], store.settings)
    assert pme["recommendation"] == "Investigate further"
    assert [s["component"] for s in pme["strengths"]] == ["load_factor", "passenger_growth"]
    assert label(scores["NHV"], [], store.settings)["potential"] == "not scored"


def test_scoring_text_uses_configured_weights_and_thresholds():
    s = {**SETTINGS, "label": {"high_min": 70, "medium_min": 45, "strength_min": 80, "weakness_max": 30}}
    text = scoring_text(s)
    assert THESIS in text
    assert "70 or more" in text and "45" in text and "80th" in text and "30th" in text
    assert "passenger growth 25%" in text and "congestion 25%" in text
