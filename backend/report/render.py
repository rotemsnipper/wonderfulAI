"""Build the report for one turn from its tool trace and the model's Comparison, Verdict and Why.

Order: the airports' details (code), then the model's comparison, verdict and why, then the question-specific
block and the fixed sections (code). Code writes every table from the tool results, using the tools' display
values (or the tools' own rounding via `fmt`), so no number in a code section can disagree with the data.

Mode: a full report for a new subject or when the question asks for one; a short follow-up (one answering
block, the model's text, one warnings-and-confidence line) when the turn has the same kind as the
conversation's last report and only airports already in it (for a ranking: the same filters). No data tool
means no report (None). A full comparison or profile for a question that is not about investing is factual: it
leaves out the scores, strengths and weaknesses and the model's Comparison, so the answer is not buried.
"""
import re

from backend.report import sections as S
from backend.report.sections import CODE, MODEL, Report, Section
from backend.tools.tools import fmt

HEADING = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?(?:\*\*)?\s*(comparison|verdict|why)\s*(?:\*\*)?\s*:?(?:\*\*)?[ \t]*")
DETAIL_TOP = 3
UNKNOWN = "unknown"
PERIOD_NAMES = {"t100_summary": "Traffic (T-100)", "delay_causes": "Delays (BTS delay causes)",
                "t100_segment": "Routes and distances (T-100 segment)", "prior_window": "Prior-year window",
                "baseline": "Growth baseline year"}
CONGESTION_METRICS = [("delay_rate_pct", "Arrivals delayed 15+ min"), ("system_delay_rate_pct", "System delay rate"),
                      ("cancel_rate_pct", "Cancellation rate"), ("departures_per_usable_runway", "Departures per usable runway")]
# detail rows: (display key, label, score component whose percentile is shown in a profile)
CAPACITY_ROWS = [
    ("passengers", "Passengers", None),
    ("compound_growth_pct_per_year", "Passenger growth a year since {baseline}", "passenger_growth"),
    ("passengers_vs_prior_pct", "Passengers vs prior year", None),
    ("load_factor", "Load factor", "load_factor"),
    ("departures", "Departures", None),
    ("departures_compound_growth_pct_per_year", "Flight growth a year since {baseline}", "flight_growth"),
    ("departures_vs_prior_pct", "Departures vs prior year", None),
    ("system_delay_rate_pct", "System delay rate", "congestion"),
]


def split_model_text(text: str) -> dict[str, str]:
    """The model's Comparison, Verdict and Why by heading; without any heading the whole text is the verdict."""
    text = (text or "").strip()
    marks = [m for m in HEADING.finditer(text)]
    if not marks:
        return {S.VERDICT: text} if text else {}
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].strip()
        if body:
            out[m.group(1).lower()] = body
    return out


def build_report(trace: list[dict], model_text: str, question: str, footer: dict, warnings: list[dict],
                 outcome: dict, last_subject: str | None) -> Report | None:
    entry = _last_data_call(trace)
    if entry is None:
        return None
    kind = S.KINDS[entry["tool"]]
    env = entry["result"]
    subject = _subject(kind, env)
    follow_up = _same_subject(subject, last_subject) and not S.FULL_REPORT_REQUEST.search(question or "")
    model = _model_sections(model_text, outcome)
    investment = kind == "ranking" or (kind != "trend" and bool(S.INVESTMENT_QUESTION.search(question or "")))

    rows = _airports(kind, env)
    halves = _profile_halves(question) if kind == "profile" else None
    code = {
        S.DETAILS: _details(kind, env, rows, investment),
        S.SPECIFIC: _specific(kind, env, rows, halves),
        S.ROBUSTNESS: _robustness(env),
    }
    if follow_up:
        block_id = S.FOLLOW_UP_SECTION[kind]
        out = [_code_section(kind, block_id, code[block_id], halves)] if code[block_id] else []
        out += model
        out.append(Section(S.STATUS, S.TITLES[S.STATUS], CODE, _status_line(warnings, footer)))
        return Report(kind, S.FOLLOW_UP, subject, out)

    code[S.WARNINGS] = _warnings(warnings)
    code[S.ASSUMPTIONS] = _assumptions(env, footer)
    if S.INVESTMENT_QUESTION.search(question or ""):
        code[S.STILL_NEEDED] = "\n".join(f"- {x}" for x in S.STILL_NEEDED_ITEMS) + f"\n\n{S.ADVICE_LINE}"
    by_id = {s.id: s for s in model if investment or s.id != S.COMPARISON}
    out = []
    for sid in S.ORDER:
        if sid in S.MODEL_SECTIONS:
            out += [by_id[sid]] if sid in by_id else []
        elif code.get(sid):
            out.append(_code_section(kind, sid, code[sid], halves))
    return Report(kind, S.REPORT, subject, out, _suggestions(kind, env, rows, halves), investment)


