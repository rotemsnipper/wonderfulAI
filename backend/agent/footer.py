"""Code-built footer, confidence label and warnings for one answer.

A trace is a list of tool calls: {"tool": name, "args": dict, "result": envelope, "reused": bool (optional)}.
`reused` marks entries carried over from an earlier turn when a follow-up quotes figures without a new
tool call. Envelopes follow the shared tool result envelope (MasterDesign "Schemas"); an error result
has an "error" key and is ignored here.

Confidence rules (fixed, never the model's opinion):
- n/a: no data was used.
- Low: partial or thin data for an airport the answer mentions.
- Medium: a proxy is used or a name was resolved by default; in a ranking, a minority of
  weak airports also gives Medium and the weak airports are named.
- High: otherwise.
"""
import re

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
WEAK_TIERS = {"partial", "thin", "none"}
WEAK_WARNINGS = {"partial_data"}
RANKING_TOOLS = {"rank_airports"}
WARNINGS_CAP = 5


def _envelopes(trace: list[dict]) -> list[dict]:
    return [t for t in trace if isinstance(t.get("result"), dict) and "error" not in t["result"]]


def _data_envelopes(trace: list[dict]) -> list[dict]:
    """Envelopes that carry airport data (resolver-only calls do not count as data used)."""
    return [t for t in _envelopes(trace) if t["result"].get("meta", {}).get("airports") and t["tool"] != "resolve_airport"]


def _codes_in(answer: str) -> set[str]:
    return set(re.findall(r"\b[A-Z]{3}\b", answer or ""))


def _mentioned_airports(trace: list[dict], answer: str) -> set[str]:
    involved = {c for t in _data_envelopes(trace) for c in t["result"]["meta"]["airports"]}
    mentioned = involved & _codes_in(answer)
    return mentioned or involved


def _airport_flags(trace: list[dict]) -> dict[str, set[str]]:
    flags: dict[str, set[str]] = {}
    for t in _data_envelopes(trace):
        env = t["result"]
        for code, q in (env.get("data_quality") or {}).items():
            if q.get("tier") in WEAK_TIERS or q.get("confidence") == "low":
                flags.setdefault(code, set()).add("weak")
        for w in env.get("warnings") or []:
            if w.get("type") in WEAK_WARNINGS:
                flags.setdefault(w.get("airport"), set()).add("weak")
    return flags


def confidence(trace: list[dict], answer: str) -> tuple[str, str]:
    data = _data_envelopes(trace)
    if not data:
        return "n/a", "no data was used for this answer"
    mentioned = _mentioned_airports(trace, answer)
    flags = _airport_flags(trace)
    weak = sorted(c for c in mentioned if "weak" in flags.get(c, set()))
    is_ranking = any(t["tool"] in RANKING_TOOLS for t in data)
    if weak and not (is_ranking and len(weak) * 2 < len(mentioned)):
        return "low", f"partial or thin data for {', '.join(weak)}"
    reasons = []
    if weak:
        reasons.append(f"partial or thin data for a minority of airports ({', '.join(weak)})")
    if any(t["result"].get("meta", {}).get("uses_proxy") for t in data):
        reasons.append("a proxy measure is used")
    if _resolved_by_default(trace, mentioned):
        reasons.append("an airport name was resolved by default")
    if reasons:
        return "medium", "; ".join(reasons)
    return "high", "full data and direct measures for every airport in the answer"


def _resolved_by_default(trace: list[dict], mentioned: set[str]) -> list[str]:
    notes = []
    for t in _envelopes(trace):
        env = t["result"]
        res = env.get("result") or {}
        if (env.get("meta", {}).get("resolved_by_default") or res.get("resolved_by_default")) and res.get("assumption"):
            if not mentioned or res.get("code") in mentioned:
                notes.append(res["assumption"])
    return list(dict.fromkeys(notes))


def _metric_mentioned(defn: dict, answer: str) -> bool:
    text = (answer or "").lower()
    names = {defn.get("name", "").replace("_", " ").lower(), (defn.get("label") or "").lower()}
    names = {n.replace(" pct", "").strip() for n in names if n}
    return any(n and n in text for n in names)


def footer(trace: list[dict], answer: str) -> dict:
    data = _data_envelopes(trace)
    label, reason = confidence(trace, answer)
    mentioned = _mentioned_airports(trace, answer)
    defs = [d for t in data for d in t["result"].get("definitions") or []]
    shown = [d for d in defs if _metric_mentioned(d, answer)] or defs
    unique_defs = list({d.get("name"): d for d in shown}.values())
    periods = {}
    for t in data:
        for source, period in (t["result"].get("meta", {}).get("periods") or {}).items():
            periods.setdefault(source, period)
    assumptions = _resolved_by_default(trace, mentioned)
    assumptions += [f"{d['name']}: {d['proxy_note']}" for d in unique_defs if d.get("proxy_note")]
    notes = []
    if data and all(t.get("reused") for t in data):
        notes.append("Figures reused from an earlier answer in this conversation; no new data was fetched.")
    return {
        "data_period": periods,
        "assumptions": list(dict.fromkeys(assumptions)),
        "definitions": [{k: d.get(k) for k in ("name", "unit", "definition", "source", "period")} for d in unique_defs],
        "confidence": label,
        "confidence_reason": reason,
        "notes": notes,
    }


def collect_warnings(trace: list[dict], cap: int = WARNINGS_CAP) -> list[dict]:
    """All warnings from the trace, deduplicated, most severe first, capped with an 'and N more' line."""
    seen, out = set(), []
    for t in _envelopes(trace):
        for w in t["result"].get("warnings") or []:
            key = (w.get("airport"), w.get("type"))
            if key not in seen:
                seen.add(key)
                out.append(w)
    out.sort(key=lambda w: SEVERITY_ORDER.get(w.get("severity"), 9))
    if len(out) > cap:
        extra = len(out) - cap
        out = out[:cap] + [{"airport": None, "type": "more", "severity": "low", "message": f"and {extra} more"}]
    return out
