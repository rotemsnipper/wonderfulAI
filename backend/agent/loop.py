"""The agent loop: one user question in, one saved Turn out.

Per turn: up to ROUND_CAP model calls with tool use (counted for this turn only); when the cap is hit,
one forced answer without tools that says what is missing. The final answer goes through the number
check; on failure one rewrite request (prefixed NUMBER_CHECK_PREFIX), and if it still fails the answer
is shown with the unverified numbers flagged. Footer and warnings are computed by code; a turn that used
data is shown as a report (backend/report), whose code sections carry them and the advice line.
The turn is saved only once complete; a failed model call saves nothing, so the conversation stays valid.
"""
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.agent import llm
from backend.agent.footer import collect_warnings, footer
from backend.agent.safeguards import misattributed_numbers, unverified_numbers
from backend.agent.session import SessionStore, Turn, history_messages, pool_from_trace, rebuild_pool
from backend.report.render import build_report
from backend.report.sections import ADVICE_LINE  # noqa: F401  (re-exported for callers of the loop)

log = logging.getLogger(__name__)

ROUND_CAP = 7
NUMBER_CHECK_PREFIX = "[number-check]"
CAP_PREFIX = "[tool-limit]"
EMPTY_TEXT = "I could not produce an answer to that. Please try rephrasing the question."
MODEL_ERROR_TEXT = "The model is not available right now, so this question was not answered. Please try again."
# refresh_data replaces the dataset, so it runs only when the user's own words ask for it (code, not the prompt).
REFRESH_TOOL = "refresh_data"
# A request is the verb acting on the data ("update the data"), not the noun ("the latest data update").
REFRESH_REQUEST = re.compile(r"(?i)\b(update|refresh|reload|re-?download)\s+(the\s+|our\s+|your\s+)?data(set)?\b")
REFRESH_OFFER = re.compile(r"(?i)\b(update|refresh|reload|re-?download)\b.*\bdata(set)?\b.*\?\s*$", re.S)
NEGATION = re.compile(r"(?i)\b(no|not|don'?t|never|stop|cancel|keep)\b")
AFFIRMATIVE = re.compile(r"(?i)^\s*(yes|yeah|yep|sure|ok(ay)?|please|go ahead|do it)\b")
REFRESH_REFUSED = ("refresh_data runs only when the user asks to update or refresh the data. Tell the user what "
                   "check_data_updates found and ask whether they want the data updated.")

Event = Callable[[str, dict], None]