def _model_sections(model_text: str, outcome: dict) -> list[Section]:
    parts = split_model_text(model_text)
    if outcome.get("status") == "flagged":
        last = next(sid for sid in reversed(S.MODEL_SECTIONS) if sid in parts) if parts else S.VERDICT
        note = "Note: these numbers could not be matched to our data: " + ", ".join(outcome["unverified"]) + "."
        parts[last] = f"{parts[last]}\n\n{note}" if parts.get(last) else note
    return [Section(sid, S.TITLES[sid], MODEL, parts[sid]) for sid in S.MODEL_SECTIONS if parts.get(sid)]


# ---------- choosing ----------

def _last_data_call(trace: list[dict]) -> dict | None:
    for t in reversed(trace or []):
        if t.get("tool") in S.KINDS and isinstance(t.get("result"), dict) and "error" not in t["result"]:
            return t
    return None


def _same_subject(subject: str, last: str | None) -> bool:
    """Same kind, and for airport subjects every airport was already in the last report (a subset)."""
    if not last or subject.split(":")[0] != last.split(":")[0]:
        return False
    if subject.startswith(("ranking:", "trend:")):
        return subject == last
    return set(subject.split(":", 1)[1].split(",")) <= set(last.split(":", 1)[1].split(","))


def _subject(kind: str, env: dict) -> str:
    if kind == "ranking":
        inputs = env.get("inputs") or {}
        return "ranking:" + ",".join(f"{k}={inputs.get(k)}" for k in ("region", "state", "size_tier", "metric"))
    if kind == "trend":
        return f"trend:{env['result']['code']}:{env['result']['metric']}"
    return f"{kind}:" + ",".join(sorted(env["meta"]["airports"]))


def _profile_halves(question: str) -> tuple[bool, bool]:
    """(long-haul, unmet demand): the half of the profile block the question asks about; both when unclear."""
    lh, unmet = bool(S.LONG_HAUL_QUESTION.search(question or "")), bool(S.UNMET_QUESTION.search(question or ""))
    return (True, True) if lh == unmet else (lh, unmet)


def _code_section(kind: str, sid: str, markdown: str, halves) -> Section:
    if sid == S.SPECIFIC:
        title = S.PROFILE_TITLES[halves] if kind == "profile" else S.SPECIFIC_TITLES[kind]
    elif sid == S.DETAILS:
        title = S.DETAILS_TITLES.get(kind, S.TITLES[sid])
    else:
        title = S.TITLES[sid]
    return Section(sid, title, CODE, markdown)


def _airports(kind: str, env: dict) -> list[dict]:
    """One dict per airport shown, in display order: basics, display metrics, score block, rank."""
    res = env["result"]
    if kind == "ranking":
        return [{**r, "display_metrics": r["metrics"]} for rows in res["groups"].values() for r in rows]
    if kind == "comparison":
        return [{**a, "display_metrics": a["display"]} for a in res["airports"]]
    if kind == "trend":
        return [res]
    return [{**res, "display_metrics": res["display"]}]


# ---------- details ----------

def _num(v) -> str:
    return "n/a" if v is None else f"{v:.1f}"


def _total(score: dict) -> str:
    if score.get("total_score") is not None:
        return score["display"]
    if score.get("partial_score") is not None:
        return f"not scored (partial {score['partial_score']:.1f})"
    return "not scored"


def _recommendation(score: dict) -> str:
    return score.get("recommendation") or score.get("note") or "n/a"


