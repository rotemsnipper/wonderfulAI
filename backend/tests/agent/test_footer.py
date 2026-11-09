from backend.agent.footer import collect_warnings, confidence, footer

PERIODS = {"t100_summary": "2025-08..2026-07", "delay_causes": "2025-08..2026-07"}
DEFS = [
    {"name": "delay_rate_pct", "label": "delay rate", "unit": "%", "definition": "share of arrivals 15+ min late",
     "source": "BTS delay causes", "period": "2025-08..2026-07", "proxy_note": None},
    {"name": "seat_gap", "label": "seat gap", "unit": "seats", "definition": "seats needed to reach 85% load factor",
     "source": "T-100", "period": "2025-08..2026-07", "proxy_note": "lower bound of unmet demand"},
]


def env(tool="compare_airports", airports=("LAX", "SNA"), quality=None, warnings=(), proxy=False, definitions=DEFS):
    return {
        "tool": tool, "args": {}, "result": {
            "tool": tool, "inputs": {}, "result": {}, "definitions": list(definitions),
            "warnings": list(warnings),
            "data_quality": quality or {c: {"tier": "full", "confidence": "high", "reason": ""} for c in airports},
            "notes": [], "meta": {"airports": list(airports), "uses_proxy": proxy, "periods": PERIODS,
                                  "score_version": "0.1"},
        },
    }


def test_high_confidence_with_full_direct_data_even_when_a_proxy_is_used():
    assert confidence([env(proxy=True)])[0] == "high"


def test_low_confidence_for_thin_data_in_the_answer_data_whatever_the_text_says():
    q = {"LAX": {"tier": "full"}, "HVN": {"tier": "partial", "confidence": "low"}}
    label, reason = confidence([env(airports=("LAX", "HVN"), quality=q)])
    assert label == "low" and "HVN" in reason


def test_medium_confidence_matches_an_airport_label_with_a_data_warning():
    q = {"LAX": {"tier": "full", "confidence": "high"}, "ANC": {"tier": "full", "confidence": "medium"}}
    label, reason = confidence([env(airports=("LAX", "ANC"), quality=q)])
    assert label == "medium" and "ANC" in reason


def test_ranking_with_weak_airports_is_medium_and_names_them():
    codes = ("BOS", "BDL", "PVD", "PWM", "HVN")
    q = {c: {"tier": "full"} for c in codes} | {"HVN": {"tier": "partial"}}
    label, reason = confidence([env(tool="rank_airports", airports=codes, quality=q)])
    assert label == "medium" and "HVN" in reason


def test_no_data_reply_is_na_not_high():
    assert footer([])["confidence"] == "n/a"
    resolver_only = [env(tool="resolve_airport", airports=("PWM", "PDX"))]
    assert confidence(resolver_only)[0] == "n/a"
    assert confidence([{"tool": "airport_profile", "args": {}, "result": {"error": "unknown", "valid_options": []}}])[0] == "n/a"


def test_footer_has_periods_and_proxy_assumptions():
    f = footer([env()])
    assert f["data_period"] == PERIODS and f["assumptions"] == ["seat_gap: lower bound of unmet demand"]


def test_footer_notes_reused_data():
    e = env() | {"reused": True}
    assert footer([e])["notes"]


def test_footer_adds_live_line_only_when_faa_status_was_used():
    faa = {"tool": "faa_airport_status", "args": {}, "result": {
        "tool": "faa_airport_status", "inputs": {}, "result": {"update_time": "Sun Nov 8 22:27:39 2026 GMT"},
        "meta": {"airports": [], "periods": {"faa_nas_status": "Sun Nov 8 22:27:39 2026 GMT"}}}}
    assert footer([faa])["notes"] == [
        "Live FAA status as of Sun Nov 8 22:27:39 2026 GMT; it changes minute by minute."]
    assert footer([env()])["notes"] == []


def test_warnings_sorted_and_deduplicated():
    ws = [{"airport": "ANC", "type": "cargo_heavy", "severity": "medium", "message": "m"},
          {"airport": "HVN", "type": "partial_data", "severity": "high", "message": "no delay data"}]
    out = collect_warnings([env(warnings=ws), env(warnings=ws[:1])])
    assert [w["airport"] for w in out] == ["HVN", "ANC"]