@dataclass
class Agent:
    system: str
    tool_specs: list[dict]
    call_tool: Callable[[str, dict], dict]
    complete: Callable[..., llm.ModelReply] = llm.complete
    round_cap: int = ROUND_CAP
    on_event: Event = field(default=lambda kind, data: None)

    def run_turn(self, store: SessionStore, user_id: str, conv_id: str, question: str) -> dict:
        t0 = time.perf_counter()
        previous = store.load(user_id, conv_id)
        history = history_messages(previous)
        pool = rebuild_pool(previous)
        msgs: list[dict] = [{"role": "user", "content": question}]
        trace: list[dict] = []
        tokens = {"input": 0, "output": 0, "thinking": 0}
        model = ""
        last_stop = ""

        def ask(extra: list[dict] | None = None, tools: bool = True) -> llm.ModelReply:
            nonlocal model, last_stop
            reply = self.complete(history + msgs + (extra or []), self.system, self.tool_specs if tools else None)
            tokens["input"] += reply.input_tokens
            tokens["output"] += reply.output_tokens
            tokens["thinking"] += reply.thinking_tokens
            last_stop = reply.stop_reason
            model = reply.model or model
            return reply

        try:
            answer, rounds, capped = self._rounds(ask, msgs, trace, self._refresh_requested(previous, question))
            outcome = {"status": "passed", "unverified": [], "rounds": rounds, "capped": capped}
            pool_now = pool | pool_from_trace(trace)
            allowed = f"{question}\n{self.system}"
            all_trace = [c for prev in previous for c in prev.tool_trace] + trace

            def check(text: str) -> tuple[list[str], list[str]]:
                missing = unverified_numbers(text, pool_now, allowed)
                wrong = [n for n in misattributed_numbers(text, all_trace, question, self.system) if n not in missing]
                return missing, wrong

            bad, wrong = check(answer)
            if bad or wrong:
                self.on_event("rewrite", {"unverified": bad, "misattributed": wrong})
                problems = []
                if bad:
                    problems.append(f"these numbers do not match any tool result: {', '.join(bad)}")
                if wrong:
                    problems.append(f"these numbers are not values of the airport named in their sentence: {', '.join(wrong)}")
                request = (f"{NUMBER_CHECK_PREFIX} In your answer, {'; and '.join(problems)}. Rewrite the answer using "
                           "only numbers from the tool results, each beside the airport it belongs to, or describe "
                           "those points in words. Keep everything else.")
                retry = ask([{"role": "assistant", "content": answer}, {"role": "user", "content": request}], tools=False)
                if retry.text.strip():
                    answer = retry.text.strip()
                still_bad, still_wrong = check(answer)
                still = still_bad + still_wrong
                outcome = {**outcome, "status": "flagged" if still else "rewritten", "unverified": still,
                           "first_unverified": bad + wrong}
            outcome["cut_off"] = last_stop == "max_tokens"
        except llm.ModelError as e:
            log.warning("turn rolled back after model error: %s", e)
            text = str(e) if isinstance(e, llm.RateLimitError) else MODEL_ERROR_TEXT
            return {"error": type(e).__name__, "display_text": text, "saved": False,
                    "check_outcome": {"status": "error", "unverified": []}, "footer": {"confidence": "n/a"},
                    "warnings": [], "tool_trace": trace}

        msgs.append({"role": "assistant", "content": answer})
        used_trace = trace or self._reused_trace(previous, answer)
        turn_footer = footer(used_trace)
        warnings = collect_warnings(used_trace)
        last_subject = next((t.report["subject"] for t in reversed(previous) if t.report), None)
        report = build_report(trace, answer, self._report_question(previous, question), turn_footer, warnings,
                              outcome, last_subject)
        if report is not None:
            display = report.markdown
        else:
            display = answer
            if outcome["status"] == "flagged":
                display += "\n\nNote: these numbers could not be matched to our data: " + ", ".join(outcome["unverified"]) + "."
            display += "".join(f"\n\n{n}" for n in turn_footer["notes"])
        turn = Turn(
            question=question, model_messages=msgs, tool_trace=trace, check_outcome=outcome, footer=turn_footer,
            warnings=warnings, display_text=display, tokens=tokens,
            timings={"total_ms": round((time.perf_counter() - t0) * 1000)}, model=model,
            report=report.to_dict() if report else None,
        )
        store.append_turn(user_id, conv_id, turn)
        self.on_event("done", {"status": outcome["status"]})
        return {**turn.to_dict(), "saved": True}

    def _rounds(self, ask, msgs: list[dict], trace: list[dict], refresh_ok: bool) -> tuple[str, int, bool]:
        """Model calls with tool use for this turn. Returns (answer text, rounds used, whether capped)."""
        rounds = 0
        while rounds < self.round_cap:
            reply = ask()
            rounds += 1
            if reply.tool_calls:
                msgs.append({"role": "assistant", "content": reply.text or None,
                             "tool_calls": [tc.to_message() for tc in reply.tool_calls]})
                for tc in reply.tool_calls:
                    self.on_event("tool_start", {"name": tc.name, "args": tc.args})
                    if tc.name == REFRESH_TOOL and not refresh_ok:
                        result = {"error": REFRESH_REFUSED, "valid_options": []}
                    else:
                        result = self.call_tool(tc.name, tc.args)
                    self.on_event("tool_end", {"name": tc.name, "error": result.get("error")})
                    trace.append({"tool": tc.name, "args": tc.args, "result": result})
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": result})
                continue
            return (reply.text.strip() or EMPTY_TEXT), rounds, False
        forced = ask([{"role": "user", "content": (
            f"{CAP_PREFIX} The tool-call limit for this question was reached. Answer now without tools, using only "
            "the tool results above, and say which information is still missing.")}], tools=False)
        return (forced.text.strip() or EMPTY_TEXT), rounds + 1, True

    @staticmethod
    def _refresh_requested(previous: list[Turn], question: str) -> bool:
        """The user's own words ask to update the data, or say yes to the assistant's offer to do it.
        Any negation closes the gate ("No, do not update the data")."""
        if NEGATION.search(question):
            return False
        if REFRESH_REQUEST.search(question):
            return True
        last = previous[-1] if previous else None
        offered = bool(last and last.report is None and REFRESH_OFFER.search(last.display_text.rstrip()))
        return offered and bool(AFFIRMATIVE.search(question))

    @staticmethod
    def _report_question(previous: list[Turn], question: str) -> str:
        """A reply to a clarifying question ("New York City") is read with the question it clarifies."""
        last = previous[-1] if previous else None
        if last and last.report is None and last.display_text.rstrip().endswith("?"):
            return f"{last.question}\n{question}"
        return question

    @staticmethod
    def _reused_trace(previous: list[Turn], answer: str) -> list[dict]:
        """For a follow-up answered without tools that still quotes figures, use the latest turn that fetched data."""
        if not re.search(r"\d", answer):
            return []
        for t in reversed(previous):
            if t.tool_trace:
                return [{**call, "reused": True} for call in t.tool_trace]
        return []


_default: Agent | None = None


def default_agent() -> Agent:
    global _default
    if _default is None:
        from backend.agent.prompt import build_system_prompt
        from backend.tools import tools
        from backend.tools.specs import TOOL_SPECS

        store = tools.ctx().store
        _default = Agent(system=build_system_prompt(store.manifest, store.settings), tool_specs=TOOL_SPECS, call_tool=tools.call)
    return _default


def run_turn(store: SessionStore, user_id: str, conv_id: str, question: str) -> dict:
    return default_agent().run_turn(store, user_id, conv_id, question)
