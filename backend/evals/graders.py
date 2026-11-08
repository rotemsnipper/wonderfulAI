"""Code-only graders for eval runs.

A run result is {"case_id": str, "turns": [turn, ...]} where each turn has at least
"display_text", "check_outcome" ({"status": "passed" | "rewritten" | "flagged", "unverified": [...]}),
"footer" ({"confidence": ...}) and optionally "tool_trace". The last turn is graded unless a check says otherwise.
"""
import json
import re
from pathlib import Path

from backend.agent.safeguards import extract_numbers
from backend.config import REPO_ROOT

EXPECTED_PATH = REPO_ROOT / "scripts" / "recompute" / "expected.json"
QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"
CONFIDENCE_LABELS = {"high", "medium", "low", "n/a"}


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
    answer = turns[-1]["display_text"]
    hits = [p for p in case.get("forbidden", []) if re.search(p, answer)]
    return not hits, f"forbidden patterns matched {hits}" if hits else "no forbidden content"


def grade_number_check(case: dict, turns: list[dict]) -> tuple[bool, str]:
    if not case.get("number_check"):
        return True, "n/a"
    graded = turns if case.get("all_turns_number_check") else turns[-1:]
    bad = [(i, t["check_outcome"].get("unverified")) for i, t in enumerate(graded)
           if t["check_outcome"].get("status") == "flagged" or t["check_outcome"].get("unverified")]
    return not bad, f"flagged numbers {bad}" if bad else "number check passed"


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
        "figures": grade_figures(case, turns, expected),
    }
    return {"case_id": case["id"], "passed": all(ok for ok, _ in checks.values()), "checks": checks}
