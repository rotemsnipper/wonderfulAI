"""Code-built footer, confidence label and warnings for one answer.

A trace is a list of tool calls: {"tool": name, "args": dict, "result": envelope, "reused": bool (optional)}.
`reused` marks entries carried over from an earlier turn when a follow-up quotes figures without a new
tool call. Envelopes follow the shared tool result envelope (MasterDesign "Schemas"); an error result
has an "error" key and is ignored here.

Confidence rules (fixed, never the model's opinion; they read the tool results only, never the answer text,
and agree with each airport's label confidence):
- n/a: no data was used.
- Low: partial or thin data for an airport in the answer's data, outside a ranking.
- Medium: in a ranking, airports with partial data (named); an airport whose label confidence is medium
  (a data warning such as cargo-heavy traffic); or live FAA status.
- High: otherwise. Proxy measures do not lower it; they are listed under assumptions in every report.
"""

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
WEAK_TIERS = {"partial", "thin"}
WEAK_WARNINGS = {"partial_data"}
RANKING_TOOLS = {"rank_airports"}


def _envelopes(trace: list[dict]) -> list[dict]:
    return [t for t in trace if isinstance(t.get("result"), dict) and "error" not in t["result"]]


def _data_envelopes(trace: list[dict]) -> list[dict]:
    """Envelopes that carry airport data (resolver-only calls do not count as data used)."""
    return [t for t in _envelopes(trace) if t["result"].get("meta", {}).get("airports") and t["tool"] != "resolve_airport"]


def _weak_airports(trace: list[dict]) -> set[str]:
    weak = set()
    for t in _data_envelopes(trace):
        env = t["result"]
        for code, q in (env.get("data_quality") or {}).items():
            if q.get("tier") in WEAK_TIERS or q.get("confidence") == "low":
                weak.add(code)
        weak |= {w.get("airport") for w in env.get("warnings") or [] if w.get("type") in WEAK_WARNINGS}
    return weak


def confidence(trace: list[dict]) -> tuple[str, str]:
    data = _data_envelopes(trace)
    if not data:
        return "n/a", "no data was used for this answer"
    weak = sorted(_weak_airports(trace))
    is_ranking = any(t["tool"] in RANKING_TOOLS for t in data)
    if weak and not is_ranking:
        return "low", f"partial or thin data for {', '.join(weak)}"
    reasons = []
    if weak:
        reasons.append(f"partial or thin data for some airports ({', '.join(weak)})")
    warned = sorted({code for t in data for code, q in (t["result"].get("data_quality") or {}).items()
                     if q.get("confidence") == "medium"} - set(weak))
    if warned:
        reasons.append(f"data warnings for {', '.join(warned)}")
    if any(t["tool"] == "faa_airport_status" for t in data):
        reasons.append("live FAA status changes minute by minute and is not checked against our data")
    if reasons:
        return "medium", "; ".join(reasons)
    return "high", "full data for every airport in the answer"


def footer(trace: list[dict]) -> dict:
    data = _data_envelopes(trace)
    label, reason = confidence(trace)
    periods = {}
    for t in data:
        for source, period in (t["result"].get("meta", {}).get("periods") or {}).items():
            periods.setdefault(source, period)
    assumptions = [f"{d['name']}: {d['proxy_note']}" for t in data for d in t["result"].get("definitions") or []
                   if d.get("proxy_note")]
    notes = []
    if data and all(t.get("reused") for t in data):
        notes.append("Figures reused from an earlier answer in this conversation; no new data was fetched.")
    # All envelopes, not only data ones: a feed with nothing listed has no airports but is still live data shown.
    live = next((t for t in _envelopes(trace) if t["tool"] == "faa_airport_status"), None)
    if live:
        notes.append(f"Live FAA status as of {live['result']['result']['update_time']}; it changes minute by minute.")
    return {
        "data_period": periods,
        "assumptions": list(dict.fromkeys(assumptions)),
        "confidence": label,
        "confidence_reason": reason,
        "notes": notes,
    }


def collect_warnings(trace: list[dict]) -> list[dict]:
    """All warnings from the trace, deduplicated, most severe first."""
    seen, out = set(), []
    for t in _envelopes(trace):
        for w in t["result"].get("warnings") or []:
            key = (w.get("airport"), w.get("type"))
            if key not in seen:
                seen.add(key)
                out.append(w)
    return sorted(out, key=lambda w: SEVERITY_ORDER.get(w.get("severity"), 9))
