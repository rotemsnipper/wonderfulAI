"""Run the eval set and grade it: python -m backend.evals.run_evals [--case ID] [--out DIR]

Each case runs as a fresh conversation. A case with `resume_after_turn` reloads the conversation from the
session store after that turn and continues with a new agent instance, to exercise resume.

The agent is driven through `turn_fn(store, user_id, conv_id, question) -> turn dict`. The default comes
from the agent loop (M3-G); tests and dry runs can pass their own.
"""
import argparse
import json
import sys
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from backend.agent.session import InMemorySessionStore
from backend.evals.graders import grade, load_cases, load_expected

RESULTS_DIR = Path(__file__).resolve().parent / "results"
TurnFn = Callable[[object, str, str, str], dict]


def default_turn_fn() -> TurnFn:
    from backend.agent import loop  # M3-G; imported late so graders work without it

    return loop.run_turn


def run_case(case: dict, turn_fn: TurnFn, make_turn_fn: Callable[[], TurnFn] | None = None) -> dict:
    store = InMemorySessionStore()
    user_id, conv_id = "eval-user", f"eval-{case['id']}-{uuid.uuid4().hex[:8]}"
    turns = []
    for i, question in enumerate(case["turns"], start=1):
        turns.append(turn_fn(store, user_id, conv_id, question))
        if case.get("resume_after_turn") == i and make_turn_fn:
            turn_fn = make_turn_fn()
    return {"case_id": case["id"], "turns": turns}


def run_all(cases: list[dict], turn_fn: TurnFn, make_turn_fn: Callable[[], TurnFn] | None = None,
            expected: dict | None = None) -> list[dict]:
    expected = load_expected() if expected is None else expected
    results = []
    for case in cases:
        run = run_case(case, turn_fn, make_turn_fn)
        results.append({**grade(case, run, expected), "turns": [_summary(t) for t in run["turns"]]})
    return results


def _summary(turn: dict) -> dict:
    """What a failure needs for diagnosis: the answer, checks, footer and which tools were called with what."""
    return {
        "question": turn.get("question"), "display_text": turn.get("display_text"),
        "check_outcome": turn.get("check_outcome"), "footer": turn.get("footer"), "error": turn.get("error"),
        "report": {k: (turn.get("report") or {}).get(k) for k in ("kind", "mode", "subject")},
        "tools": [{"tool": c["tool"], "args": c["args"], "error": (c.get("result") or {}).get("error")}
                  for c in turn.get("tool_trace") or []],
        "tokens": turn.get("tokens"), "timings": turn.get("timings"),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--case", action="append", help="run only these case ids")
    p.add_argument("--out", type=Path, default=RESULTS_DIR)
    args = p.parse_args(argv)
    cases = [c for c in load_cases() if not args.case or c["id"] in args.case]
    results = run_all(cases, default_turn_fn(), default_turn_fn)
    args.out.mkdir(parents=True, exist_ok=True)
    out = args.out / f"evals_{datetime.now():%Y%m%d_%H%M%S}.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    for r in results:
        print(f"{'PASS' if r['passed'] else 'FAIL'} {r['case_id']}")
        for name, (ok, detail) in r["checks"].items():
            if not ok:
                print(f"    {name}: {detail}")
    passed = sum(r["passed"] for r in results)
    print(f"{passed}/{len(results)} passed; results in {out}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
