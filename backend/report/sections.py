"""Report section ids and titles, report kinds and modes, and the fixed texts. Shared by the renderer,
the loop and the graders, so a section is named in one place only."""
import re
from dataclasses import asdict, dataclass, field

MODEL, CODE = "model", "code"

DETAILS = "details"
COMPARISON = "comparison"
VERDICT = "verdict"
WHY = "why"
SPECIFIC = "specific"
ROBUSTNESS = "robustness"
WARNINGS = "warnings"
ASSUMPTIONS = "assumptions"
STILL_NEEDED = "still_needed"
STATUS = "status"

TITLES = {
    DETAILS: "The airports",
    COMPARISON: "Comparison",
    VERDICT: "Verdict",
    WHY: "Why",
    ROBUSTNESS: "Robustness",
    WARNINGS: "Warnings",
    ASSUMPTIONS: "Data period, assumptions and confidence",
    STILL_NEEDED: "Still needed before investing",
    STATUS: "Warnings and confidence",
}
SPECIFIC_TITLES = {"ranking": "Not ranked", "comparison": "Congestion and runways",
                   "trend": "Trend summary and seasonal profile"}
DETAILS_TITLES = {"trend": "Month by month"}
PROFILE_TITLES = {(True, True): "Long-haul share and unmet demand", (True, False): "Long-haul share",
                  (False, True): "Unmet demand"}
MODEL_SECTIONS = [COMPARISON, VERDICT, WHY]

KINDS = {"rank_airports": "ranking", "compare_airports": "comparison", "airport_profile": "profile",
         "airport_trend": "trend"}
REPORT, FOLLOW_UP = "report", "follow_up"

ORDER = [DETAILS, COMPARISON, VERDICT, WHY, SPECIFIC, ROBUSTNESS, WARNINGS, ASSUMPTIONS, STILL_NEEDED]
# Sections every full report of a kind has (section 9 depends on the question, robustness on the metric).
# A factual comparison or profile (not about investing) has no Comparison: see `Report.investment`.
REQUIRED = {
    "ranking": [DETAILS, COMPARISON, VERDICT, WHY, WARNINGS, ASSUMPTIONS],
    "comparison": [DETAILS, COMPARISON, VERDICT, WHY, SPECIFIC, WARNINGS, ASSUMPTIONS],
    "profile": [DETAILS, VERDICT, WHY, SPECIFIC, WARNINGS, ASSUMPTIONS],  # Comparison only for investment questions
    "trend": [DETAILS, VERDICT, WHY, SPECIFIC, WARNINGS, ASSUMPTIONS],  # always factual: no scores, no Comparison
}
# The one code section a follow-up on the same subject shows: the block most follow-ups ask about.
FOLLOW_UP_SECTION = {"ranking": DETAILS, "comparison": SPECIFIC, "profile": SPECIFIC, "trend": DETAILS}
FULL_REPORT_REQUEST = re.compile(r"(?i)\b(full|detailed|complete) report\b")
INVESTMENT_QUESTION = re.compile(r"(?i)\b(should|recommend|candidates?|worth|invest|expand|expansion|renovat)")
LONG_HAUL_QUESTION = re.compile(r"(?i)long[- ]?haul|distance|\bmiles?\b|cutoff")
UNMET_QUESTION = re.compile(r"(?i)unmet|demand|delay|congest|seat")

STILL_NEEDED_ITEMS = [
    "terminal throughput and utilization (passengers per gate, peak-hour capacity)",
    "construction and operating cost of the expansion",
    "expected incremental passengers (airline commitments, FAA forecasts)",
    "revenue per incremental passenger and lease terms",
    "regulatory, environmental and physical constraints (land, runways, airspace, community caps)",
]
ADVICE_LINE = ("This is a data screen, not investment advice: confirm with site studies, airline demand and "
               "financial analysis before committing capital.")


@dataclass
class Section:
    id: str
    title: str
    written_by: str
    markdown: str


@dataclass
class Report:
    kind: str
    mode: str
    subject: str
    sections: list[Section]
    suggestions: list[str] = field(default_factory=list)
    investment: bool = True  # False: a factual comparison or profile, shown without scores and Comparison

    @property
    def markdown(self) -> str:
        parts = [f"**{s.title}**\n\n{s.markdown}" for s in self.sections]
        if self.suggestions:
            parts.append("**You could ask next**\n\n" + "\n".join(f"- {q}" for q in self.suggestions))
        return "\n\n".join(parts)

    def section(self, section_id: str) -> Section | None:
        return next((s for s in self.sections if s.id == section_id), None)

    def to_dict(self) -> dict:
        return asdict(self)
