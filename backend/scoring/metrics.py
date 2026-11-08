"""Domain metrics per airport: window totals, congestion, long-haul and unmet demand.

Rates come from summed counts over the window (never averages of monthly rates). Delay rates use the
months that have delay data; volume totals use every month present.
"""
import math

import pandas as pd

from backend.scoring import formulas as f
from backend.tools.store import Store

PASSENGER_CLASSES = ("F",)
ALL_CLASSES = ("F", "G", "L", "P")
CARGO_CLASSES = ("G", "P")
DELAY_CAUSES = {
    "nas_ct": "national aviation system (mostly congestion, includes ordinary weather)",
    "carrier_ct": "airline",
    "late_aircraft_ct": "late-arriving aircraft",
    "weather_ct": "extreme weather",
    "security_ct": "security",
}
LOWER_BOUND_NOTE = (
    "Lower bound: a constrained airport never schedules the flights that would reveal its full demand."
)
NO_DELAY_DATA = "no delay data reported for this airport (unknown, not zero)"


def _num(x) -> float | None:
    if x is None or (isinstance(x, float) and math.isnan(x)) or x is pd.NA:
        return None
    return float(x)


def _sum(df: pd.DataFrame, col: str) -> float | None:
    return _num(df[col].sum(min_count=1)) if len(df) else None


def window_totals(store: Store, code: str, which: str = "current") -> dict:
    """Summed volumes and delay counts for one airport in a window."""
    rows = store.months(which, [code])
    delay_rows = rows[rows["has_delay_data"].astype(bool)]
    out = {"has_delay_data": bool(len(delay_rows))}
    for col in ("passengers", "seats", "departures", "freight_lbs"):
        out[col] = _sum(rows, col)
    for col in ("arr_flights", "arr_del15", "arr_cancelled", "arr_delay_min", *DELAY_CAUSES):
        out[col] = _sum(delay_rows, col)
    return out


def _airport_row(store: Store, code: str) -> pd.Series:
    match = store.airports[store.airports["code"] == code]
    if match.empty:
        raise KeyError(f"unknown airport code {code!r}")
    return match.iloc[0]


def delay_rate(totals: dict) -> float | None:
    return f.rate_pct(totals["arr_del15"], totals["arr_flights"])


def system_delay_rate(totals: dict) -> float | None:
    return f.rate_pct(totals["nas_ct"], totals["arr_flights"])


def national_median_delay_rate(store: Store) -> float | None:
    """Median current-window delay rate over universe airports with delay data."""
    codes = store.airports.loc[store.airports["in_universe"].astype(bool), "code"]
    return f.median(delay_rate(window_totals(store, code)) for code in codes)


def growth(store: Store, code: str) -> dict:
    """Compound growth from the baseline year and last-year change, both in percent, for passengers and
    departures. Departures include cargo flights, so at cargo hubs flight growth can come from cargo."""
    cur, prior, base = (window_totals(store, code, w) for w in ("current", "prior", "baseline"))
    years = store.years_since_baseline()
    return {
        "compound_growth_pct_per_year": f.compound_growth_pct(cur["passengers"], base["passengers"], years),
        "baseline_year": store.baseline_year,
        "passengers_vs_prior_pct": f.growth_pct(cur["passengers"], prior["passengers"]),
        "departures_compound_growth_pct_per_year": f.compound_growth_pct(cur["departures"], base["departures"], years),
        "departures_vs_prior_pct": f.growth_pct(cur["departures"], prior["departures"]),
    }


def congestion(store: Store, code: str) -> dict:
    """Delay, system-delay and cancellation rates, plus departures per usable runway."""
    t = window_totals(store, code)
    usable = _num(_airport_row(store, code)["runways_usable"])
    return {
        "arrivals": t["arr_flights"],
        "delay_rate_pct": delay_rate(t),
        "system_delay_rate_pct": system_delay_rate(t),
        "cancel_rate_pct": f.rate_pct(t["arr_cancelled"], t["arr_flights"]),
        "departures": t["departures"],
        "runways_usable": usable,
        "departures_per_usable_runway": t["departures"] / usable if t["departures"] is not None and usable else None,
        "note": None if t["has_delay_data"] else NO_DELAY_DATA,
    }


def long_haul(store: Store, code: str, settings: dict) -> dict:
    """Long-haul share of departures at each configured cutoff, on the passenger and all-flight bases."""
    routes = store.routes_in("current", [code])
    rows = list(routes[["distance_mi", "departures", "class"]].itertuples(index=False, name=None))
    table = [
        {
            "cutoff_mi": c,
            "passenger_flights_pct": f.long_haul_share(rows, c, PASSENGER_CLASSES),
            "all_flights_pct": f.long_haul_share(rows, c, ALL_CLASSES),
        }
        for c in settings["long_haul_cutoffs"]
    ]
    total = sum(d for _, d, cls in rows if cls in ALL_CLASSES)
    cargo = sum(d for _, d, cls in rows if cls in CARGO_CLASSES)
    return {
        "default_cutoff_mi": settings["long_haul_default"],
        "headline_basis": "scheduled passenger flights (class F), share of departures",
        "all_flights_basis": "all departures including cargo and charter (classes F, G, L, P)",
        "table": table,
        "cargo_share_of_departures_pct": cargo / total * 100 if total else None,
    }


def unmet_demand(store: Store, code: str, settings: dict, median_rate_pct: float | None = None) -> dict:
    """Seat gap, excess delayed flights vs the national median and delay-cause shares; all lower bounds."""
    t = window_totals(store, code)
    ceiling = settings["load_factor_ceiling"]
    gap = f.seat_gap(t["passengers"], t["seats"], ceiling)
    if gap is None:
        gap_text = "seat gap unknown: passenger or seat data missing"
    elif gap == 0:
        gap_text = (
            f"zero seat gap: seats offered already keep the load factor at or below {ceiling:.0%}; "
            "this is a measured result, not missing data"
        )
    else:
        gap_text = f"about {gap:,.0f} more seats a year would be needed to bring the load factor down to {ceiling:.0%}"
    if median_rate_pct is None:
        median_rate_pct = national_median_delay_rate(store)
    causes = None
    if t["has_delay_data"]:
        cause_total = sum(t[c] for c in DELAY_CAUSES)
        causes = sorted(({"cause": c, "label": label, "share_pct": t[c] / cause_total * 100}
                         for c, label in DELAY_CAUSES.items()), key=lambda x: -x["share_pct"]) if cause_total else None
    return {
        "load_factor": f.load_factor(t["passengers"], t["seats"]),
        "seat_gap": gap,
        "seat_gap_interpretation": gap_text,
        "excess_delayed_flights": f.excess_delayed_flights(t["arr_del15"], t["arr_flights"], median_rate_pct),
        "national_median_delay_rate_pct": median_rate_pct,
        "delayed_flights": t["arr_del15"],
        "arrivals": t["arr_flights"],
        "delay_cause_shares": causes,
        "lower_bound_note": LOWER_BOUND_NOTE,
    }
