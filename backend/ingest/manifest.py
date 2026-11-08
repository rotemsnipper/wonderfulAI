"""Manifest describing a serving build: periods per source, window, row counts, check results, versions."""
from datetime import date

import pandas as pd


def ym_label(ym: int) -> str:
    return f"{ym // 100}-{ym % 100:02d}"


def period(yms) -> str:
    yms = sorted(int(x) for x in yms)
    return f"{ym_label(yms[0])}..{ym_label(yms[-1])}" if yms else "none"


def build_manifest(*, airports: pd.DataFrame, airport_month: pd.DataFrame, routes: pd.DataFrame,
                   windows: dict[str, list[int]], baseline_year: int, checks: list[dict], settings: dict,
                   build_date: date | None = None) -> dict:
    delay_months = airport_month.loc[airport_month["has_delay_data"].astype(bool), "ym"]
    return {
        "periods": {
            "t100_summary": period(airport_month["ym"]),
            "delay_causes": period(delay_months),
            "t100_segment": period(routes["year"] * 100 + routes["month"]),
        },
        "window": {
            "current": period(windows["current"]),
            "prior": period(windows["prior"]),
            "baseline_year": baseline_year,
        },
        "coverage": {
            "airports": int(len(airports)),
            "in_universe": int(airports["in_universe"].sum()),
            "in_universe_with_delay_data": int(
                airports[airports["in_universe"].astype(bool)]["code"].isin(
                    airport_month.loc[airport_month["ym"].isin(windows["current"]) & airport_month["has_delay_data"], "code"]
                ).sum()
            ),
            "universe_min_passengers_12m": settings["universe_min_passengers_12m"],
        },
        "row_counts": {"airports": int(len(airports)), "airport_month": int(len(airport_month)), "routes": int(len(routes))},
        "checks": {c["name"]: ("pass" if c["passed"] else "fail") for c in checks},
        "build_date": (build_date or date.today()).isoformat(),
        "config_version": settings["score_version"],
    }
