"""Fixed-rule label for a score breakdown: potential, confidence, recommendation, strengths and weaknesses.

Thresholds come from the `label` settings. A partial score is never labeled with a potential, so a high
partial score cannot become "Prioritize". This module is the only source of the thesis and label-rule text;
the prompt and the tool definitions render it from settings.
"""
from backend.scoring.score import SIDES

THESIS = (
    "Renovation pays where added capacity would be filled. Passenger side: passenger demand is growing and "
    "planes are already full. Flight side: flights are growing and the airport is congested. The score ranks "
    "capacity need across covered US airports; it is a proxy for profit, not a financial return."
)
COMPONENT_LABELS = {
    "passenger_growth": "passenger growth",
    "load_factor": "load factor",
    "flight_growth": "flight growth",
    "congestion": "congestion",
}
NOT_SCORED = "not scored"
RECOMMENDATIONS = {
    ("high", "high"): "Prioritize for due diligence",
    ("high", "medium"): "Investigate further",
    ("medium", "high"): "Investigate further",
    ("medium", "medium"): "Monitor",
    ("low", "high"): "Deprioritize",
    ("low", "medium"): "Deprioritize",
}
NOT_SCORED_RECOMMENDATION = "Not scored: review the available metrics"


def confidence(breakdown: dict | None, warnings: list[dict]) -> tuple[str, str]:
    """(level, reason): high with full data and no warning, medium with a warning, low without a full score."""
    if breakdown is None:
        return "low", "below the covered-airport threshold; no score"
    types = sorted({w["type"] for w in warnings if w["airport"] == breakdown["airport_code"]})
    if breakdown["data_tier"] != "full" or "partial_data" in types:
        missing = (breakdown["partial_scores"] or {}).get("components_missing", [])
        return "low", f"missing {', '.join(missing)}" if missing else "thin or partial data"
    if types:
        return "medium", ", ".join(types)
    return "high", "all components present"


def potential(total: float | None, cfg: dict) -> str:
    if total is None:
        return NOT_SCORED
    if total >= cfg["high_min"]:
        return "high"
    if total >= cfg["medium_min"]:
        return "medium"
    return "low"


def _entry(c: dict) -> dict:
    return {"component": c["name"], "label": COMPONENT_LABELS[c["name"]], "percentile": c["percentile"]}


def label(breakdown: dict, warnings: list[dict], settings: dict) -> dict:
    cfg = settings["label"]
    pot = potential(breakdown["total_score"], cfg)
    conf, reason = confidence(breakdown, warnings)
    rec = NOT_SCORED_RECOMMENDATION if pot == NOT_SCORED else RECOMMENDATIONS[(pot, "medium" if conf == "low" else conf)]
    present = [c for c in breakdown["components"] if c["percentile"] is not None]
    strengths = sorted((c for c in present if c["percentile"] >= cfg["strength_min"]), key=lambda c: -c["percentile"])
    weaknesses = sorted((c for c in present if c["percentile"] < cfg["weakness_max"]), key=lambda c: c["percentile"])
    return {
        "potential": pot,
        "confidence": conf,
        "confidence_reason": reason,
        "recommendation": rec,
        "strengths": [_entry(c) for c in strengths],
        "weaknesses": [_entry(c) for c in weaknesses],
    }


def _sides_text(weights: dict) -> str:
    return "; ".join(
        f"{side} side: " + ", ".join(f"{COMPONENT_LABELS[c]} {weights[c]:.0%}" for c in names)
        for side, names in SIDES.items()
    )


def score_definition(settings: dict) -> str:
    """One-line definition of the score for tool results."""
    cfg = settings["label"]
    return (f"weighted national rank percentiles across covered airports ({_sides_text(settings['weights'])}); "
            f"potential high at {cfg['high_min']} or more, medium from {cfg['medium_min']}, otherwise low; "
            f"strengths at or above the {cfg['strength_min']}th percentile, weaknesses below the "
            f"{cfg['weakness_max']}th; ranks capacity need, a proxy for profit, not a financial return")


def scoring_text(settings: dict) -> str:
    """The thesis, weights and label rule as prompt text, generated from settings."""
    cfg = settings["label"]
    sides = _sides_text(settings["weights"])
    hi, med = cfg["high_min"], cfg["medium_min"]
    return "\n".join([
        "## Scoring rules (generated from the settings)",
        f"- Thesis: {THESIS}",
        f"- Components and weights: {sides}. Each component is a national rank percentile (0-100).",
        f"- Potential: high at a score of {hi} or more, medium from {med} to under {hi}, low under {med}. "
        "A partial score is not scored.",
        "- Confidence: high with full data and no warning, medium with a warning (for example cargo-heavy), "
        "low without a full score.",
        "- Recommendation: high potential is 'Prioritize for due diligence' at high confidence and 'Investigate "
        "further' at medium; medium potential is 'Investigate further' at high confidence and 'Monitor' at medium; "
        "low potential is 'Deprioritize'.",
        f"- Strengths: components at or above the {cfg['strength_min']}th percentile. "
        f"Weaknesses: components below the {cfg['weakness_max']}th percentile.",
    ])
