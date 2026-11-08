"""Spike: LAX vs SNA on a window aligned across T-100 and delay causes. Reads data/raw, prints a summary."""
from pathlib import Path
import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
t = pd.read_csv(RAW / "bts_t100_summary" / "t100_by_origin.csv", low_memory=False)
t["ym"] = pd.to_datetime(t["reporting_month"]).dt.year * 100 + pd.to_datetime(t["reporting_month"]).dt.month
d = pd.read_csv(RAW / "bts_delay_causes" / "Airline_Delay_Cause.csv", low_memory=False)
d["ym"] = d["year"] * 100 + d["month"]

t_last, d_last = t["ym"].max(), d["ym"].max()
common = min(t_last, d_last)
print("T-100 latest:", t_last, "| delay latest:", d_last, "| latest common month:", common)

def window_end(ym, n=12):
    y, m = divmod(ym, 100)
    k = y * 12 + (m - 1) - (n - 1)
    return (k // 12) * 100 + (k % 12) + 1

lo, hi = window_end(common), common
prior_hi = window_end(common, 13)
prior_lo = window_end(prior_hi)
print("current window:", lo, "-", hi, "| prior window:", prior_lo, "-", prior_hi)

cur = t[(t.ym >= lo) & (t.ym <= hi)].groupby("origin_airport_code")[["total_departures", "total_passengers", "total_seats", "total_freight_lbs"]].sum()
pri = t[(t.ym >= prior_lo) & (t.ym <= prior_hi)].groupby("origin_airport_code")[["total_passengers"]].sum()
cur["load_factor_pct"] = 100 * cur["total_passengers"] / cur["total_seats"]
cur["pax_growth_pct"] = 100 * (cur["total_passengers"] / pri["total_passengers"] - 1)
print("airports in T-100 current window:", len(cur), "| with >=250k passengers:", int((cur.total_passengers >= 250_000).sum()))
print(cur.loc[["LAX", "SNA"]].round(1).T.to_string())

w = d[(d.ym >= lo) & (d.ym <= hi)].groupby("airport")[["arr_flights", "arr_del15", "nas_ct"]].sum()
w["delay_rate_pct"] = 100 * w.arr_del15 / w.arr_flights
w["system_delay_pct"] = 100 * w.nas_ct / w.arr_flights
print("delay airports:", len(w), "| median delay rate %:", round(w.delay_rate_pct.median(), 1), "| median system-delay %:", round(w.system_delay_pct.median(), 1))
print(w.loc[["LAX", "SNA"]].round(1).T.to_string())

for code, usable in (("LAX", 4), ("SNA", 1)):
    dep = cur.loc[code, "total_departures"]
    print(code, "departures per runway/yr (runways counted=%d):" % usable, round(dep / usable))
print("airports in T-100 not in delay file (>=250k pax):", sorted(set(cur[cur.total_passengers >= 250_000].index) - set(w.index))[:15])
