"""Number check: every number in a final answer must come from the tool results, the tool inputs or the
user's own text (membership only; a real number attached to the wrong airport still passes).

Matching tolerance is half the last written digit (36.0 million -> +/-50,000). Round numbers with trailing
zeros use their last non-zero digit, capped at 2.5% of the value (40,000 -> +/-1,000). A number written
with an explicit sign must match the sign; an unsigned number matches either sign ("fell 4%" vs -4.0).

Not checked: years, dates, ranks and ordinals, list markers, code-like tokens (T-100, A320), the 0-100
scale, and small counts (whole numbers up to 12 with no unit).
"""
import bisect
import math
import re
from collections.abc import Iterable

ROUND_CAP = 0.025
SMALL_COUNT_MAX = 12
SCALES = {"thousand": 1e3, "k": 1e3, "million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9}

_SEP = "[,    ]"
NUMBER = re.compile(
    r"(?P<sign>[+\-−])?"
    r"(?P<num>\d{1,3}(?:" + _SEP + r"\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)"
    r"(?P<pct>\s?%)?"
    r"(?:\s?(?P<scale>thousand|million|billion|mn|bn)\b|(?P<suffix>[kKmM])(?![A-Za-z]))?"
)
DATE = re.compile(r"\b(?:19|20)\d{2}-\d{1,2}(?:-\d{1,2})?\b|\b\d{1,2}/(?:19|20)\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")
SCALE_0_100 = re.compile(r"\b0\s?(?:-|–|to)\s?100\b|\bout of 100\b|/\s?100\b", re.I)
LIST_MARKER = re.compile(r"(?m)^\s*\d{1,2}[.)]\s")
RANK_BEFORE = re.compile(r"(?:#|\bno\.\s?|\brank(?:ed)?\s|\btop[\s-]|\bnumber\s)$", re.I)
ORDINAL_AFTER = re.compile(r"^(?:st|nd|rd|th)\b", re.I)
OF_AFTER_ORDINAL = re.compile(r"\d(?:st|nd|rd|th)\s+(?:of|out of)\s+$", re.I)


def _mask(text: str, pattern: re.Pattern) -> str:
    return pattern.sub(lambda m: " " * len(m.group(0)), text)


def _value(m: re.Match) -> tuple[float, float, bool]:
    """(value, tolerance, explicitly signed) for one regex match."""
    digits = re.sub(_SEP, "", m.group("num"))
    scale = 1.0
    if m.group("scale"):
        scale = SCALES[m.group("scale").lower()]
    elif m.group("suffix"):
        scale = SCALES[m.group("suffix").lower()]
    value = float(digits) * scale
    if "." in digits:
        unit = 10 ** -len(digits.split(".")[1]) * scale
        tol = unit / 2
    else:
        stripped = digits.rstrip("0")
        zeros = len(digits) - len(stripped) if stripped else 0
        tol = 10**zeros * scale / 2
        if zeros:
            tol = min(tol, ROUND_CAP * abs(value))
    sign = m.group("sign")
    if sign in ("-", "−"):
        value = -value
    return value, tol, bool(sign)


def extract_numbers(text: str) -> list[tuple[str, float, float, bool]]:
    """Checkable numbers in `text` as (as written, value, tolerance, explicitly signed); exempt ones skipped."""
    masked = _mask(_mask(_mask(text, DATE), SCALE_0_100), LIST_MARKER)
    out = []
    for m in NUMBER.finditer(masked):
        start, end = m.span()
        before, after = masked[:start], masked[end:]
        if before and (before[-1].isalpha() or (before[-1] == "-" and len(before) > 1 and before[-2].isalpha())):
            continue  # code-like: T-100, A320
        if after[:1].isalpha() and not m.group("scale") and not m.group("suffix") and not ORDINAL_AFTER.match(after):
            continue  # code-like: 737MAX, 3x
        if ORDINAL_AFTER.match(after) or RANK_BEFORE.search(before) or OF_AFTER_ORDINAL.search(before):
            continue
        # a sign glued to a preceding word or digit is a hyphen ("T-100", "2025-26"), not a minus
        sign_is_hyphen = m.group("sign") == "-" and start > 0 and masked[start - 1].isalnum()
        raw_num = m.group("num")
        is_int = re.fullmatch(r"\d+", raw_num) is not None
        no_unit = not m.group("pct") and not m.group("scale") and not m.group("suffix")
        if is_int and no_unit and 1900 <= int(raw_num) <= 2100:
            continue  # year
        if is_int and no_unit and int(raw_num) <= SMALL_COUNT_MAX:
            continue  # small count
        value, tol, signed = _value(m)
        if sign_is_hyphen:
            value, signed = abs(value), False
        written = m.group(0).strip() if not sign_is_hyphen else m.group(0)[1:].strip()
        out.append((written, value, tol, signed))
    return out


def numbers_in_data(obj) -> set[float]:
    """All numbers in a tool result or input: numeric leaves, numbers inside strings, and x100 of fractions."""
    out: set[float] = set()

    def add(x: float) -> None:
        if math.isfinite(x):
            out.add(float(x))
            if abs(x) <= 1.5:
                out.add(float(x) * 100)

    def walk(o) -> None:
        if isinstance(o, bool) or o is None:
            return
        if isinstance(o, (int, float)):
            add(o)
        elif isinstance(o, str):
            for _, value, _, _ in extract_numbers(o):
                add(value)
        elif isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, Iterable):
            for v in o:
                walk(v)
        elif hasattr(o, "item"):
            walk(o.item())

    walk(obj)
    return out


