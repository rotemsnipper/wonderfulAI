"""Independent recompute of the sample-question figures from the raw files only.

Must not import from backend/. Constants are copied by hand from config/settings.yaml on purpose,
so a config change that is not reflected here shows up as a mismatch in the M2-I acceptance run.

Run from the repo root:  python scripts/recompute/recompute.py
Writes scripts/recompute/expected.json.
"""
import json
import zipfile
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = Path(__file__).resolve().parent / "expected.json"

WINDOW = (202508, 202607)
UNIVERSE_MIN = 250_000
RUNWAY_MIN_FT = 3000
CEILING = 0.85
CUTOFFS = (2000, 2500, 3000)


def in_window(ym: pd.Series) -> pd.Series:
    return ym.between(*WINDOW)


# T-100 summary: volumes per airport in the window
t = pd.read_csv(RAW / "bts_t100_summary" / "t100_by_origin.csv", low_memory=False)
t["ym"] = t["reporting_month"].str[:4].astype(int) * 100 + t["reporting_month"].str[5:7].astype(int)
vol = t[in_window(t["ym"])].groupby("origin_airport_code")[["total_departures", "total_passengers", "total_seats"]].sum()

# Delay causes: per airport in the window
d = pd.read_csv(RAW / "bts_delay_causes" / "Airline_Delay_Cause.csv", low_memory=False)
d["ym"] = d["year"] * 100 + d["month"]
causes = ["nas_ct", "carrier_ct", "late_aircraft_ct", "weather_ct", "security_ct"]
dl = d[in_window(d["ym"])].groupby("airport")[["arr_flights", "arr_del15", "arr_cancelled", *causes]].sum()

# Runways: OurAirports, open, at least 3,000 ft
oa = pd.read_csv(RAW / "ourairports" / "airports.csv", low_memory=False)
rw = pd.read_csv(RAW / "ourairports" / "runways.csv", low_memory=False)
rw = rw[(rw["closed"] == 0) & (rw["length_ft"] >= RUNWAY_MIN_FT)]
ident = oa[(oa["iso_country"] == "US") & (oa["scheduled_service"] == "yes")].drop_duplicates("iata_code").set_index("iata_code")["ident"]


def usable_runways(code: str) -> int:
    return int((rw["airport_ident"] == ident[code]).sum())


expected = {"window": "2025-08..2026-07", "note": "recomputed from raw files with plain pandas; see recompute.py",
            "q2": {}, "q3": {}, "q4": {}}

# Q2: LAX vs SNA congestion
for code in ("LAX", "SNA"):
    v, x = vol.loc[code], dl.loc[code]
    runways = usable_runways(code)
    expected["q2"][code] = {
        "delay_rate_pct": {"value": 100 * x.arr_del15 / x.arr_flights, "formula": "sum(arr_del15) / sum(arr_flights) * 100"},
        "system_delay_rate_pct": {"value": 100 * x.nas_ct / x.arr_flights, "formula": "sum(nas_ct) / sum(arr_flights) * 100"},
        "cancel_rate_pct": {"value": 100 * x.arr_cancelled / x.arr_flights, "formula": "sum(arr_cancelled) / sum(arr_flights) * 100"},
        "load_factor": {"value": v.total_passengers / v.total_seats, "formula": "sum(passengers) / sum(seats)"},
        "runways_usable": {"value": runways, "formula": "open runways >= 3000 ft"},
        "departures_per_usable_runway": {"value": v.total_departures / runways, "formula": "sum(departures) / usable runways"},
    }

# Q3: Anchorage long-haul share of departures, passenger-only (F) and all classes
frames = []
for year in (2025, 2026):
    with zipfile.ZipFile(RAW / "bts_t100_segment" / f"t100_segment_{year}.zip") as z:
        frames.append(pd.read_csv(z.open("T_T100_SEGMENT_ALL_CARRIER.csv"), low_memory=False))
seg = pd.concat(frames)
seg = seg[in_window(seg["YEAR"] * 100 + seg["MONTH"]) & (seg["ORIGIN"] == "ANC")]
for cutoff in CUTOFFS:
    for basis, sub in (("passenger_flights", seg[seg["CLASS"] == "F"]), ("all_flights", seg)):
        share = 100 * sub.loc[sub["DISTANCE"] >= cutoff, "DEPARTURES_PERFORMED"].sum() / sub["DEPARTURES_PERFORMED"].sum()
        expected["q3"][f"{basis}_pct_at_{cutoff}"] = {
            "value": share, "formula": f"departures with DISTANCE >= {cutoff} / all departures, classes {'F' if basis == 'passenger_flights' else 'F,G,L,P'}"}
cargo = seg[seg["CLASS"].isin(["G", "P"])]["DEPARTURES_PERFORMED"].sum() / seg["DEPARTURES_PERFORMED"].sum()
expected["q3"]["cargo_share_of_departures_pct"] = {"value": 100 * cargo, "formula": "departures in classes G,P / all departures"}

# Q4: SFO unmet demand
universe = vol.index[(vol["total_passengers"] >= UNIVERSE_MIN) & vol.index.isin(ident.index)]  # US airports with scheduled service
eligible = dl[dl.index.isin(universe)]
median_rate = float((100 * eligible.arr_del15 / eligible.arr_flights).median())
v, x = vol.loc["SFO"], dl.loc["SFO"]
cause_total = x[causes].sum()
expected["q4"]["SFO"] = {
    "load_factor": {"value": v.total_passengers / v.total_seats, "formula": "sum(passengers) / sum(seats)"},
    "seat_gap": {"value": max(0.0, v.total_passengers / CEILING - v.total_seats), "formula": "max(0, passengers / 0.85 - seats)"},
    "national_median_delay_rate_pct": {"value": median_rate, "formula": "median delay rate over US airports with >= 250k passengers and delay data"},
    "excess_delayed_flights": {"value": max(0.0, x.arr_del15 - x.arr_flights * median_rate / 100), "formula": "max(0, delayed - arrivals * median rate)"},
    "delay_cause_shares_pct": {"value": {c: 100 * x[c] / cause_total for c in causes}, "formula": "cause count / sum of cause counts"},
}


def plain(obj):
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if hasattr(obj, "item"):
        return obj.item()
    return obj


OUT.write_text(json.dumps(plain(expected), indent=2), encoding="utf-8")
print(json.dumps(plain(expected), indent=2))
