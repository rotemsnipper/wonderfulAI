"""Month-by-month series for one airport and one metric, with prior-year changes and a seasonal profile.

Rates come from summed counts (load factor = passengers / seats, delay rates = delayed / arrivals), also
over a year or a calendar month across years. A month without delay data is unknown (None), never zero.
"""
import pandas as pd

from backend.scoring import formulas as f
from backend.tools.store import Store, _shift

# metric -> (numerator column, denominator column or None for a plain count)
METRICS = {
    "passengers": ("passengers", None),
    "departures": ("departures", None),
    "load_factor": ("passengers", "seats"),
    "delay_rate": ("arr_del15", "arr_flights"),
    "system_delay_rate": ("nas_ct", "arr_flights"),
}
DELAY_METRICS = {"delay_rate", "system_delay_rate"}


def is_rate(metric: str) -> bool:
    return METRICS[metric][1] is not None


def available_months(store: Store, metric: str) -> list[int]:
    """The unbroken run of months in the data that ends at the latest month; for a delay metric it starts at
    the first month of that run with any delay data."""
    present = set(store.airport_month["ym"].astype(int))
    run, ym = [], store.latest_ym
    while ym in present:
        run.append(ym)
        ym = _shift(ym, -1)
    run.reverse()
    if metric in DELAY_METRICS:
        am = store.airport_month
        delay_yms = set(am.loc[am["has_delay_data"].astype(bool), "ym"].astype(int))
        run = run[next((i for i, m in enumerate(run) if m in delay_yms), len(run)):]
    return run


def _totals(rows: pd.DataFrame, metric: str) -> tuple[float, float | None] | None:
    """Summed numerator and denominator over the rows that carry the metric; None when no row does."""
    num, den = METRICS[metric]
    if metric in DELAY_METRICS:
        rows = rows[rows["has_delay_data"].astype(bool)]
    if rows.empty:
        return None
    return float(rows[num].sum()), (float(rows[den].sum()) if den else None)


def _value(totals, metric: str, months_count: int = 1) -> float | None:
    """The metric over summed totals; a count is averaged over `months_count`."""
    if totals is None:
        return None
    num, den = totals
    if metric == "load_factor":
        return f.load_factor(num, den)
    if is_rate(metric):
        return f.rate_pct(num, den)
    return num / months_count


def change(current: float | None, prior: float | None, metric: str) -> float | None:
    """Percent change for a count, percentage points for a rate (load factor is a fraction, so x100)."""
    if current is None or prior is None:
        return None
    if metric == "load_factor":
        return (current - prior) * 100
    if is_rate(metric):
        return current - prior
    return f.growth_pct(current, prior)


def trend(store: Store, code: str, metric: str, months: list[int]) -> dict:
    """Monthly values, prior-year values and changes for `months`, plus the summary over them."""
    rows = store.airport_month[store.airport_month["code"] == code]
    by_ym = {int(ym): g for ym, g in rows.groupby("ym")}

    def month_value(ym: int) -> float | None:
        g = by_ym.get(ym)
        return None if g is None else _value(_totals(g, metric), metric)

    series = []
    for ym in months:
        value, prior = month_value(ym), month_value(_shift(ym, -12))
        series.append({"ym": ym, "value": value, "prior_year_value": prior,
                       "change_vs_prior_year": change(value, prior, metric)})

    known = [x for x in series if x["value"] is not None]
    highest = max(known, key=lambda x: x["value"], default=None)  # ties: the earliest month
    lowest = min(known, key=lambda x: x["value"], default=None)

    def over(yms: list[int]) -> float | None:
        part = rows[rows["ym"].isin(yms)]
        totals = _totals(part, metric)
        return None if totals is None else _value(totals, metric, months_count=1)

    first_last = None
    if len(months) >= 24:
        first, last = months[:12], months[-12:]
        a, b = over(first), over(last)
        first_last = {"first_months": first, "last_months": last, "first_value": a, "last_value": b,
                      "change": change(b, a, metric)}

    years = len(months) // 12
    seasonal = None
    if years:
        span = months[-12 * years:]
        profile = []
        for cal in range(1, 13):
            yms = [m for m in span if m % 100 == cal]
            part = rows[rows["ym"].isin(yms)]
            if metric in DELAY_METRICS:
                part = part[part["has_delay_data"].astype(bool)]
            profile.append({"calendar_month": cal, "value": _value(_totals(part, metric), metric, len(part) or 1),
                            "years_with_data": int(part["ym"].nunique())})
        seasonal = {"years": years, "months": span, "profile": profile}

    return {"series": series, "highest": highest, "lowest": lowest, "first_vs_last_12": first_last,
            "seasonal": seasonal, "unknown_months": len(series) - len(known)}
