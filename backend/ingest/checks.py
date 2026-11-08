"""Build-stopping checks on the serving tables. Each returns {name, passed, detail}."""
import pandas as pd

# Named airports the sample questions depend on, plus the New England airports above the threshold.
NAMED_AIRPORTS = ["LAX", "SNA", "ANC", "SFO", "BOS", "BDL", "PVD", "MHT", "PWM", "BTV", "BGR", "HVN"]
NATURAL_KEYS = {
    "airports": ["code"],
    "airport_month": ["code", "ym"],
    "routes": ["code", "year", "month", "dest", "dest_country", "distance_mi", "class"],
}
RECONCILE_TOLERANCE = 0.005


def _result(name: str, passed: bool, detail) -> dict:
    return {"name": name, "passed": bool(passed), "detail": detail}


def check_duplicate_keys(tables: dict[str, pd.DataFrame]) -> dict:
    dupes = {name: int(df.duplicated(NATURAL_KEYS[name]).sum()) for name, df in tables.items() if name in NATURAL_KEYS}
    return _result("duplicate_keys", not any(dupes.values()), dupes)


def check_named_airports(airports: pd.DataFrame, airport_month: pd.DataFrame, months: list[int],
                         named: list[str] = NAMED_AIRPORTS) -> dict:
    """Each named airport is in the airports table, in the universe, and has passengers in every window month."""
    problems = {}
    in_universe = set(airports.loc[airports["in_universe"].astype(bool), "code"])
    window = airport_month[airport_month["ym"].isin(months)]
    for code in named:
        if code not in set(airports["code"]):
            problems[code] = "missing from airports"
        elif code not in in_universe:
            problems[code] = "below the universe threshold"
        else:
            rows = window[window["code"] == code]
            missing = len(months) - rows["ym"].nunique()
            if missing or not (rows["passengers"] > 0).all():
                problems[code] = f"{missing} window month(s) missing or without passengers"
    return _result("named_airports", not problems, problems or f"all {len(named)} present")


def check_reconciliation(airport_month: pd.DataFrame, routes: pd.DataFrame, codes: list[str], months: list[int],
                         tolerance: float = RECONCILE_TOLERANCE) -> dict:
    """T-100 summary departures vs T-100 segment departures per airport over the window, within `tolerance`."""
    s = airport_month[airport_month["ym"].isin(months) & airport_month["code"].isin(codes)]
    s = s.groupby("code")["departures"].sum()
    ym = routes["year"] * 100 + routes["month"]
    g = routes[ym.isin(months) & routes["code"].isin(codes)].groupby("code")["departures"].sum()
    off = {}
    for code in codes:
        a, b = float(s.get(code, 0)), float(g.get(code, 0))
        if a == 0 or abs(b - a) / a > tolerance:
            off[code] = {"summary": a, "segment": b}
    return _result("reconciliation", not off, off or f"{len(codes)} airports within {tolerance:.1%}")


def run_checks(airports: pd.DataFrame, airport_month: pd.DataFrame, routes: pd.DataFrame, months: list[int],
               named: list[str] = NAMED_AIRPORTS) -> list[dict]:
    return [
        check_duplicate_keys({"airports": airports, "airport_month": airport_month, "routes": routes}),
        check_named_airports(airports, airport_month, months, named),
        check_reconciliation(airport_month, routes, named, months),
    ]
