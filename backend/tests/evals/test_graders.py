import re

from backend.evals.graders import grade, load_cases
from backend.evals.run_evals import run_all, run_case

EXPECTED = {
    "q2": {"LAX": {"delay_rate_pct": {"value": 19.66}}, "SNA": {"delay_rate_pct": {"value": 18.34}}},
    "q3": {"passenger_flights_pct_at_3000": {"value": 2.70}, "all_flights_pct_at_3000": {"value": 29.51},
           "passenger_flights_pct_at_2000": {"value": 15.16}},
    "q4": {"SFO": {"excess_delayed_flights": {"value": 14821.2}}},
}
CASES = {c["id"]: c for c in load_cases()}


def turn(text, status="passed", unverified=(), confidence="high"):
    return {"display_text": text, "check_outcome": {"status": status, "unverified": list(unverified)},
            "footer": {"confidence": confidence}, "tool_trace": []}


def run(case_id, *texts, **kw):
    return grade(CASES[case_id], {"case_id": case_id, "turns": [turn(t, **kw) for t in texts]}, EXPECTED)


GOOD_Q2 = ("Taking LA to mean LAX (Los Angeles International), LAX is slightly more congested than SNA.\n"
           "| Metric | LAX | SNA |\n| Delay rate | 19.7% (LAX) | 18.3% (SNA) |\n"
           "SNA has one usable runway.")


def test_good_answer_passes():
    r = run("q2_lax_sna", GOOD_Q2)
    assert r["passed"], r["checks"]


def test_wrong_figure_fails():
    r = run("q2_lax_sna", GOOD_Q2.replace("19.7%", "24.1%"))
    assert not r["passed"] and not r["checks"]["figures"][0]


def test_missing_airport_fails():
    r = run("q2_lax_sna", "Los Angeles is more congested; delay 19.7% vs 18.3%; runway context applies.")
    assert not r["checks"]["airports"][0]


def test_missing_required_content_fails():
    r = run("q3_anchorage_long_haul", "ANC long-haul share is 2.7% (ANC) at 3,000 miles, 29.5% overall.")
    assert not r["checks"]["required"][0]  # no mention of cargo or passenger basis


def test_flagged_numbers_fail_number_check():
    r = run("q2_lax_sna", GOOD_Q2, status="flagged", unverified=["24.1%"])
    assert not r["passed"] and not r["checks"]["number_check"][0]


def test_missing_footer_fails():
    r = grade(CASES["q2_lax_sna"], {"turns": [{"display_text": GOOD_Q2, "check_outcome": {"status": "passed"}}]}, EXPECTED)
    assert not r["checks"]["footer"][0]


def test_wrong_confidence_label_fails_when_case_expects_one():
    r = run("thin_data_new_haven", "HVN has no delay data reported, so congestion is unknown.", confidence="high")
    assert not r["checks"]["footer"][0]
    assert run("thin_data_new_haven", "HVN has no delay data reported, so congestion is unknown.", confidence="low")["passed"]


def test_multi_turn_checks_every_turn_and_per_turn_airports():
    case = CASES["multi_turn_resume"]
    texts = ["LAX vs SNA delays", "SNA vs LAX runways", "SFO unmet demand", "ANC long-haul", "BOS ranks first",
             "SNA delay rate was 18.3% (SNA)."]
    assert run("multi_turn_resume", *texts)["passed"]
    bad = [turn(t) for t in texts]
    bad[2] = turn(texts[2], status="flagged", unverified=["9,999"])
    assert not grade(case, {"turns": bad}, EXPECTED)["checks"]["number_check"][0]
    texts[3] = "Anchorage long-haul"
    assert not run("multi_turn_resume", *texts)["checks"]["per_turn_airports"][0]


def test_every_case_is_well_formed():
    for c in CASES.values():
        assert c["turns"] and isinstance(c["rules"], list) and c["rules"]
        for pattern in c.get("required", []) + c.get("forbidden", []):
            re.compile(pattern)
    assert sum(bool(len(c["turns"]) >= 5 and c.get("resume_after_turn")) for c in CASES.values()) == 1


def test_run_case_resumes_with_a_new_turn_function():
    calls = []

    def make(tag):
        def fn(store, user, conv, question):
            calls.append((tag, question))
            return turn(f"{question} SNA 18.3% (SNA) delay")
        return fn

    case = CASES["multi_turn_resume"]
    run_case(case, make("first"), lambda: make("resumed"))
    assert [t for t, _ in calls] == ["first"] * 3 + ["resumed"] * 3


def test_run_all_grades_each_case():
    results = run_all([CASES["out_of_scope_cost"]], lambda *a: turn("I cannot estimate costs.", confidence="n/a"),
                      expected=EXPECTED)
    assert results[0]["passed"]
