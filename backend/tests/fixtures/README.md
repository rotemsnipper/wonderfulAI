# Fixture dataset (not real data)

Tiny serving-contract dataset for M2 and M3 tests. Fictional airports with constant monthly values, so every annual figure is 12 x the monthly value and can be checked by hand.

- Source of truth: `serving/spec/airports_spec.csv` and `serving/spec/routes_spec.csv`.
- Regenerate: `python backend/tests/fixtures/serving/build_fixture.py` (writes CSV and parquet next to the spec, and copies `config/settings.yaml`).
- Periods: current window 2025-08..2026-07, prior window 2024-08..2025-07, baseline calendar 2019. Latest month is 2026-07.
- Routes are for the current window only. Route departures sum to the `airport_month` departures for every airport and month. Route passengers, seats and freight are filler values (100 passengers and 130 seats per passenger-class departure, 50,000 lbs per cargo departure) and are not meant to reconcile with `airport_month`.
- Delay columns are null (and `has_delay_data` false) for the baseline rows and for NHV.

## Conventions used for the expected values
- Rates come from summed counts (sum of delayed / sum of arrivals), never averages of monthly rates.
- Seat gap = max(0, passengers / 0.85 - seats). Excess delayed flights = max(0, delayed - arrivals x national median rate).
- National median delay rate = median of the 12-month delay rates of airports that are in the universe and have delay data (excludes NHV and TNY). Result on this fixture: 20.000%.
- Long-haul passenger basis = class F only; all-flight basis = F + G + L + P. Share of departures at or above the cutoff.
- Compound growth from baseline = (current_12m / baseline_12m) ^ (1 / years) - 1 with years = 79 / 12 = 6.5833 (2019-12 to 2026-07).
- Size tiers use the placeholder bands in `config/settings.yaml`.

## Per-airport annual values, current window (hand-checkable)
| Code | Role in tests | Passengers | Seats | Load factor % | Pax vs prior % | Current / baseline | Arrivals | Delay rate % | System delay % | Cancel % | Departures | Dep per usable runway | Seat gap |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LAA | LAX-like big airport | 36,000,000 | 43,200,000 | 83.33 | -4.00 | 1.2000 | 192,000 | 20.000 | 5.000 | 1.000 | 264,000 | 66,000 (4 runways) | 0 |
| SAA | SNA-like, runway rule (2 runways, 1 usable) | 5,520,000 | 6,960,000 | 79.31 | +2.22 | 1.1500 | 45,600 | 18.000 | 4.000 | 1.000 | 51,600 | 51,600 (1 usable) | 0 |
| NRC | Anchorage-like cargo hub | 2,400,000 | 3,120,000 | 76.92 | +5.26 | 1.3333 | 24,000 | 20.000 | 2.000 | 1.000 | 7,440 | 2,480 (3 runways) | 0 |
| BAY | SFO-like, zero seat gap, high delays | 26,400,000 | 33,000,000 | 80.00 | -2.22 | 1.0476 | 144,000 | 25.000 | 10.000 | 1.000 | 180,000 | 45,000 (4 runways) | 0 |
| NHV | No delay data | 720,000 | 960,000 | 75.00 | +3.45 | 1.2000 | none | unknown | unknown | unknown | 8,400 | 4,200 | 0 |
| SMP | Small airport, few arrivals | 300,000 | 480,000 | 62.50 | +4.17 | 1.2500 | 600 | 40.000 | 16.000 | 4.000 | 6,000 | 6,000 | 0 |
| PME | Positive seat gap; Portland, ME | 1,320,000 | 1,464,000 | 90.16 | +10.00 | 1.2222 | 9,600 | 18.750 | 3.750 | 1.000 | 13,200 | 6,600 | 88,941 |
| PMW | Portland, OR (same city name, other state) | 18,000,000 | 22,800,000 | 78.95 | -3.23 | 1.1538 | 108,000 | 16.667 | 5.000 | 1.000 | 144,000 | 48,000 | 0 |
| SPA | Springfield, MO | 3,000,000 | 3,840,000 | 78.12 | +4.17 | 1.2500 | 21,600 | 20.000 | 5.000 | 1.000 | 26,400 | 13,200 | 0 |
| SPB | Springfield, IL | 960,000 | 1,260,000 | 76.19 | -2.44 | 1.1429 | 8,400 | 18.000 | 3.000 | 1.000 | 10,800 | 5,400 | 0 |
| DPX | Regular medium airport | 4,320,000 | 5,160,000 | 83.72 | +2.86 | 1.2000 | 31,200 | 20.000 | 5.000 | 1.000 | 38,400 | 19,200 | 0 |
| TNY | Below universe threshold | 96,000 | 144,000 | 66.67 | +6.67 | 1.3333 | 1,800 | 13.333 | 2.667 | 0.667 | 2,400 | 2,400 | 0 |

Size tier (placeholder bands): LAA, BAY, PMW large; SAA, SPA, DPX medium; NRC, PME small; NHV, SMP, SPB, TNY nonhub. In the universe: all except TNY.

