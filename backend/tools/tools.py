"""The four agent tools and the dispatcher.

Every tool returns the shared envelope (envelope.py) or {error, valid_options}. All numbers the model may
quote are computed here: raw values, display strings, and differences and ratios between airports
(computed from the displayed rounding, in the metric's own unit).
"""
import inspect
import logging
from functools import cached_property

from backend.config import SERVING_DIR
from backend.scoring import formulas, label, metrics
from backend.scoring.robustness import robustness
from backend.scoring.score import score_all
from backend.scoring.warnings import airport_warnings, sort_warnings
from backend.tools.envelope import DataQuality, Definition, Envelope, Meta, error_result
from backend.tools.resolver import Resolver
from backend.tools.store import Store, load_store

log = logging.getLogger(__name__)

REGIONS = {
    "new_england": ["CT", "ME", "MA", "NH", "RI", "VT"],
}
RANK_METRICS = ["score", "passenger_growth", "flight_growth", "load_factor", "congestion", "delay_rate", "passengers"]
PER_GROUP_CAP = 10
GROWTH_SINCE_BASELINE = {"compound_growth_pct_per_year", "departures_compound_growth_pct_per_year"}
TOTAL_CAP = 30
MAX_COMPARE = 5
NOT_AVAILABLE = ("costs, ROI or construction prices; routes between two cities; gate or terminal floor area; "
                 "live or current-day data; airports outside the US")


# ---------- formatting ----------

def _r(x, nd=4):
    return None if x is None else round(float(x), nd)


def fmt(kind: str, v) -> str | None:
    if v is None:
        return None
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "fraction_pct":
        return f"{v * 100:.1f}%"
    if kind == "signed_pct":
        return f"{v:+.1f}%"
    if kind == "count":
        return f"{v / 1e6:.1f} million" if abs(v) >= 1e6 else f"{v:,.0f}"
    if kind == "score":
        return f"{v:.1f}"
    return str(v)


def _shown(kind: str, v) -> float | None:
    """The number as displayed (so differences match what the user reads)."""
    if v is None:
        return None
    if kind in ("pct", "signed_pct", "score"):
        return round(v, 1)
    if kind == "fraction_pct":
        return round(v * 100, 1)
    if kind == "count":
        return round(v / 1e6, 1) * 1e6 if abs(v) >= 1e6 else round(v)
    return v


# ---------- context ----------

