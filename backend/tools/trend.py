"""The airport_trend tool: one metric month by month for one airport, every change computed here."""
import calendar

from backend.scoring import trend as T
from backend.tools.envelope import Definition, Envelope, Meta, error_result
from backend.tools.tools import METRIC_KINDS, _check_code, _r, _warnings, _whole, ctx, fmt

MIN_MONTHS, MAX_MONTHS = 6, 90
# metric -> (key in the shared definitions catalog and METRIC_KINDS, monthly definition)
METRIC_DEFS = {
    "passengers": ("passengers", "passengers boarding at the airport in the month, all carriers, domestic plus international"),
    "departures": ("departures", "departures performed in the month; includes cargo flights"),
    "load_factor": ("load_factor", "passengers divided by seats in the month"),
    "delay_rate": ("delay_rate_pct", "share of arriving flights 15+ minutes late in the month"),
    "system_delay_rate": ("system_delay_rate_pct", "share of arriving flights in the month delayed by the national aviation system (mostly congestion, includes ordinary weather)"),
}


def _label(ym: int) -> str:
    return f"{ym // 100}-{ym % 100:02d}"


def _span(yms: list[int]) -> str:
    return f"{_label(yms[0])}..{_label(yms[-1])}"


def _change_display(v, metric: str) -> str | None:
    if v is None:
        return None
    return f"{v:+.1f} pp" if T.is_rate(metric) else fmt("signed_pct", v)


def _definition(metric: str, period: str) -> Definition:
    key, text = METRIC_DEFS[metric]
    if key == "departures":
        return Definition(name=metric, label="departures", unit="count", definition=text, source="BTS T-100", period=period)
    base = ctx().definitions([key])[0]
    return base.model_copy(update={"name": metric, "definition": text, "period": period})


def airport_trend(code: str, metric: str = "passengers", months: int = 24) -> dict:
    c = ctx()
    r = _check_code(c, code)
    if isinstance(r, dict):
        return r
    code = r
    if metric not in T.METRICS:
        return error_result(f"unknown metric {metric!r}", list(T.METRICS))
    available = T.available_months(c.store, metric)
    longest = min(len(available), MAX_MONTHS)
    n = _whole(months)
    if n is None or n < MIN_MONTHS:
        return error_result(f"months must be a whole number from {MIN_MONTHS} to {longest}", [])
    notes = []
    if n > longest:
        if longest < len(available):
            notes.append(f"{n} months were asked; a trend shows at most {MAX_MONTHS}, so it covers {longest}.")
        else:
            starts = "delay data starts" if metric in T.DELAY_METRICS else "the monthly data starts"
            notes.append(f"{n} months were asked; {starts} {_label(available[0])}, so the trend covers {longest}.")
        n = longest
    span = available[-n:]
    t = T.trend(c.store, code, metric, span)

    key = METRIC_DEFS[metric][0]
    kind = METRIC_KINDS[key]
    nd = 4 if T.is_rate(metric) else 0

    def point(ym, v):
        return {"month": _label(ym), "value": _r(v, nd), "display": fmt(kind, v)}

    rows = [{**point(x["ym"], x["value"]), "prior_year_value": _r(x["prior_year_value"], nd),
             "prior_year_display": fmt(kind, x["prior_year_value"]),
             "change_vs_prior_year": _r(x["change_vs_prior_year"], 2),
             "change_display": _change_display(x["change_vs_prior_year"], metric)} for x in t["series"]]

    fl = t["first_vs_last_12"]
    first_last = None if fl is None else {
        "first_period": _span(fl["first_months"]), "last_period": _span(fl["last_months"]),
        "first_value": _r(fl["first_value"], nd), "first_display": fmt(kind, fl["first_value"]),
        "last_value": _r(fl["last_value"], nd), "last_display": fmt(kind, fl["last_value"]),
        "change": _r(fl["change"], 2), "change_display": _change_display(fl["change"], metric),
        "basis": "rates from summed counts over each year" if T.is_rate(metric) else "totals over each year",
    }
    se = t["seasonal"]
    seasonal = None if se is None else {
        "years": se["years"], "period": _span(se["months"]),
        "basis": "per calendar month, from summed counts" if T.is_rate(metric) else "average per calendar month",
        "months": [{"month": calendar.month_abbr[x["calendar_month"]], "value": _r(x["value"], nd),
                    "display": fmt(kind, x["value"]), "years_with_data": x["years_with_data"]} for x in se["profile"]],
    }
    if t["unknown_months"]:
        notes.append(f"{t['unknown_months']} of {n} months have no data for this metric: shown as unknown, not zero.")

    result = {
        "code": code, "name": c.airports.loc[code, "name"], "metric": metric,
        "label": _definition(metric, "").label, "months_shown": n, "first_month": _label(span[0]),
        "last_month": _label(span[-1]),
        "change_unit": "percentage points" if T.is_rate(metric) else "percent",
        "months": rows,
        "summary": {
            "highest": t["highest"] and point(t["highest"]["ym"], t["highest"]["value"]),
            "lowest": t["lowest"] and point(t["lowest"]["ym"], t["lowest"]["value"]),
            "first_vs_last_12": first_last, "seasonal_profile": seasonal, "unknown_months": t["unknown_months"],
        },
    }
    period = _span(span)
    warnings = _warnings(c, [code])
    source = "delay_causes" if metric in T.DELAY_METRICS else "t100_summary"
    return Envelope(
        tool="airport_trend", inputs={"code": code, "metric": metric, "months": n}, result=result,
        definitions=[_definition(metric, period)], warnings=warnings,
        data_quality={code: c.quality(code, warnings)}, notes=notes,
        meta=Meta(airports=[code], periods={source: period}, score_version=c.settings["score_version"]),
    ).to_dict()
