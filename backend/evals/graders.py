"""Code-only graders for eval runs.

A run result is {"case_id": str, "turns": [turn, ...]} where each turn has at least
"display_text", "check_outcome" ({"status": "passed" | "rewritten" | "flagged", "unverified": [...]}),
"footer" ({"confidence": ...}) and optionally "tool_trace", "model_messages" and "report" (the Turn fields).
The last turn is graded unless a check says otherwise. Forbidden patterns and claim checks read the model's own
text; airports, required patterns and figures read the full display text the user sees. Report checks run on
every turn shown as a full report.
"""
import json
import re
from pathlib import Path

from backend.agent.safeguards import extract_numbers
from backend.config import REPO_ROOT
from backend.report import sections as S

EXPECTED_PATH = REPO_ROOT / "scripts" / "recompute" / "expected.json"
QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"
CONFIDENCE_LABELS = {"high", "medium", "low", "n/a"}
FINANCIAL_CLAIM = re.compile(r"(?i)\$\s?\d|\bROI\b|return on investment|\bprofit (of|margin)")


def load_cases(path: Path = QUESTIONS_PATH) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["cases"]


def load_expected(path: Path = EXPECTED_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def lookup(expected: dict, key: str):
    node = expected
    for part in key.split("."):
        node = node[part]
    return node


def _codes(text: str) -> set[str]:
    return set(re.findall(r"\b[A-Z]{3}\b", text))


def model_text(turn: dict) -> str:
    """The model's own answer (the last assistant message); the display text when messages are not stored."""
    for m in reversed(turn.get("model_messages") or []):
        if m.get("role") == "assistant" and m.get("content"):
            return m["content"]
    return turn.get("display_text", "")


def _mode(turn: dict) -> str:
    report = turn.get("report")
    return f"report:{report['kind']}" if report and report["mode"] == S.REPORT else (report or {}).get("mode", "plain")


def _section(report: dict, section_id: str) -> str:
    return next((s["markdown"] for s in report["sections"] if s["id"] == section_id), "")


def _full_reports(turns: list[dict]) -> list[tuple[int, dict, dict]]:
    return [(i, t, t["report"]) for i, t in enumerate(turns) if (t.get("report") or {}).get("mode") == S.REPORT]


def _last_data_result(turn: dict) -> dict:
    for call in reversed(turn.get("tool_trace") or []):
        if call["tool"] in S.KINDS and "error" not in (call.get("result") or {}):
            return call["result"]["result"]
    return {}


def grade_modes(case: dict, turns: list[dict]) -> tuple[bool, str]:
    """`expect_modes`: per turn "report:<kind>", "follow_up", "plain", "not_report" or null (anything)."""
    wanted = case.get("expect_modes")
    if not wanted:
        return True, "n/a"
    got = [_mode(t) for t in turns]
    bad = [(i, w, g) for i, (w, g) in enumerate(zip(wanted, got))
           if w and not (g == w or (w == "not_report" and not g.startswith("report:")))]
    ok = not bad and len(turns) >= len(wanted)
    return ok, f"modes {got}" if ok else f"wrong modes (turn, wanted, got): {bad}"


def grade_report_sections(case: dict, turns: list[dict]) -> tuple[bool, str]:
    missing = [(i, sorted(set(S.REQUIRED[r["kind"]]) - {s["id"] for s in r["sections"]}
                          - (set() if r.get("investment", True) else {S.COMPARISON}))) for i, _, r in _full_reports(turns)]
    missing = [m for m in missing if m[1]]
    return not missing, f"missing sections {missing}" if missing else "required sections present"


def _cells(row: str) -> list[str]:
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _shown_label(details: str, code: str, row_label: str = "Recommendation") -> str:
    """The text the details section shows for an airport: its cell in a grid whose header names the code, or
    its line in a table that lists it as "Name (CODE)"."""
    lines = details.splitlines()
    for i, line in enumerate(lines):
        head = _cells(line) if line.startswith("|") else []
        if code in head:
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                cells = _cells(row)
                if cells and cells[0] == row_label and len(cells) > head.index(code):
                    return cells[head.index(code)]
    return next((ln for ln in lines if f"({code})" in ln), "")


def _rows(kind: str, res: dict) -> list[dict]:
    if kind == "ranking":
        return [x for g in res.get("groups", {}).values() for x in g]
    if kind == "trend":
        return []  # one airport, no labels and no Comparison to check
    return res.get("airports") or [res]


def grade_label_match(case: dict, turns: list[dict]) -> tuple[bool, str]:
    """The recommendation the report shows is the tool's, for every airport the tool labeled."""
    bad = []
    for i, t, r in _full_reports(turns):
        if not r.get("investment", True):
            continue  # a factual report shows no labels
        details = _section(r, S.DETAILS)
        for row in _rows(r["kind"], _last_data_result(t)):
            rec = (row.get("score") or {}).get("recommendation")
            if rec and row.get("code") and rec not in _shown_label(details, row["code"]):
                bad.append((i, row.get("code"), rec))
    return not bad, f"label mismatch {bad}" if bad else "labels match the tools"


def grade_comparison_names_airports(case: dict, turns: list[dict]) -> tuple[bool, str]:
    """The model's Comparison names every airport compared (the top three of a ranking)."""
    bad = []
    for i, t, r in _full_reports(turns):
        rows = _rows(r["kind"], _last_data_result(t))
        if r["kind"] == "ranking":
            rows = sorted((x for x in rows if x.get("rank")), key=lambda x: x["rank"])[:3]
        text = _section(r, S.COMPARISON)
        if not r.get("investment", True) or (r["kind"] == "profile" and not text):
            continue  # a factual report has no Comparison; optional for a one-airport question
        missing = [x["code"] for x in rows if x.get("code") and x["code"] not in text]
        if missing:
            bad.append((i, missing))
    return not bad, f"comparison misses airports {bad}" if bad else "comparison names every airport"


def grade_no_financial_claim(case: dict, turns: list[dict]) -> tuple[bool, str]:
    hits = [(i, m.group(0)) for i, t, _ in _full_reports(turns) if (m := FINANCIAL_CLAIM.search(model_text(t)))]
    return not hits, f"financial claim in a report {hits}" if hits else "no financial claim"


def grade_verdict_names_top(case: dict, turns: list[dict]) -> tuple[bool, str]:
    bad = []
    for i, t, r in _full_reports(turns):
        if r["kind"] != "ranking":
            continue
        top = next((x["code"] for g in _last_data_result(t).get("groups", {}).values() for x in g if x.get("rank") == 1), None)
        if top and top not in _section(r, S.VERDICT):
            bad.append((i, top))
    return not bad, f"verdict misses the top airport {bad}" if bad else "verdict names the top airport"


def grade_airports(case: dict, turns: list[dict]) -> tuple[bool, str]:
    answer = turns[-1]["display_text"]
    expected = case.get("expected_airports", [])
    if not expected:
        return True, "no airports expected"
    found = _codes(answer) & set(expected)
    need = case.get("min_airports", len(expected))
    ok = len(found) >= need
    return ok, f"found {sorted(found)}; need {need} of {expected}"


def grade_per_turn_airports(case: dict, turns: list[dict]) -> tuple[bool, str]:
    wanted = case.get("per_turn_airports")
    if not wanted:
        return True, "n/a"
    missing = [(i, sorted(set(w) - _codes(t["display_text"]))) for i, (w, t) in enumerate(zip(wanted, turns))
               if not set(w) <= _codes(t["display_text"])]
    ok = not missing and len(turns) >= len(wanted)
    return ok, f"missing per turn: {missing}" if missing else f"{len(turns)} turns"


def grade_required(case: dict, turns: list[dict]) -> tuple[bool, str]:
    answer = turns[-1]["display_text"]
    missing = [p for p in case.get("required", []) if not re.search(p, answer)]
    return not missing, f"missing patterns {missing}" if missing else "all required content present"


def grade_forbidden(case: dict, turns: list[dict]) -> tuple[bool, str]:
    answer = model_text(turns[-1])
    hits = [p for p in case.get("forbidden", []) if re.search(p, answer)]
    return not hits, f"forbidden patterns matched {hits}" if hits else "no forbidden content"


def grade_number_check(case: dict, turns: list[dict]) -> tuple[bool, str]:
    if not case.get("number_check"):
        return True, "n/a"
    graded = turns if case.get("all_turns_number_check") else turns[-1:]
    bad = [(i, t["check_outcome"].get("unverified")) for i, t in enumerate(graded)
           if t["check_outcome"].get("status") == "flagged" or t["check_outcome"].get("unverified")]
    return not bad, f"flagged numbers {bad}" if bad else "number check passed"


def grade_complete(case: dict, turns: list[dict]) -> tuple[bool, str]:
    cut = [i for i, t in enumerate(turns) if (t.get("check_outcome") or {}).get("cut_off")]
    return not cut, f"answer cut off at the token limit in turns {cut}" if cut else "answers complete"


def grade_footer(case: dict, turns: list[dict]) -> tuple[bool, str]:
    footer = turns[-1].get("footer") or {}
    label = footer.get("confidence")
    if label not in CONFIDENCE_LABELS:
        return False, f"footer confidence missing or invalid: {label!r}"
    want = case.get("expect_confidence")
    if want and label != want:
        return False, f"confidence {label!r}, expected {want!r}"
    return True, f"confidence {label}"


def grade_figures(case: dict, turns: list[dict], expected: dict) -> tuple[bool, str]:
    figures = case.get("figures", [])
    if not figures:
        return True, "n/a"
    if not expected:
        return False, "expected.json not found; run scripts/recompute/recompute.py"
    values = [v for _, v, _, _ in extract_numbers(turns[-1]["display_text"])]
    missing = []
    for f in figures:
        target = float(lookup(expected, f["key"]))
        tol = abs(target) * f["tolerance_pct"] / 100
        if not any(abs(v - target) <= tol or abs(v * 100 - target) <= tol for v in values):
            missing.append(f"{f['key']}={target:.4g}")
    return not missing, f"figures not found {missing}" if missing else "all figures present"


def grade(case: dict, run: dict, expected: dict | None = None) -> dict:
    expected = load_expected() if expected is None else expected
    turns = run["turns"]
    if not turns:
        return {"case_id": case["id"], "passed": False, "checks": {"turns": (False, "no turns")}}
    checks = {
        "airports": grade_airports(case, turns),
        "per_turn_airports": grade_per_turn_airports(case, turns),
        "required": grade_required(case, turns),
        "forbidden": grade_forbidden(case, turns),
        "number_check": grade_number_check(case, turns),
        "footer": grade_footer(case, turns),
        "complete": grade_complete(case, turns),
        "figures": grade_figures(case, turns, expected),
        "modes": grade_modes(case, turns),
        "report_sections": grade_report_sections(case, turns),
        "label_match": grade_label_match(case, turns),
        "comparison_names_airports": grade_comparison_names_airports(case, turns),
        "no_financial_claim": grade_no_financial_claim(case, turns),
        "verdict_names_top": grade_verdict_names_top(case, turns),
    }
    return {"case_id": case["id"], "passed": all(ok for ok, _ in checks.values()), "checks": checks}