class Context:
    def __init__(self, store: Store, settings: dict):
        self.store, self.settings = store, settings
        self.resolver = Resolver(store)
        self.airports = store.airports.set_index("code")

    @cached_property
    def scores(self) -> dict:
        return score_all(self.store, self.settings)

    @cached_property
    def median_delay(self) -> float | None:
        return metrics.national_median_delay_rate(self.store)

    def periods(self, long_haul: bool = False) -> dict:
        cur = self.store.window_label("current")
        out = {"t100_summary": cur, "delay_causes": cur, "prior_window": self.store.window_label("prior"),
               "baseline": str(self.store.baseline_year)}
        if long_haul:
            out["t100_segment"] = cur
        return out

    def definitions(self, names: list[str]) -> list[Definition]:
        s, cur = self.settings, self.store.window_label("current")
        catalog = {
            "passengers": ("passengers", "count", "passengers boarding at the airport in the 12-month window, all carriers, domestic plus international", "BTS T-100", None),
            "load_factor": ("load factor", "%", "passengers divided by seats in the window", "BTS T-100", None),
            "compound_growth_pct_per_year": ("passenger growth", "% a year", f"compound annual passenger growth from {self.store.baseline_year} to the current window", "BTS T-100", None),
            "passengers_vs_prior_pct": ("change vs prior year", "%", "passengers in the window vs the 12 months before", "BTS T-100", None),
            "departures_compound_growth_pct_per_year": ("flight growth", "% a year", f"compound annual departures growth from {self.store.baseline_year} to the current window; departures include cargo flights, so at cargo hubs part of the growth can be cargo", "BTS T-100", None),
            "departures_vs_prior_pct": ("departures change vs prior year", "%", "departures in the window vs the 12 months before", "BTS T-100", None),
            "delay_rate_pct": ("delay rate", "%", "share of arriving flights 15+ minutes late", "BTS delay causes", None),
            "system_delay_rate_pct": ("system delay rate", "%", "share of arriving flights delayed by the national aviation system (mostly congestion, includes ordinary weather)", "BTS delay causes", "system delays are mostly, not purely, congestion"),
            "cancel_rate_pct": ("cancellation rate", "%", "cancelled arrivals divided by scheduled arrivals", "BTS delay causes", None),
            "departures_per_usable_runway": ("departures per usable runway", "departures", f"departures in the window divided by open runways of at least {s['usable_runway_min_ft']:,} ft", "BTS T-100, OurAirports", None),
            "total_score": ("capacity-need score", "0-100", label.score_definition(s), "computed", "proxy for profit, not a financial return"),
            "long_haul_share": ("long-haul share", "%", "share of departures at or above the cutoff distance; headline counts scheduled passenger flights (class F), the all-flights share includes cargo and charter", "BTS T-100 segment", None),
            "seat_gap": ("seat gap", "seats", f"extra seats a year needed to bring the load factor down to {s['load_factor_ceiling']:.0%}", "BTS T-100", "lower bound of unmet demand"),
            "excess_delayed_flights": ("excess delayed flights", "flights", "delayed arrivals above the national median delay rate", "BTS delay causes", "lower bound of congestion-related unmet demand"),
        }
        out = []
        for n in names:
            name_label, unit, text, source, proxy = catalog[n]
            period = str(self.store.baseline_year) + " to " + cur if n in GROWTH_SINCE_BASELINE else cur
            out.append(Definition(name=n, label=name_label, unit=unit, definition=text, source=source, period=period, proxy_note=proxy))
        return out

    def quality(self, code: str, warnings: list[dict]) -> DataQuality:
        b = self.scores.get(code)
        level, reason = label.confidence(b, warnings)
        if b is None:
            tier = "thin"
        elif b["data_tier"] != "full":
            tier = "partial"
        else:
            tier = "thin" if level == "low" else "full"
        return DataQuality(tier=tier, confidence=level, reason=reason)


_ctx: Context | None = None


def configure(store: Store | None = None) -> Context:
    """Set the serving data the tools read (tests pass the fixture store); defaults to data/serving.
    Settings are the ones stored with that data."""
    global _ctx
    store = store or load_store(SERVING_DIR)
    _ctx = Context(store, store.settings)
    return _ctx


def ctx() -> Context:
    return _ctx or configure()


# ---------- shared pieces ----------

def _whole(x) -> int | None:
    """Model tool arguments arrive as JSON numbers (10.0); accept whole numbers only."""
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and x.is_integer():
        return int(x)
    return None


def _check_code(c: Context, code) -> str | dict:
    if not isinstance(code, str) or not code.strip():
        return error_result("an airport code is required; use resolve_airport for names", [])
    up = code.strip().upper()
    if up in c.resolver.codes:
        return up
    return error_result(f"unknown airport code {code!r}; call resolve_airport with the name to find the code", [])


def _basics(c: Context, code: str) -> dict:
    a = c.airports.loc[code]
    return {"code": code, "name": a["name"], "city": a["city"], "state": a["state"], "size_tier": a["size_tier"],
            "covered": bool(a["in_universe"]), "runways_usable": int(a["runways_usable"]),
            "runways_total": int(a["runways_total"])}


