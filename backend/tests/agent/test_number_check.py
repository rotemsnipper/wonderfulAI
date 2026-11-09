from backend.agent.safeguards import extract_numbers, misattributed_numbers, numbers_in_data, unverified_numbers

TOOL_RESULT = {
    "result": {
        "LAX": {"delay_rate_pct": 19.660028, "system_delay_rate_pct": 4.957, "passengers": 36_039_571,
                "load_factor": 0.82195, "departures_per_usable_runway": 66_796.75, "passengers_vs_prior_pct": -4.0},
        "SNA": {"delay_rate_pct": 18.3438, "passengers": 5_527_071, "display": {"passengers": "5.5 million"}},
        "ratio_lax_to_sna_passengers": 6.52,
    },
    "inputs": {"codes": ["LAX", "SNA"], "cutoff_mi": 3000},
}
POOL = numbers_in_data(TOOL_RESULT)


def check(answer, allowed=""):
    return unverified_numbers(answer, POOL, allowed)


def test_forms_seen_in_answers_are_accepted():
    for answer in [
        "LAX has a delay rate of 19.7% (LAX).",
        "About 20% of LAX arrivals are delayed.",
        "LAX handled 36.0 million passengers.",
        "LAX handled 36 million passengers.",
        "LAX handled 36,039,571 passengers.",
        "Load factor at LAX is 82.2%.",
        "LAX runs 66,797 departures per usable runway.",
        "LAX runs about 67,000 departures per usable runway.",
        "LAX is 6.5 times SNA by passengers.",
    ]:
        assert check(answer) == [], answer


def test_copied_display_value_is_accepted():
    assert check("SNA served 5.5 million passengers.") == []


def test_rejected_invented_number():
    assert check("LAX has a delay rate of 23.4%.") == ["23.4%"]


def test_rounding_beyond_half_last_digit_is_rejected():
    assert check("LAX has a delay rate of 19.5%.") == ["19.5%"]


def test_round_number_capped_at_two_and_a_half_percent():
    # 70,000 is 4.8% away from 66,797; its last non-zero digit alone would allow +/-5,000
    assert check("LAX runs about 70,000 departures per usable runway.") == ["70,000"]


def test_explicit_sign_mismatch_is_rejected():
    assert check("LAX passengers changed +4% vs the prior year.") == ["+4%"]
    assert check("LAX system delay rate is -4.96%.") == ["-4.96%"]


def test_unsigned_number_matches_negative_change():
    assert check("LAX passengers fell 4% vs the prior year.") == []
    assert check("LAX passengers changed -4% vs the prior year.") == []


def test_exempt_tokens_are_not_checked():
    for answer in [
        "Data for 2025-08 to 2026-07, baseline 2019.",
        "Source: BTS T-100 and A320 fleet.",
        "LAX ranks 1st of 184; SNA is 9th of 30.",
        "SNA is ranked #3 and in the top 5.",
        "Scores use a 0-100 scale; a score out of 100.",
        "Two airports, 4 runways, 12 months.",
        "1. LAX\n2. SNA\n",
    ]:
        assert check(answer) == [], answer


def test_tool_inputs_are_in_the_pool():
    assert check("At the 3,000-mile cutoff...") == []


def test_numbers_from_the_question_are_allowed():
    assert check("You asked about 2,500 miles.", allowed="and at 2,500 miles?") == []
    assert check("You asked about 2,500 miles.") == ["2,500"]


def test_extract_scale_words_and_percent():
    got = {w: v for w, v, _, _ in extract_numbers("1.2 billion, 45k, 7 thousand, 3.5%")}
    assert got == {"1.2 billion": 1.2e9, "45k": 45_000, "7 thousand": 7_000, "3.5%": 3.5}


def test_numbers_in_data_reads_nested_strings_and_scales_fractions():
    pool = numbers_in_data({"a": [0.25, {"b": "about 3.1 million"}], "flag": True})
    assert {0.25, 25.0, 3.1e6} <= pool
    assert 1.0 not in pool


PAIR_TRACE = [{"tool": "compare_airports", "args": {"codes": ["LAX", "SNA"]}, "result": {
    "result": {"airports": [{"code": "LAX", "display": {"delay_rate_pct": "19.7%"}},
                            {"code": "SNA", "display": {"delay_rate_pct": "18.3%"}}],
               "differences": [{"a": "LAX", "b": "SNA", "difference": 1.4}], "national_median_pct": 21.7},
    "meta": {"airports": ["LAX", "SNA"]}}}]


def test_number_moved_to_the_wrong_airport_is_caught():
    assert misattributed_numbers("SNA has a delay rate of 19.7% (SNA).", PAIR_TRACE) == ["19.7%"]
    assert misattributed_numbers("LAX has a delay rate of 19.7% (LAX).", PAIR_TRACE) == []
    assert misattributed_numbers("LAX is 1.4 points above SNA.", PAIR_TRACE) == []  # two airports: not checked
    assert misattributed_numbers("SNA is below the national median of 21.7% (SNA).", PAIR_TRACE) == []


def test_prompt_threshold_beside_an_airport_passes_only_in_a_threshold_sentence():
    trace = [{**PAIR_TRACE[0], "result": {**PAIR_TRACE[0]["result"],
                                          "definitions": [{"definition": "high potential at 65 or more"}]}}]
    prompt = "Potential is high at 65 or more."
    assert misattributed_numbers("LAX scores 65 (LAX).", trace, "", prompt) == ["65"]
    assert misattributed_numbers("LAX is below the 65 high-potential threshold (LAX).", trace, "", prompt) == []
