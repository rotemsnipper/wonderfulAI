"""Ranking robustness: re-weight stored percentiles under random Dirichlet draws around the default weights.

Percentiles do not depend on the weights, so each draw only recomputes the weighted sums. Only airports
with a full score take part. Verdicts per airport:
- robust: in the top K in at least 80% of draws
- sensitive: in the top K in 20% to 80% of draws
- rarely in top: under 20%
"""
import numpy as np

ROBUST_SHARE = 0.80
RARE_SHARE = 0.20


def _verdict(share: float) -> str:
    if share >= ROBUST_SHARE:
        return "robust"
    if share >= RARE_SHARE:
        return "sensitive"
    return "rarely in top"


def robustness(breakdowns: list[dict], weights: dict, settings: dict) -> dict:
    """Per-airport top-K share, best and worst rank and verdict, plus a one-line summary.

    `breakdowns` are score breakdowns with a total score (others are ignored).
    """
    cfg = settings["robustness"]
    full = [b for b in breakdowns if b["total_score"] is not None]
    names = list(weights)
    codes = [b["airport_code"] for b in full]
    if not full:
        return {"per_airport": {}, "summary": "No airports with a full score; robustness not computed.",
                "draws": 0, "seed": cfg["seed"], "top_k": cfg["top_k"]}
    pct = np.array([[next(c["percentile"] for c in b["components"] if c["name"] == n) for n in names] for b in full])
    base = np.array([weights[n] for n in names])
    rng = np.random.default_rng(cfg["seed"])
    draws = rng.dirichlet(base * cfg["concentration"], size=cfg["draws"])
    scores = draws @ pct.T
    # rank 1 = best; ties broken by code order for determinism
    order = np.lexsort((np.broadcast_to(np.arange(len(codes)), scores.shape), -scores), axis=1)
    ranks = np.empty_like(order)
    rows = np.arange(scores.shape[0])[:, None]
    ranks[rows, order] = np.arange(1, len(codes) + 1)
    k = min(cfg["top_k"], len(codes))
    in_top = ranks <= k
    per = {}
    for i, code in enumerate(codes):
        share = float(in_top[:, i].mean())
        per[code] = {
            "top_k_share": share,
            "best_rank": int(ranks[:, i].min()),
            "worst_rank": int(ranks[:, i].max()),
            "verdict": _verdict(share),
        }
    default_top = [b["airport_code"] for b in sorted(full, key=lambda b: (-b["total_score"], b["airport_code"]))[:k]]
    return {
        "per_airport": per,
        "summary": summary_line(default_top, per, cfg["draws"], k),
        "draws": int(cfg["draws"]),
        "seed": cfg["seed"],
        "top_k": k,
    }


def summary_line(default_top: list[str], per: dict, draws: int, k: int) -> str:
    robust = [c for c in default_top if per[c]["verdict"] == "robust"]
    shaky = [c for c in default_top if per[c]["verdict"] != "robust"]
    parts = []
    if robust:
        parts.append(f"{', '.join(robust)} stay in the top {k} in at least {ROBUST_SHARE:.0%} of {draws} weight scenarios")
    if shaky:
        parts.append(", ".join(f"{c} is {per[c]['verdict']} (top {k} in {per[c]['top_k_share']:.0%})" for c in shaky))
    return "Robustness: " + "; ".join(parts) + "."
