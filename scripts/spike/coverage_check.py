"""Spike: coverage of named airports and the DJT/PBI and HVN gaps."""
from pathlib import Path
import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
t = pd.read_csv(RAW / "bts_t100_summary" / "t100_by_origin.csv", low_memory=False)
t["ym"] = pd.to_datetime(t["reporting_month"]).dt.year * 100 + pd.to_datetime(t["reporting_month"]).dt.month
d = pd.read_csv(RAW / "bts_delay_causes" / "Airline_Delay_Cause.csv", low_memory=False)
d["ym"] = d["year"] * 100 + d["month"]
cur = t[(t.ym >= 202508) & (t.ym <= 202607)].groupby("origin_airport_code")["total_passengers"].sum()
ne = ["BOS", "PVD", "BDL", "MHT", "PWM", "BTV", "BGR", "HVN", "ORH", "ACK", "HYA", "PSM"]
rows = [(c, int(cur.get(c, 0)), int(d[d.airport == c].shape[0])) for c in ne + ["LAX", "SNA", "ANC", "SFO", "PBI", "DJT"]]
print(pd.DataFrame(rows, columns=["code", "pax_12m", "delay_rows_all_months"]).to_string(index=False))
print("HVN carriers in delay file:", d[d.airport == "HVN"]["carrier"].unique().tolist())
print("T-100 names:", t[t.origin_airport_code.isin(["DJT", "PBI"])][["origin_airport_code", "origin_airport_name"]].drop_duplicates().values.tolist())