def _score_block(c: Context, code: str) -> dict:
    b = c.scores.get(code)
    if b is None:
        return {"total_score": None, "note": "not covered: below the passenger threshold, so no score"}
    comps = {x["name"]: {"raw": _r(x["raw_value"]), "percentile": _r(x["percentile"], 1),
                         "contribution": _r(x["contribution"], 1)} for x in b["components"]}
    partial = b["partial_scores"]
    lab = label.label(b, airport_warnings(c.store, code, c.settings), c.settings)
    return {
        "total_score": _r(b["total_score"], 1), "display": fmt("score", b["total_score"]),
        "partial_score": _r(partial["score"], 1) if partial else None,
        "partial_label": partial["label"] if partial else None,
        "passenger_score": _r(b["passenger_score"], 1), "flight_score": _r(b["flight_score"], 1),
        "components": comps, "effective_weights": {k: _r(v, 3) for k, v in b["effective_weights"].items()},
        "data_tier": b["data_tier"],
        "potential": lab["potential"], "confidence": lab["confidence"], "recommendation": lab["recommendation"],
        "strengths": [{**x, "percentile": _r(x["percentile"], 1)} for x in lab["strengths"]],
        "weaknesses": [{**x, "percentile": _r(x["percentile"], 1)} for x in lab["weaknesses"]],
    }


def _metrics_block(c: Context, code: str) -> dict:
    st = c.store
    t = metrics.window_totals(st, code)
    g = metrics.growth(st, code)
    k = metrics.congestion(st, code)
    raw = {
        "passengers": t["passengers"], "seats": t["seats"], "departures": t["departures"],
        "load_factor": formulas.load_factor(t["passengers"], t["seats"]),
        "compound_growth_pct_per_year": g["compound_growth_pct_per_year"],
        "passengers_vs_prior_pct": g["passengers_vs_prior_pct"],
        "departures_compound_growth_pct_per_year": g["departures_compound_growth_pct_per_year"],
        "departures_vs_prior_pct": g["departures_vs_prior_pct"],
        "delay_rate_pct": k["delay_rate_pct"], "system_delay_rate_pct": k["system_delay_rate_pct"],
        "cancel_rate_pct": k["cancel_rate_pct"], "departures_per_usable_runway": k["departures_per_usable_runway"],
        "arrivals": k["arrivals"],
    }
    kinds = METRIC_KINDS
    return {
        "values": {n: _r(v) for n, v in raw.items()},
        "display": {n: fmt(kinds.get(n, "count"), v) for n, v in raw.items() if v is not None},
        "delay_note": k["note"],
    }


METRIC_KINDS = {
    "passengers": "count", "seats": "count", "departures": "count", "arrivals": "count", "load_factor": "fraction_pct",
    "compound_growth_pct_per_year": "signed_pct", "passengers_vs_prior_pct": "signed_pct",
    "departures_compound_growth_pct_per_year": "signed_pct", "departures_vs_prior_pct": "signed_pct", "delay_rate_pct": "pct",
    "system_delay_rate_pct": "pct", "cancel_rate_pct": "pct", "departures_per_usable_runway": "count",
    "total_score": "score",
}


def _warnings(c: Context, codes: list[str]) -> list[dict]:
    return sort_warnings([w for code in codes for w in airport_warnings(c.store, code, c.settings)])


def _envelope(tool: str, inputs: dict, result: dict, codes: list[str], defs: list[str], *, long_haul=False,
              proxy=False, notes=None) -> dict:
    c = ctx()
    warnings = _warnings(c, codes)
    return Envelope(
        tool=tool, inputs=inputs, result=result, definitions=c.definitions(defs), warnings=warnings,
        data_quality={code: c.quality(code, warnings) for code in codes}, notes=notes or [],
        meta=Meta(airports=codes, uses_proxy=proxy, periods=c.periods(long_haul),
                  score_version=c.settings["score_version"]),
    ).to_dict()


# ---------- tools ----------

def resolve_airport(query: str) -> dict:
    c = ctx()
    r = c.resolver.resolve(query)
    codes = [x["code"] for x in r["candidates"]]
    return Envelope(tool="resolve_airport", inputs={"query": query}, result=r,
                    meta=Meta(airports=codes, resolved_by_default=bool(r.get("resolved_by_default")))).to_dict()


