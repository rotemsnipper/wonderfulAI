from pathlib import Path

import pytest

from backend.agent.footer import collect_warnings, footer
from backend.agent.safeguards import unverified_numbers
from backend.agent.session import pool_from_trace
from backend.report import sections as S
from backend.report.render import build_report, split_model_text
from backend.tools import tools
from backend.tools.store import load_store

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "serving"
MODEL_TEXT = ("**Comparison**\nDPX leads on both sides.\n\n**Verdict**\nDPX leads the list.\n\n"
              "**Why**\nDPX has the highest score and full planes.")
PASSED = {"status": "passed", "unverified": []}


@pytest.fixture(autouse=True, scope="module")
def fixture_data():
    tools.configure(load_store(FIXTURE))
    yield
    tools._ctx = None


def call(name, args):
    return {"tool": name, "args": args, "result": tools.call(name, args)}


def build(trace, text=MODEL_TEXT, question="Which airports should expand their terminals?", last=None, outcome=PASSED):
    return build_report(trace, text, question, footer(trace, text), collect_warnings(trace), outcome, last)


def ids(report):
    return [s.id for s in report.sections]


def test_ranking_report_puts_details_first_then_the_model_text_then_fixed_sections():
    r = build([call("rank_airports", {})])
    assert r.kind == "ranking" and r.mode == S.REPORT
    assert ids(r) == [S.DETAILS, S.COMPARISON, S.VERDICT, S.WHY, S.SPECIFIC, S.ROBUSTNESS, S.WARNINGS, S.ASSUMPTIONS,
                      S.STILL_NEEDED]
    details = r.section(S.DETAILS).markdown
    assert details.splitlines()[0] == "|  | DPX | SMP | PME |"  # the top three in detail
    assert "*Large*" in details and "*Nonhub*" in details and "Investigate further" in details
    assert "NHV" in r.section(S.SPECIFIC).markdown
    assert "500 weight scenarios" in r.section(S.ROBUSTNESS).markdown
    assert r.markdown.startswith("**The airports**")


def test_comparison_details_have_location_runways_and_labels_and_the_block_has_differences():
    r = build([call("compare_airports", {"codes": ["LAA", "SAA"]})], question="Should LAA or SAA expand?")
    assert r.kind == "comparison" and S.ROBUSTNESS not in ids(r)
    details = r.section(S.DETAILS).markdown
    assert "Lakeshore, CA" in details and "| Usable runways | 4 of 4 | 1 of 2 |" in details and "Deprioritize" in details
    specific = r.section(S.SPECIFIC).markdown
    assert "System delay rate: LAA minus SAA" in specific and "different size tiers" in specific


def test_profile_shows_percentiles_and_only_the_half_the_question_asks_about():
    trace = [call("airport_profile", {"code": "NRC"})]
    long_haul = build(trace, question="What share of NRC flights are long-haul?")
    assert "Percentile among covered airports" in long_haul.section(S.DETAILS).markdown
    assert long_haul.section(S.SPECIFIC).title == "Long-haul share"
    assert "45.2%" in long_haul.section(S.SPECIFIC).markdown and "Seat gap" not in long_haul.section(S.SPECIFIC).markdown
    assert long_haul.suggestions == ["What is the unmet demand at NRC?"]
    unmet = build(trace, question="What is the unmet demand at NRC?")
    assert unmet.section(S.SPECIFIC).title == "Unmet demand" and "Lower bound" in unmet.section(S.SPECIFIC).markdown
    both = build(trace, question="Should NRC expand?")
    assert both.section(S.SPECIFIC).title == "Long-haul share and unmet demand"


def test_airport_without_delay_data_shows_unknown_and_not_scored():
    r = build([call("airport_profile", {"code": "NHV"})], question="Is NHV worth expanding?")
    assert "unknown" in r.section(S.SPECIFIC).markdown
    assert "not scored" in r.section(S.DETAILS).markdown.lower()


def test_factual_question_leaves_out_scores_strengths_and_the_comparison():
    r = build([call("compare_airports", {"codes": ["LAA", "SAA"]})], question="Which is busier and how delayed is it?")
    details = r.section(S.DETAILS).markdown
    assert not r.investment and S.COMPARISON not in ids(r) and S.VERDICT in ids(r)
    assert "Score (0-100)" not in details and "Recommendation" not in details and "strengths" not in details
    assert "Passengers" in details and r.section(S.SPECIFIC) is not None


