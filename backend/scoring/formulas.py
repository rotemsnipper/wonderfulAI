"""Pure metric formulas. No file or config access.

Every function returns None when its inputs cannot support a number (missing input, zero
denominator). None means unknown; it is never replaced by 0.
Fractions are 0..1 (load_factor); anything named *_pct is a percentage 0..100.
"""
import math
from collections.abc import Iterable, Mapping


def _missing(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def load_factor(passengers: float | None, seats: float | None) -> float | None:
    """Passengers / seats as a fraction."""
    if _missing(passengers) or _missing(seats) or seats <= 0:
        return None
    return passengers / seats


def growth_pct(current: float | None, prior: float | None) -> float | None:
    """Simple change from prior to current, in percent."""
    if _missing(current) or _missing(prior) or prior <= 0:
        return None
    return (current / prior - 1) * 100


def compound_growth_pct(current: float | None, baseline: float | None, years: float | None) -> float | None:
    """Compound annual growth from baseline to current over `years`, in percent per year."""
    if _missing(current) or _missing(baseline) or _missing(years) or baseline <= 0 or current < 0 or years <= 0:
        return None
    return ((current / baseline) ** (1 / years) - 1) * 100


def rate_pct(numerator: float | None, denominator: float | None) -> float | None:
    """numerator / denominator in percent; None on a missing input or a zero denominator."""
    if _missing(numerator) or _missing(denominator) or denominator <= 0:
        return None
    return numerator / denominator * 100


def long_haul_share(
    rows: Iterable[tuple[float, float, str]], cutoff_mi: float, classes: Iterable[str]
) -> float | None:
    """Share of departures (percent) at or above `cutoff_mi`, counting only rows whose class is in `classes`.

    `rows` holds (distance_mi, departures, class) tuples. Rows with a missing distance or departures
    are skipped. None when there are no departures on the basis.
    """
    basis = set(classes)
    total = longhaul = 0.0
    for distance, departures, cls in rows:
        if cls not in basis or _missing(distance) or _missing(departures):
            continue
        total += departures
        if distance >= cutoff_mi:
            longhaul += departures
    if total <= 0:
        return None
    return longhaul / total * 100


def percentile_ranks(values: Mapping[str, float | None]) -> dict[str, float | None]:
    """Rank percentile 0..100 for each key; ties share the average rank; missing values stay None.

    Percentile = (rank - 1) / (n - 1) * 100 over the n non-missing values, where rank 1 is the worst.
    A single non-missing value gets 100.
    """
    present = {k: v for k, v in values.items() if not _missing(v)}
    out: dict[str, float | None] = {k: None for k in values}
    n = len(present)
    if n == 0:
        return out
    ordered = sorted(present.items(), key=lambda kv: kv[1])
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg_rank = (i + j) / 2 + 1
        pct = 100.0 if n == 1 else (avg_rank - 1) / (n - 1) * 100
        for k in range(i, j + 1):
            out[ordered[k][0]] = pct
        i = j + 1
    return out


def weighted_score(components: Mapping[str, float | None], weights: Mapping[str, float]) -> float | None:
    """Weighted sum of component percentiles; None if any weighted component is missing."""
    total = 0.0
    for name, weight in weights.items():
        value = components.get(name)
        if _missing(value):
            return None
        total += value * weight
    return total


def seat_gap(passengers: float | None, seats: float | None, ceiling: float) -> float | None:
    """Seats needed to bring load factor down to `ceiling`: max(0, passengers / ceiling - seats)."""
    if _missing(passengers) or _missing(seats) or ceiling <= 0:
        return None
    return max(0.0, passengers / ceiling - seats)


def excess_delayed_flights(
    delayed: float | None, arrivals: float | None, reference_rate_pct: float | None
) -> float | None:
    """Delayed arrivals above the reference rate: max(0, delayed - arrivals * rate)."""
    if _missing(delayed) or _missing(arrivals) or _missing(reference_rate_pct):
        return None
    return max(0.0, delayed - arrivals * reference_rate_pct / 100)


def median(values: Iterable[float | None]) -> float | None:
    """Median of the non-missing values; None if there are none."""
    xs = sorted(v for v in values if not _missing(v))
    n = len(xs)
    if n == 0:
        return None
    mid = n // 2
    return xs[mid] if n % 2 else (xs[mid - 1] + xs[mid]) / 2
