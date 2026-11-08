"""M2-I: the four sample questions through the real tools on the real serving data, compared with the
independent recompute (scripts/recompute/expected.json). Skipped when either file set is missing."""
import json

import pytest

from backend.config import REPO_ROOT
from backend.scoring.metrics import DELAY_CAUSES
from backend.tools import tools
from backend.tools.store import load_store

SERVING = REPO_ROOT / "data" / "serving"
EXPECTED = REPO_ROOT / "scripts" / "recompute" / "expected.json"
TOL = 1e-6

pytestmark = pytest.mark.skipif(not (SERVING / "manifest.json").exists() or not EXPECTED.exists(),
                                reason="real serving data or expected.json not built")


@pytest.fixture(autouse=True, scope="module")
def real_data():
    tools.configure(load_store(SERVING))
    yield
    tools._ctx = None


@pytest.fixture(scope="module")
def expected():
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


def resolved(query):
    r = tools.call("resolve_airport", {"query": query})["result"]
    assert r["status"] == "resolved", r
    return r["code"]


def test_q1_new_england_ranking_is_usable():
    r = tools.call("rank_airports", {"region": "new_england"})
    rows = [row for rows in r["result"]["groups"].values() for row in rows]
    assert {"BOS", "PWM", "BGR"} <= {row["code"] for row in rows}
    assert r["result"]["robustness"]["summary"].startswith("Robustness:")
    assert "HVN" in {x["code"] for x in r["result"]["not_ranked"]}


def test_q1_new_england_departures_growth_matches(expected):
    r = tools.call("rank_airports", {"region": "new_england"})
    codes = [row["code"] for rows in r["result"]["groups"].values() for row in rows]
    codes += [x["code"] for x in r["result"]["not_ranked"]]
    assert set(codes) == set(expected["q1"])
    for code in codes:
        m = tools.call("airport_profile", {"code": code})["result"]["metrics"]
        for key in ("departures_compound_growth_pct_per_year", "departures_vs_prior_pct"):
            assert m[key] == pytest.approx(expected["q1"][code][key]["value"], abs=1e-3), (code, key)


def test_q1_new_england_labels_never_rate_partial_data():
    r = tools.call("rank_airports", {"region": "new_england"})
    rows = [row for rows in r["result"]["groups"].values() for row in rows]
    assert all(row["score"]["potential"] != "not scored" for row in rows)
    hvn = tools.call("airport_profile", {"code": "HVN"})["result"]["score"]
    assert hvn["potential"] == "not scored" and hvn["recommendation"].startswith("Not scored")


def test_q2_names_resolve_and_figures_match(expected):
    codes = [resolved("LA"), resolved("Santa Ana")]
    assert codes == ["LAX", "SNA"]
    r = tools.call("compare_airports", {"codes": codes})
    by = {a["code"]: a for a in r["result"]["airports"]}
    for code in codes:
        e, m = expected["q2"][code], by[code]["metrics"]
        for key in ("delay_rate_pct", "system_delay_rate_pct", "cancel_rate_pct", "load_factor",
                    "departures_per_usable_runway"):
            assert m[key] == pytest.approx(e[key]["value"], abs=1e-3), (code, key)
        assert by[code]["runways_usable"] == e["runways_usable"]["value"]


def test_q3_anchorage_long_haul_matches(expected):
    r = tools.call("airport_profile", {"code": resolved("Anchorage")})
    lh = r["result"]["long_haul"]
    for row in lh["table"]:
        c = row["cutoff_mi"]
        assert row["passenger_flights_pct"] == pytest.approx(expected["q3"][f"passenger_flights_pct_at_{c}"]["value"], abs=0.01)
        assert row["all_flights_pct"] == pytest.approx(expected["q3"][f"all_flights_pct_at_{c}"]["value"], abs=0.01)
    assert lh["cargo_share_of_departures_pct"] == pytest.approx(expected["q3"]["cargo_share_of_departures_pct"]["value"], abs=0.01)


def test_q4_sfo_unmet_demand_matches(expected):
    r = tools.call("airport_profile", {"code": "SFO"})
    u, e = r["result"]["unmet_demand"], expected["q4"]["SFO"]
    assert r["result"]["metrics"]["load_factor"] == pytest.approx(e["load_factor"]["value"], abs=1e-4)
    assert u["seat_gap"] == pytest.approx(e["seat_gap"]["value"], abs=1)
    assert u["national_median_delay_rate_pct"] == pytest.approx(e["national_median_delay_rate_pct"]["value"], abs=0.01)
    assert u["excess_delayed_flights"] == pytest.approx(e["excess_delayed_flights"]["value"], abs=1)
    label_to_key = {label: key for key, label in DELAY_CAUSES.items()}
    shares = {label_to_key[x["cause"]]: x["share_pct"] for x in u["delay_cause_shares"]}
    for key, value in e["delay_cause_shares_pct"]["value"].items():
        assert shares[key] == pytest.approx(value, abs=0.1), key
