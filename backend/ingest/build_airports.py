"""Build the `airports` serving table from OurAirports plus T-100 IDs and 12-month passengers.

Inputs other than OurAirports arrive as a DataFrame (code, airport_id, passengers_12m) so this module
reads no other raw file. Only US airports with scheduled airline service are kept.
Usable runways: open and at least `usable_runway_min_ft` long.
"""
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

COLUMNS = ["airport_id", "code", "name", "city", "state", "runways_total", "runways_usable", "max_runway_ft",
           "size_tier", "in_universe"]


def size_tier(passengers: float, bands: dict) -> str:
    return next(tier for tier, lower in sorted(bands.items(), key=lambda kv: -kv[1]) if passengers >= lower)


def runway_counts(runways: pd.DataFrame, min_ft: float) -> pd.DataFrame:
    """Per OurAirports ident: open runways, usable runways and longest open runway."""
    rw = runways[runways["closed"] == 0]
    g = rw.groupby("airport_ident")
    return pd.DataFrame({
        "runways_total": g.size(),
        "runways_usable": rw[rw["length_ft"] >= min_ft].groupby("airport_ident").size(),
        "max_runway_ft": g["length_ft"].max(),
    }).fillna({"runways_usable": 0})


def build_airports(ourairports_dir: Path | str, t100: pd.DataFrame, settings: dict) -> tuple[pd.DataFrame, list[str]]:
    """Return (airports table, unmatched T-100 codes).

    `t100` has one row per airport code: code, airport_id, passengers_12m.
    """
    ourairports_dir = Path(ourairports_dir)
    oa = pd.read_csv(ourairports_dir / "airports.csv", low_memory=False)
    oa = oa[(oa["iso_country"] == "US") & oa["iata_code"].notna() & (oa["scheduled_service"] == "yes")]
    oa = oa.drop_duplicates("iata_code").set_index("iata_code")
    rw = runway_counts(pd.read_csv(ourairports_dir / "runways.csv", low_memory=False), settings["usable_runway_min_ft"])

    rows, unmatched = [], []
    for t in t100.itertuples(index=False):
        if t.code not in oa.index:
            unmatched.append(t.code)
            continue
        a = oa.loc[t.code]
        counts = rw.loc[a["ident"]] if a["ident"] in rw.index else None
        rows.append({
            "airport_id": int(t.airport_id),
            "code": t.code,
            "name": a["name"],
            "city": a["municipality"],
            "state": a["iso_region"].split("-", 1)[1],
            "runways_total": int(counts["runways_total"]) if counts is not None else 0,
            "runways_usable": int(counts["runways_usable"]) if counts is not None else 0,
            "max_runway_ft": float(counts["max_runway_ft"]) if counts is not None else None,
            "size_tier": size_tier(t.passengers_12m, settings["size_bands"]),
            "in_universe": bool(t.passengers_12m >= settings["universe_min_passengers_12m"]),
        })
    log.info("%d T-100 airports have no scheduled-service US OurAirports match and were dropped", len(unmatched))
    return pd.DataFrame(rows, columns=COLUMNS).sort_values("code").reset_index(drop=True), sorted(unmatched)