def _details(kind: str, env: dict, rows: list[dict], investment: bool) -> str:
    res = env["result"]
    if kind == "trend":
        return _month_table(res)
    if kind == "ranking" and res.get("weights_used"):
        names = {"passenger_growth": "passenger growth", "load_factor": "load factor",
                 "flight_growth": "flight growth", "congestion": "congestion"}
        used = ", ".join(f"{names.get(k, k)} {v * 100:.0f}%" for k, v in res["weights_used"].items())
        return f"*Custom weights: {used} (default: equal weights).*\n\n" + _details(kind, {**env, "result": {
            k: v for k, v in res.items() if k != "weights_used"}}, rows, investment)
    if kind == "ranking" and res["metric"] != "score":
        label = next((d["label"] for d in env.get("definitions") or []), res["ranked_by"])
        head = f"| Rank | Airport | Size tier | {label} |\n|---|---|---|---|"
        return "\n".join([head] + [f"| {r['rank']} | {r['name']} ({r['code']}) | {r['size_tier']} | {r['display']} |"
                                   for r in rows])
    shown = sorted(rows, key=lambda r: r["rank"])[:DETAIL_TOP] if kind == "ranking" else rows
    out = _detail_grid(env, shown, kind == "profile", investment) + (_strengths(shown) if investment else "")
    if kind == "ranking":
        out += "\n\n*All ranked airports, by size tier*\n\n" + _score_tables(res, rows)
    return out


def _detail_grid(env: dict, rows: list[dict], percentiles: bool, scores_shown: bool) -> str:
    baseline = (env.get("meta", {}).get("periods") or {}).get("baseline", "baseline")
    codes = [r["code"] for r in rows]
    head = ["", *codes] + (["Percentile among covered airports"] if percentiles else [])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def line(label, cells, pct=""):
        lines.append(f"| {label} | " + " | ".join(cells) + (f" | {pct}" if percentiles else "") + " |")

    line("Airport", [r["name"] for r in rows])
    line("Location", [f"{r['city']}, {r['state']}" for r in rows])
    line("Size tier", [r["size_tier"] for r in rows])
    line("Usable runways", [f"{r['runways_usable']} of {r['runways_total']}" for r in rows])
    scores = [r.get("score") or {} for r in rows]
    if scores_shown:
        line("Score (0-100)", [_total(s) for s in scores])
        line("Passenger side", [_num(s.get("passenger_score")) for s in scores])
        line("Flight side", [_num(s.get("flight_score")) for s in scores])
        line("Recommendation", [_recommendation(s) for s in scores])
    for key, label, component in CAPACITY_ROWS:
        pct = ""
        if percentiles and component:
            p = ((scores[0].get("components") or {}).get(component) or {}).get("percentile")
            pct = UNKNOWN if p is None else f"{p:.1f}"
        line(label.format(baseline=baseline), [r["display_metrics"].get(key) or UNKNOWN for r in rows], pct)
    return "\n".join(lines)


def _strengths(rows: list[dict]) -> str:
    notes = []
    for r in rows:
        score = r.get("score") or {}
        if "strengths" not in score:
            continue
        s = ", ".join(f"{x['label']} (percentile {x['percentile']:.1f})" for x in score["strengths"]) or "none"
        w = ", ".join(f"{x['label']} (percentile {x['percentile']:.1f})" for x in score["weaknesses"]) or "none"
        notes.append(f"- **{r['code']}**: strengths: {s}; weaknesses: {w}")
    return "\n\n" + "\n".join(notes) if notes else ""


def _score_tables(res: dict, rows: list[dict]) -> str:
    head = ["Rank", "Airport", "Score (0-100)", "Passenger side", "Flight side", "Recommendation"]
    header = "| " + " | ".join(head) + " |\n|" + "---|" * len(head)

    def line(r):
        s = r.get("score") or {}
        cells = [str(r["rank"]), f"{r['name']} ({r['code']})", _total(s), _num(s.get("passenger_score")),
                 _num(s.get("flight_score")), _recommendation(s)]
        return "| " + " | ".join(cells) + " |"

    parts = []
    for tier, members in res["groups"].items():
        codes = {m["code"] for m in members}
        parts.append(f"*{tier.capitalize()}*\n\n" + "\n".join([header] + [line(r) for r in rows if r["code"] in codes]))
    return "\n\n".join(parts)


# ---------- question-specific block ----------

