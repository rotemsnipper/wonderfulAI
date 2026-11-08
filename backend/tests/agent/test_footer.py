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


def test_ranking_with_weak_airports_is_medium_and_names_them():
    codes = ("BOS", "BDL", "PVD", "PWM", "HVN")
    q = {c: {"tier": "full"} for c in codes} | {"HVN": {"tier": "partial"}}
    label, reason = confidence([env(tool="rank_airports", airports=codes, quality=q)], "BOS, BDL, PVD, PWM and HVN.")
    assert label == "medium" and "HVN" in reason


def test_no_data_reply_is_na_not_high():
    assert footer([], "I can't help with ticket prices.")["confidence"] == "n/a"
    resolver_only = [env(tool="resolve_airport", airports=("PWM", "PDX"))]
    assert confidence(resolver_only, "Which Portland do you mean?")[0] == "n/a"
    assert confidence([{"tool": "airport_profile", "args": {}, "result": {"error": "unknown", "valid_options": []}}], "x")[0] == "n/a"


def test_footer_has_periods_and_proxy_assumptions():
    f = footer([env()], "LAX has a delay rate of 19.7%.")
    assert f["data_period"] == PERIODS and f["assumptions"] == ["seat_gap: lower bound of unmet demand"]


def test_footer_notes_reused_data():
    e = env() | {"reused": True}
    assert footer([e], "As before, LAX delay rate is 19.7%.")["notes"]


def test_warnings_sorted_and_deduplicated():
    ws = [{"airport": "ANC", "type": "cargo_heavy", "severity": "medium", "message": "m"},
          {"airport": "HVN", "type": "partial_data", "severity": "high", "message": "no delay data"}]
    out = collect_warnings([env(warnings=ws), env(warnings=ws[:1])])
    assert [w["airport"] for w in out] == ["HVN", "ANC"]
