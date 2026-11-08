"""Build the `airport_month` serving table: T-100 airport-month volumes joined to delay causes.

Delay rows are per carrier; they are summed per airport and month and joined on the airport code.
An airport-month with no delay rows has null delay columns and `has_delay_data` false (unknown, never zero).
"""
from pathlib import Path

import pandas as pd

COLUMNS = ["code", "year", "month", "ym", "departures", "passengers", "seats", "freight_lbs", "arr_flights",
           "arr_del15", "nas_ct", "weather_ct", "carrier_ct", "late_aircraft_ct", "security_ct", "arr_cancelled",
           "arr_delay_min", "has_delay_data"]
T100_COLUMNS = {"total_departures": "departures", "total_passengers": "passengers", "total_seats": "seats",
                "total_freight_lbs": "freight_lbs"}
DELAY_COLUMNS = ["arr_flights", "arr_del15", "nas_ct", "weather_ct", "carrier_ct", "late_aircraft_ct",
                 "security_ct", "arr_cancelled", "arr_delay"]


def read_t100_summary(path: Path | str, start_year: int) -> pd.DataFrame:
    """T-100 rows from `start_year` on, keyed by code and ym."""
    t = pd.read_csv(path, low_memory=False, usecols=["origin_airport_code", "reporting_month", *T100_COLUMNS])
    when = pd.to_datetime(t["reporting_month"].str[:10])
    t = t.assign(code=t["origin_airport_code"].str.strip().str.upper(),
                 year=when.dt.year.astype(int), month=when.dt.month.astype(int))
    t = t[t["year"] >= start_year].rename(columns=T100_COLUMNS)
    t["ym"] = t["year"] * 100 + t["month"]
    return t[["code", "year", "month", "ym", *T100_COLUMNS.values()]]


def read_delay(path: Path | str) -> pd.DataFrame:
    """Delay causes summed per airport code and ym."""
    d = pd.read_csv(path, low_memory=False)
    d["ym"] = d["year"].astype(int) * 100 + d["month"].astype(int)
    d["code"] = d["airport"].str.strip().str.upper()
    out = d.groupby(["code", "ym"], as_index=False)[DELAY_COLUMNS].sum(min_count=1)
    return out.rename(columns={"arr_delay": "arr_delay_min"})


def build_airport_month(t100_path: Path | str, delay_path: Path | str, start_year: int) -> tuple[pd.DataFrame, dict]:
    """Return (airport_month table, latest month in each source)."""
    t = read_t100_summary(t100_path, start_year)
    d = read_delay(delay_path)
    df = t.merge(d, on=["code", "ym"], how="left", validate="many_to_one")
    df["has_delay_data"] = df["arr_flights"].notna()
    latest = {"t100_latest_ym": int(t["ym"].max()), "delay_latest_ym": int(d["ym"].max())}
    return df[COLUMNS].sort_values(["code", "ym"]).reset_index(drop=True), latest
