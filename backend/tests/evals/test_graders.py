import re

from backend.evals.graders import grade, load_cases
from backend.evals.run_evals import run_all, run_case
from backend.report import sections as S

EXPECTED = {
    "q2": {"LAX": {"delay_rate_pct": {"value": 19.66}}, "SNA": {"delay_rate_pct": {"value": 18.34}}},
    "q3": {"passenger_flights_pct_at_3000": {"value": 2.70}, "all_flights_pct_at_3000": {"value": 29.51},
           "passenger_flights_pct_at_2000": {"value": 15.16}},
    "q4": {"SFO": {"excess_delayed_flights": {"value": 14821.2}}},
}
CASES = {c["id"]: c for c in load_cases()}


def report(kind, mode=S.REPORT, **markdown):
    ids = S.REQUIRED[kind] if mode == S.REPORT else [S.VERDICT, S.STATUS]
    return {"kind": kind, "mode": mode, "subject": kind,
            "sections": [{"id": i, "title": i, "written_by": "code", "markdown": markdown.get(i, "x")} for i in ids]}


def turn(text, status="passed", unverified=(), confidence="high", report=None, trace=(), model=None):
    return {"display_text": text, "check_outcome": {"status": status, "unverified": list(unverified)},
            "footer": {"confidence": confidence}, "tool_trace": list(trace), "report": report,
            "model_messages": [{"role": "assistant", "content": model if model is not None else text}]}


def run(case_id, *texts, reports=None, **kw):
    reports = reports or [None] * len(texts)
    turns = [turn(t, report=r, **kw) for t, r in zip(texts, reports)]
    return grade(CASES[case_id], {"case_id": case_id, "turns": turns}, EXPECTED)


COMPARISON = report("comparison")


GOOD_Q2 = ("Taking LA to mean LAX (Los Angeles International), LAX is slightly more congested than SNA.\n"
           "| Metric | LAX | SNA |\n| Delay rate | 19.7% (LAX) | 18.3% (SNA) |\n"
           "SNA has one usable runway.")


def test_good_answer_passes():
    r = run("q2_lax_sna", GOOD_Q2, reports=[COMPARISON])
    assert r["passed"], r["checks"]


def test_wrong_figure_fails():
    r = run("q2_lax_sna", GOOD_Q2.replace("19.7%", "24.1%"), reports=[COMPARISON])
    assert not r["passed"] and not r["checks"]["figures"][0]


def test_missing_airport_fails():
    r = run("q2_lax_sna", "Los Angeles is more congested; delay 19.7% vs 18.3%; runway context applies.")
    assert not r["checks"]["airports"][0]


def test_missing_required_content_fails():
    r = run("q2_lax_sna", GOOD_Q2.replace("SNA has one usable runway.", ""), reports=[COMPARISON])
    assert not r["checks"]["required"][0]  # no runway context


def test_flagged_numbers_fail_number_check():
    r = run("q2_lax_sna", GOOD_Q2, status="flagged", unverified=["24.1%"], reports=[COMPARISON])
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
    reports = [COMPARISON, None, report("profile"), report("profile"), report("ranking"), None]
    assert run("multi_turn_resume", *texts, reports=reports)["passed"]
    bad = [turn(t, report=r) for t, r in zip(texts, reports)]
    bad[2] = turn(texts[2], status="flagged", unverified=["9,999"])
    assert not grade(case, {"turns": bad}, EXPECTED)["checks"]["number_check"][0]
    texts[3] = "Anchorage long-haul"
    assert not run("multi_turn_resume", *texts, reports=reports)["checks"]["per_turn_airports"][0]


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


# ---- report checks: deliberately broken reports must fail ----

LAX_ROW = {"code": "LAX", "score": {"recommendation": "Monitor"}}
PROFILE_TRACE = [{"tool": "airport_profile", "args": {}, "result": {"result": LAX_ROW}}]


def test_full_report_on_a_follow_up_turn_fails():
    texts = ["Anchorage long-haul (ANC)", "At 2,000 miles: 15.2% (ANC)"]
    ok = run("followup_cutoff", *texts, reports=[report("profile"), report("profile", mode=S.FOLLOW_UP)])
    assert ok["checks"]["modes"][0], ok["checks"]["modes"]
    bad = run("followup_cutoff", *texts, reports=[report("profile"), report("profile")])
    assert not bad["checks"]["modes"][0]


