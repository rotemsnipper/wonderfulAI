"""The agent loop: one user question in, one saved Turn out.

Per turn: up to ROUND_CAP model calls with tool use (counted for this turn only); when the cap is hit,
one forced answer without tools that says what is missing. The final answer goes through the number
check; on failure one rewrite request (prefixed NUMBER_CHECK_PREFIX), and if it still fails the answer
is shown with the unverified numbers flagged. Footer, warnings and the advice line are added by code.
The turn is saved only once complete; a failed model call saves nothing, so the conversation stays valid.
"""
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.agent import llm
from backend.agent.footer import collect_warnings, footer
from backend.agent.safeguards import unverified_numbers
from backend.agent.session import SessionStore, Turn, history_messages, pool_from_trace, rebuild_pool

log = logging.getLogger(__name__)

ROUND_CAP = 7
NUMBER_CHECK_PREFIX = "[number-check]"
CAP_PREFIX = "[tool-limit]"
SHORTEN_PREFIX = "[length-limit]"
ADVICE_LINE = ("This is a data screen, not investment advice: confirm with site studies, airline demand and "
               "financial analysis before committing capital.")
RECOMMENDATION = re.compile(r"(?i)\b(should|recommend|candidates?|worth|invest|expand|expansion|renovat)")
REFUSAL_TEXT = "I can't help with that request. I can answer questions about US airport traffic, growth, delays and expansion signals."
EMPTY_TEXT = "I could not produce an answer to that. Please try rephrasing the question."
MODEL_ERROR_TEXT = "The model is not available right now, so this question was not answered. Please try again."

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
        tokens = {"input": 0, "output": 0}
        model = ""

        def ask(extra: list[dict] | None = None, tools: bool = True) -> llm.ModelReply:
            nonlocal model
            reply = self.complete(history + msgs + (extra or []), self.system, self.tool_specs if tools else None)
            tokens["input"] += reply.input_tokens
            tokens["output"] += reply.output_tokens
            model = reply.model or model
            return reply

        try:
            answer, rounds, capped = self._rounds(ask, msgs, trace)
            outcome = {"status": "passed", "unverified": [], "rounds": rounds, "capped": capped}
            pool_now = pool | pool_from_trace(trace)
            allowed = f"{question}\n{self.system}"
            bad = unverified_numbers(answer, pool_now, allowed)
            if bad:
                self.on_event("rewrite", {"unverified": bad})
                request = (f"{NUMBER_CHECK_PREFIX} These numbers in your answer do not match any tool result: "
                           f"{', '.join(bad)}. Rewrite the answer using only numbers from the tool results, or describe "
                           "those points in words. Keep everything else.")
                retry = ask([{"role": "assistant", "content": answer}, {"role": "user", "content": request}], tools=False)
                if retry.text.strip():
                    answer = retry.text.strip()
                still = unverified_numbers(answer, pool_now, allowed)
                outcome = {**outcome, "status": "flagged" if still else "rewritten", "unverified": still,
                           "first_unverified": bad}
        except llm.ModelError as e:
            log.warning("turn rolled back after model error: %s", e)
            text = str(e) if isinstance(e, llm.RateLimitError) else MODEL_ERROR_TEXT
            return {"error": type(e).__name__, "display_text": text, "saved": False,
                    "check_outcome": {"status": "error", "unverified": []}, "footer": {"confidence": "n/a"},
                    "warnings": [], "tool_trace": trace}

        msgs.append({"role": "assistant", "content": answer})
        used_trace = trace or self._reused_trace(previous, answer)
        turn_footer = footer(used_trace, answer)
        warnings = collect_warnings(used_trace)
        display = answer
        if outcome["status"] == "flagged":
            display += "\n\nNote: these numbers could not be matched to our data: " + ", ".join(outcome["unverified"]) + "."
        if RECOMMENDATION.search(question) and trace:
            display += "\n\n" + ADVICE_LINE
        turn = Turn(
            question=question, model_messages=msgs, tool_trace=trace, check_outcome=outcome, footer=turn_footer,
            warnings=warnings, display_text=display, tokens=tokens,
            timings={"total_ms": round((time.perf_counter() - t0) * 1000)}, model=model,
        )
        store.append_turn(user_id, conv_id, turn)
        self.on_event("done", {"status": outcome["status"]})
        return {**turn.to_dict(), "saved": True}

    def _rounds(self, ask, msgs: list[dict], trace: list[dict]) -> tuple[str, int, bool]:
        """Model calls with tool use for this turn. Returns (answer text, rounds used, whether capped)."""
        rounds = 0
        shortened = False
        while rounds < self.round_cap:
            reply = ask()
            rounds += 1
            if reply.tool_calls:
                msgs.append({"role": "assistant", "content": reply.text or None,
                             "tool_calls": [tc.to_message() for tc in reply.tool_calls]})
                for tc in reply.tool_calls:
                    self.on_event("tool_start", {"name": tc.name, "args": tc.args})
                    result = self.call_tool(tc.name, tc.args)
                    self.on_event("tool_end", {"name": tc.name, "error": result.get("error")})
                    trace.append({"tool": tc.name, "args": tc.args, "result": result})
                    msgs.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name, "content": result})
                continue
            if reply.stop_reason == "refusal":
                return REFUSAL_TEXT, rounds, False
            if reply.stop_reason == "max_tokens" and not shortened:
                shortened = True
                short = ask([{"role": "assistant", "content": reply.text},
                             {"role": "user", "content": f"{SHORTEN_PREFIX} That answer was cut off. Give the complete answer again in under 200 words."}],
                            tools=False)
                rounds += 1
                return (short.text.strip() or reply.text.strip() or EMPTY_TEXT), rounds, False
            return (reply.text.strip() or EMPTY_TEXT), rounds, False
        forced = ask([{"role": "user", "content": (
            f"{CAP_PREFIX} The tool-call limit for this question was reached. Answer now without tools, using only "
            "the tool results above, and say which information is still missing.")}], tools=False)
        return (forced.text.strip() or EMPTY_TEXT), rounds + 1, True

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

        manifest = tools.ctx().store.manifest
        _default = Agent(system=build_system_prompt(manifest), tool_specs=TOOL_SPECS, call_tool=tools.call)
    return _default


def run_turn(store: SessionStore, user_id: str, conv_id: str, question: str) -> dict:
    return default_agent().run_turn(store, user_id, conv_id, question)