def test_ranking_by_one_metric_shows_that_metric_and_no_robustness():
    r = build([call("rank_airports", {"metric": "load_factor"})], question="Which airports have the fullest planes?")
    assert S.ROBUSTNESS not in ids(r) and "load factor" in r.section(S.DETAILS).markdown.lower()


@pytest.mark.parametrize("name,args", [
    ("rank_airports", {}),
    ("compare_airports", {"codes": ["LAA", "SAA", "NHV"]}),
    ("airport_profile", {"code": "NRC"}),
])
def test_every_number_in_code_sections_comes_from_the_tool_result(name, args):
    trace = [call(name, args)]
    r = build(trace)
    code = "\n".join(s.markdown for s in r.sections if s.written_by == S.CODE) + "\n" + "\n".join(r.suggestions)
    assert unverified_numbers(code, pool_from_trace(trace)) == []


def test_same_subject_again_gives_a_short_follow_up():
    first = build([call("airport_profile", {"code": "NRC"})], question="Profile NRC")
    r = build([call("airport_profile", {"code": "NRC", "long_haul_cutoff_mi": 2000})], question="And at 2,000 miles?",
              last=first.subject)
    assert r.mode == S.FOLLOW_UP and ids(r) == [S.SPECIFIC, S.COMPARISON, S.VERDICT, S.WHY, S.STATUS]
    assert r.section(S.SPECIFIC).title == "Long-haul share" and r.suggestions == []
    last = build([call("compare_airports", {"codes": ["LAA", "SAA", "DPX"]})]).subject
    assert build([call("compare_airports", {"codes": ["DPX", "LAA"]})], last=last).mode == S.FOLLOW_UP


def test_new_airports_a_new_kind_or_a_full_report_request_give_a_report():
    last = build([call("compare_airports", {"codes": ["LAA", "SAA"]})]).subject
    assert build([call("compare_airports", {"codes": ["LAA", "DPX"]})], last=last).mode == S.REPORT
    assert build([call("compare_airports", {"codes": ["LAA", "SAA"]})], question="Give me the full report",
                 last=last).mode == S.REPORT
    last = build([call("rank_airports", {})]).subject
    assert build([call("airport_profile", {"code": "DPX"})], last=last).mode == S.REPORT


def test_suggestions_name_airports_from_the_result():
    assert build([call("rank_airports", {})]).suggestions == ["Compare DPX and SMP.", "Give me a profile of DPX."]
    assert build([call("compare_airports", {"codes": ["LAA", "SAA"]})]).suggestions == [
        "Give me a profile of LAA.", "Give me a profile of SAA."]


def test_no_data_tool_means_no_report_and_the_last_data_tool_decides_the_kind():
    assert build([], text="Which Portland do you mean?") is None
    assert build([call("resolve_airport", {"query": "Lakeshore"})]) is None
    assert build([call("airport_profile", {"code": "XXX"})]) is None
    assert build([call("rank_airports", {}), call("airport_profile", {"code": "DPX"})]).subject == "profile:DPX"


def test_split_model_text_accepts_heading_styles_and_falls_back_to_verdict():
    for text in ("**Comparison**\nC.\n\n**Verdict**\nA.\n\n**Why**\nB.", "Comparison: C.\nVerdict: A.\nWhy:\nB.",
                 "## Comparison\nC.\n## Verdict\nA.\n## Why\nB."):
        assert split_model_text(text) == {"comparison": "C.", "verdict": "A.", "why": "B."}, text
    assert split_model_text("NRC is cargo-heavy.") == {"verdict": "NRC is cargo-heavy."}


def test_flagged_numbers_are_noted_after_the_model_part():
    r = build([call("airport_profile", {"code": "NRC"})], outcome={"status": "flagged", "unverified": ["40.2%"]})
    assert "could not be matched to our data: 40.2%" in r.section(S.WHY).markdown


def test_still_needed_and_advice_only_for_investment_questions():
    trace = [call("airport_profile", {"code": "NRC"})]
    assert S.ADVICE_LINE in build(trace, question="Should NRC expand?").section(S.STILL_NEEDED).markdown
    assert S.STILL_NEEDED not in ids(build(trace, question="What is the long-haul share at NRC?"))