def rank_airports(region: str | None = None, state: str | None = None, size_tier: str | None = None,
                  metric: str = "score", limit: int = PER_GROUP_CAP) -> dict:
    c = ctx()
    tiers = list(c.settings["size_bands"])
    if region is not None and region not in REGIONS:
        return error_result(f"unknown region {region!r}", list(REGIONS))
    states = sorted(set(c.airports["state"]))
    if state is not None:
        state = str(state).strip().upper()
        if state not in states:
            return error_result(f"unknown state {state!r}; use the two-letter code", states)
        if region is not None and state not in REGIONS[region]:
            return error_result(f"state {state} is not in region {region}; give one or the other", [])
    if size_tier is not None and size_tier not in tiers + ["all"]:
        return error_result(f"unknown size tier {size_tier!r}", tiers + ["all"])
    if metric not in RANK_METRICS:
        return error_result(f"unknown metric {metric!r}", RANK_METRICS)
    limit = _whole(limit)
    if limit is None or not 1 <= limit <= PER_GROUP_CAP:
        return error_result(f"limit must be a whole number from 1 to {PER_GROUP_CAP}", [])

    pool = [code for code in c.scores]
    if region:
        pool = [x for x in pool if c.airports.loc[x, "state"] in REGIONS[region]]
    if state:
        pool = [x for x in pool if c.airports.loc[x, "state"] == state]
    if size_tier and size_tier != "all":
        pool = [x for x in pool if c.airports.loc[x, "size_tier"] == size_tier]
    if not pool:
        return error_result("no covered airports match these filters", [])

    mblocks = {x: _metrics_block(c, x) for x in pool}
    key_name = {"score": "total_score", "passenger_growth": "compound_growth_pct_per_year",
                "flight_growth": "departures_compound_growth_pct_per_year", "load_factor": "load_factor",
                "congestion": "system_delay_rate_pct", "delay_rate": "delay_rate_pct", "passengers": "passengers"}[metric]

    def value(x):
        return c.scores[x]["total_score"] if metric == "score" else mblocks[x]["values"][key_name]

    ranked = sorted([x for x in pool if value(x) is not None], key=lambda x: (-value(x), x))
    unranked = sorted(x for x in pool if value(x) is None)
    rank_of = {x: i + 1 for i, x in enumerate(ranked)}

    def row(x):
        out = {**_basics(c, x), "rank": rank_of.get(x), "value": _r(value(x), 4),
               "display": fmt(METRIC_KINDS[key_name], value(x)), "metrics": mblocks[x]["display"]}
        if metric == "score":
            out["score"] = _score_block(c, x)
        return out

    groups, shown, cut = {}, 0, []
    for tier in tiers:
        members = [x for x in ranked if c.airports.loc[x, "size_tier"] == tier]
        keep = members[: min(limit, TOTAL_CAP - shown)]
        cut += members[len(keep):]
        shown += len(keep)
        if keep:
            groups[tier] = [row(x) for x in keep]

    def not_ranked(x):
        partial = c.scores[x]["partial_scores"] if metric == "score" else None
        if partial:
            return {"code": x, "reason": f"partial score: {partial['label']}", "partial_score": _r(partial["score"], 1)}
        return {"code": x, "reason": f"{key_name} not available", "partial_score": None}

    result = {
        "metric": metric, "ranked_by": key_name, "filters": {"region": region, "state": state, "size_tier": size_tier},
        "covered_airports_in_filter": len(pool), "groups": groups, "list_was_cut": bool(cut), "cut_airports": cut,
        "not_ranked": [not_ranked(x) for x in unranked],
        "note": "Ranks are within the filter; size tiers are shown for grouping and are not part of the score.",
    }
    shown_codes = [r["code"] for rows in groups.values() for r in rows]
    if metric == "score":
        rb = robustness([c.scores[x] for x in ranked], c.settings["weights"], c.settings)
        result["robustness"] = {
            "summary": rb["summary"], "draws": rb["draws"], "top_k": rb["top_k"],
            "per_airport": {x: {**v, "top_k_share_pct": round(v["top_k_share"] * 100)}
                            for x, v in rb["per_airport"].items() if x in shown_codes},
        }
    codes = shown_codes + unranked
    defs = (["total_score", "compound_growth_pct_per_year", "load_factor", "departures_compound_growth_pct_per_year",
             "system_delay_rate_pct"] if metric == "score" else [key_name])
    return _envelope("rank_airports", {"region": region, "state": state, "size_tier": size_tier, "metric": metric, "limit": limit},
                     result, codes, defs)


