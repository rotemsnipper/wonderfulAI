"""Computed data-quality warnings per airport: no delay data, cargo-heavy traffic."""
from backend.scoring import metrics
from backend.tools.store import Store

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _w(code: str, kind: str, severity: str, message: str) -> dict:
    return {"airport": code, "type": kind, "severity": severity, "message": message}


def airport_warnings(store: Store, code: str, settings: dict) -> list[dict]:
    """Warnings for one airport, most severe first."""
    out = []
    if not metrics.window_totals(store, code)["has_delay_data"]:
        out.append(_w(code, "partial_data", "high",
                      "No delay data is reported for this airport; congestion is unknown (not zero)."))
    cargo = metrics.long_haul(store, code, settings)["cargo_share_of_departures_pct"]
    if cargo is not None and cargo >= settings["cargo_heavy_pct"]:
        out.append(_w(code, "cargo_heavy", "medium",
                      f"Cargo flights are {cargo:.0f}% of departures; passenger-based metrics describe only part of the traffic."))
    return out


def sort_warnings(warnings: list[dict]) -> list[dict]:
    return sorted(warnings, key=lambda w: SEVERITY_ORDER.get(w["severity"], 9))