def _specific(kind: str, env: dict, rows: list[dict], halves) -> str:
    res = env["result"]
    if kind == "ranking":
        out = []
        for x in res["not_ranked"]:
            reason = x["reason"].removeprefix("partial score: ")
            extra = f" (partial score {x['partial_score']:.1f})" if x.get("partial_score") is not None else ""
            out.append(f"- **{x['code']}**: {reason}{extra}")
        if res.get("list_was_cut"):
            out.append("- Not shown (list cut at the per-tier cap): " + ", ".join(res["cut_airports"]))
        return "\n".join(out)
    if kind == "comparison":
        return _congestion(env, rows)
    if kind == "trend":
        return _trend_summary(env)
    long_haul, unmet = halves
    return "\n\n".join(([_long_haul(res)] if long_haul else []) + ([_unmet(res)] if unmet else []))


def _congestion(env: dict, rows: list[dict]) -> str:
    res = env["result"]
    codes = [r["code"] for r in rows]
    lines = ["| Metric | " + " | ".join(codes) + " |", "|---|" + "---|" * len(codes)]
    for key, label in CONGESTION_METRICS:
        lines.append(f"| {label} | " + " | ".join(r["display_metrics"].get(key) or UNKNOWN for r in rows) + " |")
    diffs = []
    for d in res["differences"]:
        if d["metric"] not in dict(CONGESTION_METRICS) or d.get("difference") is None:
            continue
        unit = " pp" if d["difference_unit"] == "percentage points" else ""
        diff = f"{d['difference']:+.1f}{unit}" if unit else f"{d['difference']:+,}"
        ratio = f", ratio {d['ratio']:.2f}" if d.get("ratio") is not None else ""
        diffs.append(f"- {dict(CONGESTION_METRICS)[d['metric']]}: {d['a']} minus {d['b']} = {diff}{ratio}")
    out = "\n".join(lines)
    if diffs:
        out += "\n\n" + "\n".join(diffs)
    out += "".join(f"\n- {r['code']}: {r['delay_note']}" for r in rows if r.get("delay_note"))
    out += "".join(f"\n- {n}" for n in env.get("notes") or [])
    return out


def _pct(v) -> str:
    return UNKNOWN if v is None else fmt("pct", v)


def _long_haul(res: dict) -> str:
    lh = res["long_haul"]
    lines = ["| Cutoff | Scheduled passenger flights | All flights (incl. cargo and charter) |", "|---|---|---|"]
    for x in lh["table"]:
        mark = " (headline)" if x["cutoff_mi"] == lh["headline_cutoff_mi"] else ""
        lines.append(f"| {x['cutoff_mi']:,} miles{mark} | {_pct(x['passenger_flights_pct'])} | {_pct(x['all_flights_pct'])} |")
    lines.append("")
    lines.append(f"- Basis: {lh['basis']}.")
    if lh.get("cargo_share_of_departures_pct") is not None:
        lines.append(f"- Cargo share of departures: {_pct(lh['cargo_share_of_departures_pct'])}.")
    return "\n".join(lines)


def _unmet(res: dict) -> str:
    u = res["unmet_demand"]
    median = _pct(u["national_median_delay_rate_pct"])
    if u.get("excess_delayed_flights") is None:
        excess = f"{UNKNOWN} (no delay data)"
    elif u["excess_delayed_flights"] == 0:
        excess = f"0 (the delay rate is at or below the national median of {median})"
    else:
        excess = f"{u['excess_delayed_flights_display']} a year above the national median delay rate of {median}"
    lines = [
        f"- Seat gap: {u['seat_gap_display'] or UNKNOWN} seats a year" + (f"; {u['seat_gap_interpretation']}" if u.get("seat_gap_interpretation") else ""),
        f"- Excess delayed flights: {excess}",
    ]
    if u.get("delay_cause_shares"):
        lines.append("- Delay causes: " + ", ".join(f"{x['cause']} {_pct(x['share_pct'])}" for x in u["delay_cause_shares"]))
    if res.get("delay_note"):
        lines.append(f"- {res['delay_note']}")
    lines.append(f"- {u['lower_bound_note']}")
    return "\n".join(lines)


def _month_table(res: dict) -> str:
    lines = [f"| Month | {res['label'].capitalize()} | Same month a year earlier | Change |", "|---|---|---|---|"]
    for m in res["months"]:
        lines.append(f"| {m['month']} | {m['display'] or UNKNOWN} | {m['prior_year_display'] or 'n/a'} | "
                     f"{m['change_display'] or 'n/a'} |")
    return "\n".join(lines) + f"\n\nChange vs the same month a year earlier, in {res['change_unit']}."


