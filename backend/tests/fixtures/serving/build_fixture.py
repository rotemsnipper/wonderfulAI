"""Expand the hand-written fixture spec into serving-contract tables (CSV and parquet).

Every airport has constant monthly values, so any annual figure is 12 x the monthly value.
Periods: current window 2025-08..2026-07, prior window 2024-08..2025-07, baseline calendar 2019.
Run from the repo root:  python backend/tests/fixtures/serving/build_fixture.py
"""
import json
import shutil
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = HERE / "spec"


def months(start_ym: int, end_ym: int) -> list[int]:
    out, y, m = [], start_ym // 100, start_ym % 100
    while y * 100 + m <= end_ym:
        out.append(y * 100 + m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


CURRENT = months(202508, 202607)
PRIOR = months(202408, 202507)
BASELINE = months(201901, 201912)

a = pd.read_csv(SPEC / "airports_spec.csv")
r = pd.read_csv(SPEC / "routes_spec.csv")

# tier bands mirror config/settings.yaml (placeholder values)
BANDS = [("large", 10_000_000), ("medium", 3_000_000), ("small", 1_000_000), ("nonhub", 0)]
UNIVERSE_MIN = 250_000

rows = []
for s in a.itertuples():
    cur_months = CURRENT[-int(s.months_in_window):]
    for ym in cur_months + PRIOR + BASELINE:
        is_cur, is_prior = ym in cur_months, ym in PRIOR
        pax = s.pax_m if is_cur else (s.prior_pax_m if is_prior else s.base_pax_m)
        has_delay = bool(s.has_delay) and (is_cur or is_prior)
        pick = lambda v: (v if has_delay else None)
        rows.append(dict(
            code=s.code, year=ym // 100, month=ym % 100, ym=ym,
            departures=s.dep_m, passengers=pax, seats=s.seats_m, freight_lbs=s.freight_m,
            arr_flights=pick(s.arr_m), arr_del15=pick(s.del15_m), nas_ct=pick(s.nas_m), weather_ct=pick(s.weather_m),
            carrier_ct=pick(s.carrier_m), late_aircraft_ct=pick(s.late_m), security_ct=pick(s.security_m),
            arr_cancelled=pick(s.cancel_m), arr_delay_min=pick(s.delay_min_m),
            has_delay_data=has_delay,
        ))
am = pd.DataFrame(rows)

cur12 = am[am.ym.between(202508, 202607)].groupby("code")["passengers"].sum()
airports = a[["airport_id", "code", "name", "city", "state", "runways_total", "runways_usable"]].copy()
airports["max_runway_ft"] = a["max_runway_ft"]
airports["size_tier"] = [next(t for t, lo in BANDS if cur12[c] >= lo) for c in airports.code]
airports["in_universe"] = [cur12[c] >= UNIVERSE_MIN for c in airports.code]

routes = []
for x in r.itertuples():
    n = int(a.loc[a.code == x.code, "months_in_window"].iloc[0])
    for ym in CURRENT[-n:]:
        cargo = x._5 in ("G", "P")
        routes.append(dict(
            code=x.code, year=ym // 100, month=ym % 100, dest=x.dest, dest_country=x.dest_country,
            distance_mi=x.distance_mi, **{"class": x._5}, departures=x.departures_m,
            passengers=0 if cargo else x.departures_m * 100, seats=0 if cargo else x.departures_m * 130,
            freight_lbs=x.departures_m * 50000 if cargo else 0,
        ))
rt = pd.DataFrame(routes)

manifest = dict(
    note="fixture dataset, not real data",
    periods=dict(t100_summary="2019-01..2019-12, 2024-08..2026-07", delay_causes="2024-08..2026-07", t100_segment="2025-08..2026-07"),
    window=dict(current="2025-08..2026-07", prior="2024-08..2025-07", baseline_year=2019),
    row_counts=dict(airports=len(airports), airport_month=len(am), routes=len(rt)),
    checks=dict(duplicate_keys="pass", named_airports="n/a", reconciliation="n/a"),
    build_date="2026-11-08", config_version="0.1-draft",
)

for name, df in (("airports", airports), ("airport_month", am), ("routes", rt)):
    df.to_csv(HERE / f"{name}.csv", index=False)
    df.to_parquet(HERE / f"{name}.parquet", index=False)
(HERE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
# a serving folder carries the settings it was built with
shutil.copy(HERE.parents[3] / "config" / "settings.yaml", HERE / "settings.yaml")
print({k: len(v) for k, v in (("airports", airports), ("airport_month", am), ("routes", rt))})