def _matches(value: float, tol: float, signed: bool, pool: list[float]) -> bool:
    targets = [value] if signed else [value, -value]
    for t in targets:
        i = bisect.bisect_left(pool, t - tol - 1e-9)
        if i < len(pool) and pool[i] <= t + tol + 1e-9:
            return True
    return False


def unverified_numbers(answer: str, pool: set[float], allowed_text: str = "") -> list[str]:
    """Numbers in `answer` that match nothing in `pool` or in `allowed_text` (the user's question, fixed prompt numbers)."""
    full = sorted(pool | {v for _, v, _, _ in extract_numbers(allowed_text)})
    return [written for written, value, tol, signed in extract_numbers(answer) if not _matches(value, tol, signed, full)]


# ---------- per-airport attribution ----------

CODE = re.compile(r"\b[A-Z]{3}\b")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")
# Fixed numbers (thresholds, cutoffs, weights) may sit beside an airport only in a sentence about a threshold;
# otherwise "BOS scores 65" would pass because 65 is the high-potential threshold.
THRESHOLD_WORDS = re.compile(r"(?i)\b(threshold|ceiling|cutoff|cut-off|limit|weight(ed|s)?|"
                             r"above|below|under|over|at least|clears?|misses|short of)\b")
# Definition texts restate settings (weights, thresholds), not values of any airport.
FIXED_TEXT_KEYS = {"definitions"}


def airport_pools(trace: Iterable[dict]) -> tuple[dict[str, set[float]], set[float]]:
    """Numbers tied to each airport in the tool results, and the numbers tied to no airport (national medians,
    settings, counts). A subtree belongs to an airport when it is a dict with that `code` (or `airport`), a pair
    with `a`/`b` codes (its `a_*` fields are a's, `b_*` fields b's, the rest both), or the value of a key that is
    an airport code."""
    calls = list(trace)
    codes = {c for call in calls for c in ((call.get("result") or {}).get("meta") or {}).get("airports", [])}
    per: dict[str, set[float]] = {}
    shared: set[float] = set()

    def walk(node, owners: frozenset) -> None:
        if isinstance(node, dict):
            here = owners | {node[k] for k in ("code", "airport") if node.get(k) in codes}
            a, b = node.get("a"), node.get("b")
            for k, v in node.items():
                if k in FIXED_TEXT_KEYS:
                    continue
                own = here | {k} if k in codes else here
                if a in codes and b in codes:  # a pair: a_* fields are a's, b_* fields b's, the rest both
                    own = own | ({a} if k.startswith("a_") else {b} if k.startswith("b_") else {a, b})
                walk(v, own)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v, owners)
        else:
            nums = numbers_in_data(node)
            if not owners:
                shared.update(nums)
            for c in owners:
                per.setdefault(c, set()).update(nums)

    for call in calls:
        walk(call.get("result"), frozenset())
    return per, shared


def misattributed_numbers(answer: str, trace: Iterable[dict], allowed_text: str = "", fixed_text: str = "") -> list[str]:
    """Numbers in a sentence that names exactly one airport but match none of that airport's values (nor a value
    tied to no airport). Catches a real figure moved to the wrong airport, which the pool check lets through.
    `allowed_text` (the user's question) always counts; `fixed_text` (the system prompt) only in a sentence
    about a threshold."""
    per, shared = airport_pools(trace)
    bad: list[str] = []
    for sentence in SENTENCE_END.split(answer or ""):
        named = set(CODE.findall(sentence)) & set(per)
        if len(named) != 1:
            continue
        (code,) = named
        allowed = f"{allowed_text}\n{fixed_text}" if THRESHOLD_WORDS.search(sentence) else allowed_text
        bad += unverified_numbers(sentence, per[code] | shared, allowed)
    return list(dict.fromkeys(bad))
