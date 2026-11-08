from backend.agent.footer import collect_warnings, confidence, footer

PERIODS = {"t100_summary": "2025-08..2026-07", "delay_causes": "2025-08..2026-07"}
DEFS = [
    {"name": "delay_rate_pct", "label": "delay rate", "unit": "%", "definition": "share of arrivals 15+ min late",
     "source": "BTS delay causes", "period": "2025-08..2026-07", "proxy_note": None},
    {"name": "seat_gap", "label": "seat gap", "unit": "seats", "definition": "seats needed to reach 85% load factor",
     "source": "T-100", "period": "2025-08..2026-07", "proxy_note": "lower bound of unmet demand"},
]


def env(tool="compare_airports", airports=("LAX", "SNA"), quality=None, warnings=(), proxy=False, definitions=DEFS,
        resolved=None):
    result = {}
    if resolved:
        result = {"code": resolved[0], "resolved_by_default": True, "assumption": resolved[1]}
    return {
        "tool": tool, "args": {}, "result": {
            "tool": tool, "inputs": {}, "result": result, "definitions": list(definitions),
            "warnings": list(warnings),
            "data_quality": quality or {c: {"tier": "full", "confidence": "high", "reason": ""} for c in airports},
            "notes": [], "meta": {"airports": list(airports), "uses_proxy": proxy, "periods": PERIODS,
                                  "score_version": "0.1", "resolved_by_default": bool(resolved)},
        },
    }


def test_high_confidence_with_full_direct_data():
    assert confidence([env()], "LAX delay rate 19.7% vs SNA 18.3%.")[0] == "high"


def test_low_confidence_for_thin_data_on_mentioned_airport():
    q = {"LAX": {"tier": "full"}, "HVN": {"tier": "partial", "confidence": "low"}}
    label, reason = confidence([env(airports=("LAX", "HVN"), quality=q)], "HVN has no delay data.")
    assert label == "low" and "HVN" in reason


def test_weak_airport_not_mentioned_does_not_lower_confidence():
    q = {"LAX": {"tier": "full"}, "HVN": {"tier": "partial"}}
    assert confidence([env(airports=("LAX", "HVN"), quality=q)], "LAX delay rate is 19.7%.")[0] == "high"


def test_medium_confidence_for_proxy():
    label, reason = confidence([env(proxy=True)], "LAX seat gap is 0.")
    assert label == "medium" and "proxy" in reason


def test_medium_confidence_for_resolved_by_default():
    trace = [env(tool="resolve_airport", airports=("LAX",), resolved=("LAX", "'LA' was taken to mean LAX")), env()]
    assert confidence(trace, "LAX vs SNA")[0] == "medium"


def test_ranking_with_minority_of_weak_airports_is_medium_and_names_them():
    codes = ("BOS", "BDL", "PVD", "PWM", "HVN")
    q = {c: {"tier": "full"} for c in codes} | {"HVN": {"tier": "partial"}}
    label, reason = confidence([env(tool="rank_airports", airports=codes, quality=q)], "BOS, BDL, PVD, PWM and HVN.")
    assert label == "medium" and "HVN" in reason


def test_ranking_with_majority_of_weak_airports_is_low():
    codes = ("BOS", "HVN", "ORH")
    q = {"BOS": {"tier": "full"}, "HVN": {"tier": "partial"}, "ORH": {"tier": "thin"}}
    assert confidence([env(tool="rank_airports", airports=codes, quality=q)], "BOS HVN ORH")[0] == "low"


def test_no_data_reply_is_na_not_high():
    assert confidence([], "I can't help with ticket prices.") == ("n/a", "no data was used for this answer")
    resolver_only = [env(tool="resolve_airport", airports=("PWM", "PDX"))]
    assert confidence(resolver_only, "Which Portland do you mean?")[0] == "n/a"
    assert confidence([{"tool": "airport_profile", "args": {}, "result": {"error": "unknown", "valid_options": []}}], "x")[0] == "n/a"


def test_footer_lists_only_mentioned_definitions():
    f = footer([env()], "LAX has a delay rate of 19.7%.")
    assert [d["name"] for d in f["definitions"]] == ["delay_rate_pct"]
    assert f["data_period"] == PERIODS and f["confidence"] == "high"
    assert f["assumptions"] == []


def test_footer_falls_back_to_all_definitions_and_lists_proxy_assumption():
    f = footer([env()], "Here is what I found for LAX.")
    assert {d["name"] for d in f["definitions"]} == {"delay_rate_pct", "seat_gap"}
    assert any("lower bound" in a for a in f["assumptions"])


def test_footer_carries_resolved_by_default_note():
    trace = [env(tool="resolve_airport", airports=("LAX",), resolved=("LAX", "'LA' was taken to mean LAX")), env()]
    assert "'LA' was taken to mean LAX" in footer(trace, "LAX delay rate 19.7%")["assumptions"]


def test_footer_notes_reused_data():
    e = env() | {"reused": True}
    assert footer([e], "As before, LAX delay rate is 19.7%.")["notes"]


def test_footer_for_no_data_reply():
    f = footer([], "That is outside what I can answer.")
    assert f["confidence"] == "n/a" and f["data_period"] == {} and f["definitions"] == []


def test_warnings_sorted_deduplicated_and_capped():
    ws = [{"airport": f"A{i}", "type": "cargo_heavy", "severity": "medium", "message": "m"} for i in range(6)]
    ws += [{"airport": "HVN", "type": "partial_data", "severity": "high", "message": "no delay data"}]
    trace = [env(warnings=ws), env(warnings=ws[:2])]
    out = collect_warnings(trace, cap=5)
    assert out[0]["airport"] == "HVN"
    assert len(out) == 6 and out[-1] == {"airport": None, "type": "more", "severity": "low", "message": "and 2 more"}


def test_warnings_under_cap_have_no_more_line():
    w = [{"airport": "ANC", "type": "cargo_heavy", "severity": "medium", "message": "m"}]
    assert collect_warnings([env(warnings=w)]) == w