COMPARE_METRICS = ["passengers", "load_factor", "compound_growth_pct_per_year", "passengers_vs_prior_pct",
                   "departures_compound_growth_pct_per_year",
                   "delay_rate_pct", "system_delay_rate_pct", "cancel_rate_pct", "departures_per_usable_runway"]
TOTALS = {"passengers", "departures_per_usable_runway"}


def compare_airports(codes: list[str]) -> dict:
    c = ctx()
    if not isinstance(codes, list) or not 2 <= len(codes) <= MAX_COMPARE:
        return error_result(f"give 2 to {MAX_COMPARE} airport codes", [])
    checked = []
    for code in codes:
        r = _check_code(c, code)
        if isinstance(r, dict):
            return r
        checked.append(r)
    if len(set(checked)) != len(checked):
        return error_result("the same airport was given twice", [])
    blocks = {x: _metrics_block(c, x) for x in checked}
    airports = [{**_basics(c, x), "metrics": blocks[x]["values"], "display": blocks[x]["display"],
                 "score": _score_block(c, x), "delay_note": blocks[x]["delay_note"]} for x in checked]
    base = checked[0]
    diffs = []
    for other in checked[1:]:
        for m in COMPARE_METRICS:
            kind = METRIC_KINDS[m]
            a, b = _shown(kind, blocks[base]["values"][m]), _shown(kind, blocks[other]["values"][m])
            if a is None or b is None:
                diffs.append({"metric": m, "a": base, "b": other, "difference": None, "ratio": None, "note": "not available for one airport"})
                continue
            unit = "percentage points" if kind in ("pct", "signed_pct", "fraction_pct") else "count"
            diffs.append({"metric": m, "a": base, "b": other, "a_value": a, "b_value": b,
                          "difference": round(a - b, 1) if unit != "count" else round(a - b),
                          "difference_unit": unit, "ratio": round(a / b, 2) if b else None})
    tiers = {c.airports.loc[x, "size_tier"] for x in checked}
    notes = []
    if len(tiers) > 1:
        notes.append("These airports are in different size tiers: compare rates and shares (delay rate, load factor, growth); "
                     "totals such as passengers mostly reflect size.")
    if not all(c.airports.loc[x, "in_universe"] for x in checked):
        notes.append("At least one airport is below the covered threshold and has no score.")
    result = {"airports": airports, "differences": diffs, "differences_basis": f"first airport ({base}) minus each other airport, from displayed rounding",
              "size_tiers_differ": len(tiers) > 1}
    return _envelope("compare_airports", {"codes": checked}, result, checked,
                     ["delay_rate_pct", "system_delay_rate_pct", "cancel_rate_pct", "departures_per_usable_runway",
                      "load_factor", "compound_growth_pct_per_year", "passengers_vs_prior_pct",
                      "departures_compound_growth_pct_per_year", "passengers", "total_score"],
                     notes=notes)


