"""Build the `routes` serving table from T-100 Segment (All Carriers) yearly zips.

One row per origin, month, destination, distance and service class, summed over carriers and aircraft
types. Cargo and charter classes are kept so tools can compute passenger-only and all-flight shares.
DISTANCE in T-100 is in statute miles. Rows with no departures, passengers or freight are dropped.
"""
import logging
import zipfile
from collections.abc import Iterable
from pathlib import Path

import pandas as pd


log = logging.getLogger(__name__)

CSV_NAME = "T_T100_SEGMENT_ALL_CARRIER.csv"
COLUMNS = ["code", "year", "month", "dest", "dest_country", "distance_mi", "class", "departures", "passengers",
           "seats", "freight_lbs"]
SOURCE = {"ORIGIN": "code", "YEAR": "year", "MONTH": "month", "DEST": "dest", "DEST_COUNTRY": "dest_country",
          "DISTANCE": "distance_mi", "CLASS": "class", "DEPARTURES_PERFORMED": "departures",
          "PASSENGERS": "passengers", "SEATS": "seats", "FREIGHT": "freight_lbs"}
KEYS = ["code", "year", "month", "dest", "dest_country", "distance_mi", "class"]
MEASURES = ["departures", "passengers", "seats", "freight_lbs"]


def _read(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            with z.open(CSV_NAME) as fh:
                df = pd.read_csv(fh, low_memory=False)
    else:
        df = pd.read_csv(path, low_memory=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return df[list(SOURCE)].rename(columns=SOURCE)


def build_routes(paths: Iterable[Path | str], start_ym: int | None = None,
                 end_ym: int | None = None) -> tuple[pd.DataFrame, dict]:
    """Return (routes table, build log) from segment zips or CSVs, optionally limited to start_ym..end_ym."""
    df = pd.concat([_read(Path(p)) for p in paths], ignore_index=True)
    for c in ("year", "month"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(int)
    for c in ("distance_mi", *MEASURES):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    ym = df["year"] * 100 + df["month"]
    keep = pd.Series(True, index=df.index)
    if start_ym:
        keep &= ym >= start_ym
    if end_ym:
        keep &= ym <= end_ym
    df = df[keep].copy()
    df["code"] = df["code"].str.strip().str.upper()
    df["dest"] = df["dest"].str.strip().str.upper()
    empty = (df[MEASURES] == 0).all(axis=1)
    out = df[~empty].groupby(KEYS, as_index=False)[MEASURES].sum()
    out = out[COLUMNS].sort_values(["code", "year", "month", "dest", "class"]).reset_index(drop=True)
    build_log = {
        "source_rows": int(len(df)),
        "empty_rows_dropped": int(empty.sum()),
        "rows": int(len(out)),
        "departures_by_class": {k: int(v) for k, v in out.groupby("class")["departures"].sum().items()},
        "international_departures": int(out.loc[out["dest_country"] != "US", "departures"].sum()),
        "max_distance_mi": float(out["distance_mi"].max()) if len(out) else None,
    }
    log.info("routes: %s", build_log)
    return out, build_log
