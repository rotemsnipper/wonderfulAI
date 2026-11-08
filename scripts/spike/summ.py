import pandas as pd
from pathlib import Path
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
d = pd.read_csv(RAW / "bts_delay_causes" / "Airline_Delay_Cause.csv", low_memory=False)
d["ym"] = d["year"]*100 + d["month"]
m = d.groupby(["airport","ym"])[["arr_flights","arr_del15","nas_ct","weather_ct","carrier_ct","late_aircraft_ct","security_ct","arr_cancelled","arr_diverted","arr_delay","nas_delay"]].sum().reset_index()
last12 = sorted(m["ym"].unique())[-12:]
print("last12 window:", last12[0], "to", last12[-1])
w = m[m["ym"].isin(last12)].groupby("airport")[["arr_flights","arr_del15","nas_ct","arr_cancelled","carrier_ct","weather_ct","late_aircraft_ct"]].sum()
w["delay_rate_pct"] = 100*w["arr_del15"]/w["arr_flights"]
w["nas_ct_share_of_flights_pct"] = 100*w["nas_ct"]/w["arr_flights"]
w["cancel_pct"] = 100*w["arr_cancelled"]/w["arr_flights"]
print("airports with 12m data:", len(w), " median delay rate %:", round(w["delay_rate_pct"].median(),1))
print(w.loc[["LAX","SNA"]].round(1).T.to_string())
print("months present per airport (LAX/SNA):", m[m.airport.isin(["LAX","SNA"])].groupby("airport")["ym"].nunique().to_dict())
a = pd.read_csv(RAW / "ourairports" / "airports.csv", low_memory=False)
r = pd.read_csv(RAW / "ourairports" / "runways.csv", low_memory=False)
for code in ["KLAX","KSNA"]:
    row = a[a["ident"]==code].iloc[0]
    rw = r[(r["airport_ident"]==code)]
    print(code, row["name"], row["iata_code"], row["municipality"], row["iso_region"], "runways:", len(rw), rw[["le_ident","he_ident","length_ft","closed","surface"]].values.tolist())
