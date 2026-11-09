"""JSON schemas the model sees for the tools. Flat, with enums, so free-tier tool calling stays reliable."""
from backend.config import SERVING_DIR, load_settings
from backend.tools.tools import MAX_COMPARE, PER_GROUP_CAP, RANK_METRICS

_settings = load_settings(SERVING_DIR / "settings.yaml")
_w = _settings["weights"]

TOOL_SPECS: list[dict] = [
    {
        "name": "resolve_airport",
        "description": (
            "Turn an airport name, city or code into an airport code. Call this first whenever the user does not "
            "give a three-letter code. Pass the full city or airport name, not an abbreviation or nickname; expand "
            "it first. Status 'ambiguous' means ask the user to choose; 'not_found' means retry once as its "
            "retry_hint says, then the airport is not in our data. Do not use it for whole states or regions; use "
            "the rank_airports states filter."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string",
                                     "description": "the full city or airport name, or a three-letter code"}},
            "required": ["query"],
        },
    },
    {
        "name": "rank_airports",
        "description": (
            "Rank covered airports by capacity-need score (default) or by one metric, optionally within a set of US "
            "states or a size tier. Use for 'which airports' questions. Score rows carry the passenger and flight "
            "side scores, the label (potential, confidence, recommendation), strengths and weaknesses. Results are "
            "grouped by size tier and include a robustness verdict for score rankings. To compare named airports "
            "use compare_airports."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "states": {"type": "array", "items": {"type": "string"}, "description": (
                    "two-letter US state codes to rank within; for a named region pass the codes of its states")},
                "size_tier": {"type": "string", "enum": list(_settings["size_bands"]) + ["all"]},
                "metric": {"type": "string", "enum": RANK_METRICS},
                "limit": {"type": "integer", "minimum": 1, "maximum": PER_GROUP_CAP,
                          "description": "airports per size tier"},
                "w_passenger_growth": {"type": "number", "minimum": 0, "description": (
                    f"optional custom weight for passenger growth (default {_w['passenger_growth']}), only with metric score; given "
                    "weights replace the defaults and all four are normalized to sum to 1")},
                "w_load_factor": {"type": "number", "minimum": 0,
                                  "description": f"optional custom weight for load factor (default {_w['load_factor']}), only with metric score"},
                "w_flight_growth": {"type": "number", "minimum": 0,
                                    "description": f"optional custom weight for flight growth (default {_w['flight_growth']}), only with metric score"},
                "w_congestion": {"type": "number", "minimum": 0,
                                 "description": f"optional custom weight for congestion (default {_w['congestion']}), only with metric score"},
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
    {
        "name": "check_data_updates",
        "description": (
            "Check whether the public BTS sources have months newer than our data window. Quick and changes "
            "nothing. Use when the user asks whether the data is current or newer data exists."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "refresh_data",
        "description": (
            "Download the BTS and OurAirports files again and rebuild our data, about 75 seconds. Only when the "
            "user asks to update or refresh the data. Does nothing when no newer month exists; on any failure the "
            "old data is kept. Returns the old and new data windows."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "faa_airport_status",
        "description": (
            "Current FAA airport status: ground stops, ground delay programs, arrival and departure delays and "
            "closures. Live (minutes old) with its own update time; context only, never part of the score, label "
            "or report. Airline-affecting events are in events; closures to non-scheduled general aviation only "
            "are in general_aviation_only and do not affect airlines; requested airports with nothing listed are in "
            "nothing_listed. The feed lists only FAA programs and delays above its reporting threshold, so nothing "
            "listed does not mean no delays."
        ),
        "parameters": {
            "type": "object",
            "properties": {"codes": {"type": "array", "items": {"type": "string"},
                                     "description": "3-letter airport codes; omit for every airport the feed lists"}},
        },
    },
    {
        "name": "airport_trend",
        "description": (
            "One airport's metric month by month: each month's value, the same month a year earlier and the change, "
            "plus the highest and lowest month, the last 12 months against the 12 before, and a seasonal profile, all "
            "computed. Use for month-by-month, seasonal or since-when questions about one airport. Needs an airport code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "metric": {"type": "string", "enum": ["passengers", "departures", "load_factor", "delay_rate",
                                                      "system_delay_rate"], "description": "default passengers"},
                "months": {"type": "integer", "minimum": 6, "maximum": 90,
                           "description": "months ending at the latest month (delay metrics start 2024-01); default 24"},
            },
            "required": ["code"],
        },
    },
]