def airport_profile(code: str, long_haul_cutoff_mi: int | None = None) -> dict:
    c = ctx()
    r = _check_code(c, code)
    if isinstance(r, dict):
        return r
    code = r
    cutoffs = c.settings["long_haul_cutoffs"]
    if long_haul_cutoff_mi is not None:
        long_haul_cutoff_mi = _whole(long_haul_cutoff_mi)
        if long_haul_cutoff_mi not in cutoffs:
            return error_result(f"long-haul cutoff must be one of {cutoffs} miles", cutoffs)
    s = c.settings
    block = _metrics_block(c, code)
    lh = metrics.long_haul(c.store, code, s)
    headline_cut = long_haul_cutoff_mi or lh["default_cutoff_mi"]
    head = next(x for x in lh["table"] if x["cutoff_mi"] == headline_cut)
    long_haul = {
        "headline_cutoff_mi": headline_cut,
        "headline_passenger_flights_pct": _r(head["passenger_flights_pct"], 2),
        "headline_all_flights_pct": _r(head["all_flights_pct"], 2),
        "display": {"passenger_flights": fmt("pct", head["passenger_flights_pct"]), "all_flights": fmt("pct", head["all_flights_pct"])},
        "table": [{"cutoff_mi": x["cutoff_mi"], "passenger_flights_pct": _r(x["passenger_flights_pct"], 2),
                   "all_flights_pct": _r(x["all_flights_pct"], 2)} for x in lh["table"]],
        "cargo_share_of_departures_pct": _r(lh["cargo_share_of_departures_pct"], 2),
        "basis": f"{lh['headline_basis']}; all flights: {lh['all_flights_basis']}",
    }
    u = metrics.unmet_demand(c.store, code, s, c.median_delay)
    unmet = {
        "seat_gap": _r(u["seat_gap"], 0), "seat_gap_display": fmt("count", u["seat_gap"]),
        "seat_gap_interpretation": u["seat_gap_interpretation"],
        "excess_delayed_flights": _r(u["excess_delayed_flights"], 0),
        "excess_delayed_flights_display": fmt("count", u["excess_delayed_flights"]),
        "national_median_delay_rate_pct": _r(u["national_median_delay_rate_pct"], 2),
        "delayed_flights": _r(u["delayed_flights"], 0), "arrivals": _r(u["arrivals"], 0),
        "delay_cause_shares": [{"cause": x["label"], "share_pct": _r(x["share_pct"], 1)} for x in u["delay_cause_shares"] or []] or None,
        "lower_bound_note": u["lower_bound_note"],
    }
    result = {**_basics(c, code), "metrics": block["values"], "display": block["display"],
              "delay_note": block["delay_note"],
              "score": _score_block(c, code), "long_haul": long_haul, "unmet_demand": unmet}
    return _envelope("airport_profile", {"code": code, "long_haul_cutoff_mi": long_haul_cutoff_mi}, result, [code],
                     ["passengers", "load_factor", "compound_growth_pct_per_year", "departures_compound_growth_pct_per_year",
                      "delay_rate_pct", "system_delay_rate_pct",
                      "departures_per_usable_runway", "long_haul_share", "seat_gap", "excess_delayed_flights", "total_score"],
                     long_haul=True, proxy=True)


TOOLS = {
    "resolve_airport": resolve_airport,
    "rank_airports": rank_airports,
    "compare_airports": compare_airports,
    "airport_profile": airport_profile,
}


def call(name: str, args: dict | None) -> dict:
    """Run one tool by name. Never raises: bad input and internal failures come back as {error, valid_options}."""
    fn = TOOLS.get(name)
    if fn is None:
        return error_result(f"unknown tool {name!r}", list(TOOLS))
    args = args or {}
    if not isinstance(args, dict):
        return error_result("tool arguments must be an object", [])
    params = inspect.signature(fn).parameters
    unknown = sorted(set(args) - set(params))
    if unknown:
        return error_result(f"unsupported argument(s) for {name}: {', '.join(unknown)}", list(params))
    missing = [p for p, v in params.items() if v.default is inspect.Parameter.empty and p not in args]
    if missing:
        return error_result(f"missing argument(s) for {name}: {', '.join(missing)}", list(params))
    try:
        return fn(**args)
    except Exception as e:  # the agent loop must never see an exception from a tool
        log.exception("tool %s failed", name)
        return error_result(f"internal error in {name}: {type(e).__name__}", [])