def _trend_summary(env: dict) -> str:
    s = env["result"]["summary"]
    lines = []
    for key, name in (("highest", "Highest month"), ("lowest", "Lowest month")):
        if s[key]:
            lines.append(f"- {name}: {s[key]['month']}, {s[key]['display']}")
    fl = s["first_vs_last_12"]
    if fl:
        lines.append(f"- Year {fl['last_period']} vs year {fl['first_period']}: {fl['last_display'] or UNKNOWN} vs "
                     f"{fl['first_display'] or UNKNOWN} ({fl['change_display'] or 'n/a'}; {fl['basis']})")
    lines += [f"- {n}" for n in env.get("notes") or []]
    se = s["seasonal_profile"]
    if se:
        lines.append(f"\n*Seasonal profile: {se['basis']} over the last {se['years']} full years ({se['period']})*"
                     if se["years"] > 1 else
                     f"\n*Seasonal profile: one full year ({se['period']})*")
        lines += ["", "| Month | Value |", "|---|---|"]
        lines += [f"| {x['month']} | {x['display'] or UNKNOWN} |" for x in se["months"]]
    return "\n".join(lines)


# ---------- fixed sections ----------

def _robustness(env: dict) -> str:
    rb = env["result"].get("robustness")
    return rb["summary"].removeprefix("Robustness: ") if rb else ""


def _warnings(warnings: list[dict]) -> str:
    if not warnings:
        return "None for the airports shown."
    return "\n".join(f"- **{w.get('airport')}** ({w.get('severity')}): {w.get('message')}" for w in warnings)


def _confidence(footer: dict) -> str:
    label = str(footer.get("confidence", "n/a"))
    label = label.capitalize() if label != "n/a" else label
    return f"Confidence: {label} ({footer.get('confidence_reason', '')})"


def _assumptions(env: dict, footer: dict) -> str:
    periods = footer.get("data_period") or {}
    lines = [f"- {PERIOD_NAMES.get(k, k)}: {v}" for k, v in periods.items()]
    labels = {d["name"]: d.get("label") or d["name"] for d in env.get("definitions") or []}
    for a in footer.get("assumptions") or []:
        name, sep, rest = a.partition(": ")
        lines.append(f"- {labels[name]}: {rest}" if sep and name in labels else f"- {a}")
    note = env["result"].get("note")
    if note:
        lines.append(f"- {note}")
    if env["result"].get("weights_used"):
        lines.append("- custom weights: a sensitivity check, not the default score")
    lines.append(f"- {_confidence(footer)}")
    return "\n".join(lines)


def _status_line(warnings: list[dict], footer: dict) -> str:
    warn = "; ".join(f"{w.get('airport')}: {w.get('message')}" for w in warnings) or "none"
    return f"Warnings: {warn}\n\n{_confidence(footer)}"


def _suggestions(kind: str, env: dict, rows: list[dict], halves) -> list[str]:
    if kind == "ranking":
        top = [r["code"] for r in sorted((r for r in rows if r.get("rank")), key=lambda r: r["rank"])[:2]]
        out = [f"Compare {top[0]} and {top[1]}."] if len(top) == 2 else []
        return out + ([f"Give me a profile of {top[0]}."] if top else [])
    if kind == "comparison":
        return [f"Give me a profile of {r['code']}." for r in rows[:3]]
    res = env["result"]
    if kind == "trend":
        other = "has the delay rate" if res["metric"] == "passengers" else "have passengers"
        return [f"How {other} at {res['code']} changed month by month?", f"Give me a profile of {res['code']}."]
    code = res["code"]
    long_haul, unmet = halves
    if long_haul and not unmet:
        return [f"What is the unmet demand at {code}?"]
    if unmet and not long_haul:
        return [f"What share of {code}'s flights are long-haul?"]
    others = [x["cutoff_mi"] for x in res["long_haul"]["table"] if x["cutoff_mi"] != res["long_haul"]["headline_cutoff_mi"]]
    return [f"What is the long-haul share at {others[0]:,} miles?"] if others else []
