"""Spike: inspect T-100 segment files for Anchorage inputs."""
import zipfile
from pathlib import Path
import pandas as pd

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "bts_t100_segment"
frames = []
for y in (2025, 2026):
    with zipfile.ZipFile(RAW / f"t100_segment_{y}.zip") as z:
        name = "T_T100_SEGMENT_ALL_CARRIER.csv"
        frames.append(pd.read_csv(z.open(name), low_memory=False))
df = pd.concat(frames)
df.columns = [c.strip().upper() for c in df.columns]
print("shape:", df.shape, "columns:", list(df.columns))
ym = df["YEAR"] * 100 + df["MONTH"]
print("range:", ym.min(), ym.max())
w = df[(ym >= 202508) & (ym <= 202607) & (df["ORIGIN"] == "ANC")]
print("ANC rows in window:", len(w), "| classes:", w.groupby("CLASS")["DEPARTURES_PERFORMED"].sum().to_dict())
for cut in (2000, 2500, 3000):
    for label, sub in (("passenger F", w[w.CLASS == "F"]), ("all classes", w)):
        tot = sub["DEPARTURES_PERFORMED"].sum()
        lh = sub[sub["DISTANCE"] >= cut]["DEPARTURES_PERFORMED"].sum()
        print(f"cutoff {cut}: {label}: {100 * lh / tot:.1f}% ({int(lh)} of {int(tot)})")
print("ANC destinations countries:", w["DEST_COUNTRY"].value_counts().head(5).to_dict())
