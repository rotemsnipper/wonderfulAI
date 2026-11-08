from pathlib import Path

import pytest

from backend.config import load_settings
from backend.scoring.robustness import robustness
from backend.scoring.score import score_all
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"
WEIGHTS = {"growth": 0.4, "load_factor": 0.35, "congestion": 0.25}
SETTINGS = {"robustness": {"draws": 300, "seed": 7, "concentration": 20, "top_k": 1}}


def bd(code, g, lf, c):
    total = g * WEIGHTS["growth"] + lf * WEIGHTS["load_factor"] + c * WEIGHTS["congestion"]
    comps = [{"name": n, "percentile": v} for n, v in (("growth", g), ("load_factor", lf), ("congestion", c))]
    return {"airport_code": code, "total_score": total, "components": comps}


def test_obvious_winner_is_robust():
    out = robustness([bd("AAA", 100, 100, 100), bd("BBB", 50, 50, 50), bd("CCC", 0, 0, 0)], WEIGHTS, SETTINGS)
    assert out["per_airport"]["AAA"]["verdict"] == "robust"
    assert out["per_airport"]["AAA"]["best_rank"] == out["per_airport"]["AAA"]["worst_rank"] == 1
    assert out["per_airport"]["CCC"]["verdict"] == "rarely in top"
    assert "AAA" in out["summary"] and "stay in the top 1" in out["summary"]


def test_close_pair_is_sensitive():
    # AAA leads on growth, BBB on load factor; totals nearly equal, so the winner depends on weights
    out = robustness([bd("AAA", 100, 0, 50), bd("BBB", 0, 100, 63)], WEIGHTS, SETTINGS)
    assert out["per_airport"]["AAA"]["verdict"] == "sensitive"
    assert out["per_airport"]["BBB"]["verdict"] == "sensitive"
    assert "sensitive" in out["summary"]


def test_same_seed_gives_same_output():
    items = [bd("AAA", 100, 0, 50), bd("BBB", 0, 100, 63), bd("CCC", 40, 40, 40)]
    assert robustness(items, WEIGHTS, SETTINGS) == robustness(items, WEIGHTS, SETTINGS)


def test_runs_on_fixture_scores_with_config():
    settings = load_settings()
    scores = score_all(load_store(FIXTURE), settings)
    out = robustness(list(scores.values()), settings["weights"], settings)
    assert out["draws"] == settings["robustness"]["draws"]
    assert all(1 <= v["best_rank"] <= v["worst_rank"] for v in out["per_airport"].values())
    assert sum(v["top_k_share"] for v in out["per_airport"].values()) == pytest.approx(settings["robustness"]["top_k"])