def test_report_missing_a_section_fails():
    broken = report("profile")
    broken["sections"] = [s for s in broken["sections"] if s["id"] != S.WARNINGS]
    r = grade(CASES["q4_sfo_unmet_demand"], {"turns": [turn("SFO", report=broken)]}, EXPECTED)
    assert not r["checks"]["report_sections"][0]


def test_table_label_that_differs_from_the_tool_fails():
    grid = "|  | LAX |\n|---|---|\n| Score (0-100) | 40.0 |\n| Recommendation | {} |"
    good = turn("LAX", report=report("profile", details=grid.format("Monitor"), comparison="LAX"), trace=PROFILE_TRACE)
    bad = turn("LAX", report=report("profile", details=grid.format("Prioritize for due diligence"), comparison="LAX"),
               trace=PROFILE_TRACE)
    case = CASES["q4_sfo_unmet_demand"]
    assert grade(case, {"turns": [good]}, EXPECTED)["checks"]["label_match"][0]
    assert not grade(case, {"turns": [bad]}, EXPECTED)["checks"]["label_match"][0]


def test_profit_claim_in_the_model_text_of_a_report_fails():
    t = turn("LAX", report=report("profile"), model="**Verdict**\nExpanding LAX gives an ROI of 12% (LAX).")
    assert not grade(CASES["q4_sfo_unmet_demand"], {"turns": [t]}, EXPECTED)["checks"]["no_financial_claim"][0]


def test_ranking_verdict_without_the_top_airport_fails():
    trace = [{"tool": "rank_airports", "args": {}, "result": {"result": {"groups": {"small": [{"code": "BGR", "rank": 1}]}}}}]
    good = turn("BGR", report=report("ranking", verdict="BGR leads."), trace=trace)
    bad = turn("BGR", report=report("ranking", verdict="BOS leads."), trace=trace)
    case = CASES["q1_new_england"]
    assert grade(case, {"turns": [good]}, EXPECTED)["checks"]["verdict_names_top"][0]
    assert not grade(case, {"turns": [bad]}, EXPECTED)["checks"]["verdict_names_top"][0]


def test_forbidden_patterns_read_the_model_text_not_the_code_sections():
    display = "**Data period, assumptions and confidence**\n\nConfidence: High (full data)"
    r = grade(CASES["no_footer_in_text"], {"turns": [turn(display, report=COMPARISON, model="LAX and SFO load factor.")]},
              EXPECTED)
    assert r["checks"]["forbidden"][0]
    r = grade(CASES["no_footer_in_text"], {"turns": [turn(display, report=COMPARISON, model="Confidence: high")]}, EXPECTED)
    assert not r["checks"]["forbidden"][0]


def test_answer_cut_off_at_the_token_limit_fails():
    t = turn(GOOD_Q2, report=COMPARISON)
    t["check_outcome"]["cut_off"] = True
    assert not grade(CASES["q2_lax_sna"], {"turns": [t]}, EXPECTED)["checks"]["complete"][0]


def test_comparison_that_skips_a_compared_airport_fails():
    trace = [{"tool": "compare_airports", "args": {}, "result": {"result": {"airports": [{"code": "LAX"}, {"code": "SNA"}]}}}]
    case = CASES["q2_lax_sna"]
    good = turn(GOOD_Q2, report=report("comparison", comparison="LAX is busier than SNA."), trace=trace)
    bad = turn(GOOD_Q2, report=report("comparison", comparison="LAX is busy."), trace=trace)
    assert grade(case, {"turns": [good]}, EXPECTED)["checks"]["comparison_names_airports"][0]
    assert not grade(case, {"turns": [bad]}, EXPECTED)["checks"]["comparison_names_airports"][0]


def test_profile_comparison_is_optional_but_must_name_the_airport_when_written():
    case = CASES["q3_anchorage_long_haul"]
    trace = [{"tool": "airport_profile", "args": {}, "result": {"result": {"code": "ANC"}}}]
    without = report("profile")
    assert grade(case, {"turns": [turn("ANC", report=without, trace=trace)]}, EXPECTED)["checks"]["report_sections"][0]
    wrong = report("profile")
    wrong["sections"].append({"id": S.COMPARISON, "title": "", "written_by": "model", "markdown": "It is busy."})
    assert not grade(case, {"turns": [turn("ANC", report=wrong, trace=trace)]}, EXPECTED)["checks"]["comparison_names_airports"][0]
