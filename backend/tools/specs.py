"""JSON schemas the model sees for the four tools. Flat, with enums, so free-tier tool calling stays reliable."""
from backend.config import SERVING_DIR, load_settings
from backend.tools.tools import MAX_COMPARE, PER_GROUP_CAP, RANK_METRICS, REGIONS

_settings = load_settings(SERVING_DIR / "settings.yaml")

TOOL_SPECS: list[dict] = [
    {
        "name": "resolve_airport",
        "description": (
            "Turn an airport name, city, nickname or code into an airport code. Call this first whenever the user "
            "does not give a three-letter code. Status 'ambiguous' means ask the user to choose; 'not_found' means "
            "the airport is not in our data. Do not use it for whole states or regions; use rank_airports filters."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "the place or airport as the user wrote it"}},
            "required": ["query"],
        },
    },
    {
        "name": "rank_airports",
        "description": (
            "Rank covered airports by capacity-need score (default) or by one metric, optionally within a region, "
            "a state or a size tier. Use for 'which airports' questions. Score rows carry the passenger and flight "
            "side scores, the label (potential, confidence, recommendation), strengths and weaknesses. Results are "
            "grouped by size tier and include a robustness verdict for score rankings. To compare named airports "
            "use compare_airports."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "region": {"type": "string", "enum": list(REGIONS)},
                "state": {"type": "string", "description": "two-letter US state code, for example ME"},
                "size_tier": {"type": "string", "enum": list(_settings["size_bands"]) + ["all"]},
                "metric": {"type": "string", "enum": RANK_METRICS},
                "limit": {"type": "integer", "minimum": 1, "maximum": PER_GROUP_CAP,
                          "description": "airports per size tier"},
            },
        },
    },
    {
        "name": "compare_airports",
        "description": (
            f"Compare 2 to {MAX_COMPARE} airports side by side: traffic, load factor, growth, delays, departures per "
            "usable runway and score with its label, with differences and ratios already computed. Needs airport codes; resolve "
            "names first."
        ),
        "parameters": {
            "type": "object",
            "properties": {"codes": {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": MAX_COMPARE}},
            "required": ["codes"],
        },
    },
    {
        "name": "airport_profile",
        "description": (
            "One airport in depth: traffic, growth, delays and delay causes, score breakdown with side scores and "
            "label, long-haul share at "
            "several distance cutoffs (passenger flights and all flights), and unmet demand (seat gap, excess "
            "delayed flights). Use for long-haul and unmet-demand questions. Needs an airport code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "long_haul_cutoff_mi": {"type": "integer", "enum": list(_settings["long_haul_cutoffs"]),
                                        "description": "headline cutoff in miles; the full cutoff table is always returned"},
            },
            "required": ["code"],
        },
    },
]
