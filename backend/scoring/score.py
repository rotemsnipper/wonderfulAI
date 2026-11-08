"""Capacity-need score: national rank percentiles of four components on two sides, weighted by versioned config.

Components (higher means more need for added capacity):
- passenger side
  - passenger_growth: compound annual passenger growth from the baseline year, percent per year
  - load_factor: passengers / seats in the current window
- flight side
  - flight_growth: compound annual departures growth from the baseline year, percent per year
  - congestion: arrival system-delay (NAS) rate in the current window, percent

Each side score is the weighted mean of its two percentiles and needs both of them. An airport missing
any component gets no total score; its available components are re-weighted into a labeled partial
score. Missing values are never imputed.
"""
from backend.scoring import formulas as f
from backend.scoring import metrics
from backend.tools.store import Store

SIDES = {"passenger": ("passenger_growth", "load_factor"), "flight": ("flight_growth", "congestion")}
COMPONENTS = SIDES["passenger"] + SIDES["flight"]


def raw_components(store: Store, code: str) -> dict[str, float | None]:
    t = metrics.window_totals(store, code)
    g = metrics.growth(store, code)
    return {
        "passenger_growth": g["compound_growth_pct_per_year"],
        "load_factor": f.load_factor(t["passengers"], t["seats"]),
        "flight_growth": g["departures_compound_growth_pct_per_year"],
        "congestion": metrics.system_delay_rate(t),
    }


def universe_codes(store: Store) -> list[str]:
    return sorted(store.airports.loc[store.airports["in_universe"].astype(bool), "code"])


def side_score(pct: dict, weights: dict, side: str) -> float | None:
    names = SIDES[side]
    w_sum = sum(weights[c] for c in names)
    return f.weighted_score({c: pct[c] for c in names}, {c: weights[c] / w_sum for c in names})


def _breakdown(code: str, raw: dict, pct: dict, weights: dict, version: str) -> dict:
    available = [c for c in COMPONENTS if pct[c] is not None]
    total = f.weighted_score({c: pct[c] for c in COMPONENTS}, weights)
    if total is not None:
        effective = dict(weights)
        tier, partial = "full", None
    elif available:
        w_sum = sum(weights[c] for c in available)
        effective = {c: (weights[c] / w_sum if c in available else 0.0) for c in COMPONENTS}
        missing = [c for c in COMPONENTS if c not in available]
        partial = {
            "score": f.weighted_score({c: pct[c] for c in available}, {c: effective[c] for c in available}),
            "components_used": available,
            "components_missing": missing,
            "label": f"partial score without {', '.join(missing)} (not comparable to full scores)",
        }
        tier = "partial"
    else:
        effective = {c: 0.0 for c in COMPONENTS}
        tier, partial = "none", None
    return {
        "airport_code": code,
        "total_score": total,
        "partial_scores": partial,
        "components": [
            {
                "name": c,
                "raw_value": raw[c],
                "percentile": pct[c],
                "weight": weights[c],
                "contribution": pct[c] * effective[c] if pct[c] is not None else None,
            }
            for c in COMPONENTS
        ],
        "effective_weights": effective,
        "passenger_score": side_score(pct, weights, "passenger"),
        "flight_score": side_score(pct, weights, "flight"),
        "data_tier": tier,
        "score_version": version,
        "robustness": None,
    }


def score_all(store: Store, settings: dict) -> dict[str, dict]:
    """Score breakdown for every universe airport, keyed by code."""
    weights = settings["weights"]
    codes = universe_codes(store)
    raw = {code: raw_components(store, code) for code in codes}
    pct = {c: f.percentile_ranks({code: raw[code][c] for code in codes}) for c in COMPONENTS}
    return {
        code: _breakdown(code, raw[code], {c: pct[c][code] for c in COMPONENTS}, weights, settings["score_version"])
        for code in codes
    }


def ranked(breakdowns: dict[str, dict]) -> list[dict]:
    """Breakdowns with a total score, best first; ties broken by code for determinism."""
    scored = [b for b in breakdowns.values() if b["total_score"] is not None]
    return sorted(scored, key=lambda b: (-b["total_score"], b["airport_code"]))