## Derived values to test
- National median delay rate: 20.000% (eligible: BAY, DPX, LAA, NRC, PME, PMW, SAA, SMP, SPA, SPB).
- Excess delayed flights vs that median: BAY 7,200; SMP 120; all others 0 (floored).
- Compound growth from baseline: ratio 1.2 gives 2.808%/year; 1.15 gives 2.146%; 1.3333 gives 4.467%; 1.0476 gives 0.709%; 1.2222 gives 3.095%.
- Zero seat gap is the normal case (11 of 12 airports); PME is the only positive one: 1,320,000 / 0.85 - 1,464,000 = 88,941.

## Departures growth and the two-sided score (score version 0.2)
Departures per month: current `dep_m`, prior `prior_dep_m`, baseline `base_dep_m` (see the spec). Compound departures growth uses the same 79 / 12 years as passengers. Percentiles rank the 11 universe airports (10 for congestion; NHV has no delay data), ties share the average rank. Side score = mean of its two percentiles (equal weights); total = mean of the four.

| Code | Departures cur / base | Dep growth %/yr | Dep vs prior % | Pax growth pct | Load factor pct | Flight growth pct | Congestion pct | Passenger side | Flight side | Total |
|---|---|---|---|---|---|---|---|---|---|---|
| DPX | 1.2800 | 3.821 | +6.667 | 50.0 | 90.0 | 80.0 | 61.1 | 70.00 | 70.56 | 70.278 |
| SMP | 1.2500 | 3.448 | +4.167 | 85.0 | 0.0 | 70.0 | 100.0 | 42.50 | 85.00 | 63.750 |
| PME | 1.2222 | 3.095 | +10.000 | 70.0 | 100.0 | 60.0 | 22.2 | 85.00 | 41.11 | 63.056 |
| LAA | 1.1579 | 2.252 | 0.000 | 50.0 | 80.0 | 50.0 | 61.1 | 65.00 | 55.56 | 60.278 |
| NRC | 1.5500 | 6.884 | +24.000 | 100.0 | 30.0 | 100.0 | 0.0 | 65.00 | 50.00 | 57.500 |
| SPA | 1.1000 | 1.458 | +4.762 | 85.0 | 40.0 | 40.0 | 61.1 | 62.50 | 50.56 | 56.528 |
| BAY | 1.0000 | 0.000 | -3.226 | 0.0 | 70.0 | 20.0 | 88.9 | 35.00 | 54.44 | 44.722 |
| PMW | 0.9600 | -0.618 | 0.000 | 30.0 | 50.0 | 10.0 | 61.1 | 40.00 | 35.56 | 37.778 |
| SAA | 1.0750 | 1.105 | +2.381 | 20.0 | 60.0 | 30.0 | 33.3 | 40.00 | 31.67 | 35.833 |
| SPB | 0.9000 | -1.588 | -5.263 | 10.0 | 20.0 | 0.0 | 11.1 | 15.00 | 5.56 | 10.278 |
| NHV | 1.4000 | 5.244 | +9.375 | 50.0 | 10.0 | 90.0 | none | 30.00 | none | none (partial) |

TNY (out of universe): departures flat, 0.000%/year.

Expected labels with the placeholder thresholds (High 65, Medium 50, strength 70, weakness 40):
- DPX: High potential, High confidence, "Prioritize for due diligence"; strengths load factor 90, flight growth 80; no weaknesses.
- NRC: Medium potential, Medium confidence (cargo-heavy), "Monitor".
- PME: Medium, High confidence, "Investigate further"; strengths load factor 100, passenger growth 70 (edge: exactly 70); weakness congestion 22.2.
- BAY: Low, "Deprioritize". NHV: "Not scored", Low confidence.

## Long-haul share of departures (current window)
| Airport | Cutoff | Passenger flights (F) | All flights (F+G+L+P) |
|---|---|---|---|
| NRC | 2,000 | 33.33% (100 of 300) | 61.29% (380 of 620) |
| NRC | 2,500 | 13.33% (40 of 300) | 51.61% (320 of 620) |
| NRC | 3,000 | 3.33% (10 of 300) | 45.16% (280 of 620) |
| LAA | 2,000 / 2,500 / 3,000 | 31.82% / 31.82% / 9.09% | same (all F) |
| SAA | 2,000 / 2,500 / 3,000 | 11.63% / 0% / 0% | same (all F) |
| BAY | 2,000 / 2,500 / 3,000 | 40.00% / 40.00% / 13.33% | same (all F) |

NRC cargo share of departures (classes G and P): 50.00% (310 of 620), which triggers the cargo-heavy warning at the 30% placeholder threshold.

## Resolver cases the fixture supports
- "Portland" matches PME (ME) and PMW (OR); "Springfield" matches SPA and SPB: always ask, largest first.
- A three-letter string that is not a code (for example "Rio") must not be accepted as a code.
