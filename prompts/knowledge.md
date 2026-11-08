## Definitions
- Passengers, seats, departures: T-100 airport-month summary, all carriers, domestic plus international, summed over the 12-month window.
- Load factor: passengers divided by seats. A practical ceiling is 85%; above it, flights are hard to book.
- Passenger growth: compound annual passenger growth from the baseline year to the current window, plus the change against the prior 12 months.
- Flight growth: compound annual departures growth from the baseline year to the current window, plus the change against the prior 12 months. Departures include cargo flights, so at cargo hubs part of the growth can be cargo; the cargo-heavy warning lowers confidence there.
- Delay rate: share of arriving flights 15 or more minutes late, from BTS delay causes.
- System delay rate: share of arriving flights delayed by the national aviation system (NAS) cause. NAS is mostly congestion and air traffic control but also includes ordinary weather.
- Cancellation rate: cancelled arrivals divided by scheduled arrivals.
- Departures per usable runway: departures in the window divided by open runways of at least 3,000 feet. This is context, not a score component.
- Long-haul share: share of departures at or above a distance cutoff (2,000, 2,500 and 3,000 miles; 3,000 is the default). The headline uses scheduled passenger flights (class F); the share including cargo and charter flights (classes F, G, L, P) is shown beside it.
- Seat gap: extra seats a year needed to bring the load factor down to 85%. Zero is a valid, measured result.
- Excess delayed flights: delayed arrivals above what the national median delay rate would give. A lower bound of congestion-related unmet demand.
- Delay-cause shares: each cause's share of the delay cause counts (system, airline, late-arriving aircraft, extreme weather, security).
- Capacity-need score: weighted national rank percentiles (0-100) of four components on two sides. Passenger side: passenger growth and load factor (is demand growing, are planes already full?). Flight side: flight growth and congestion (are flights growing, is the airport congested?). Side scores show which kind of capacity is under pressure. Missing a component means no total score; a labeled partial score is shown instead and the airport is not labeled. An airport without delay data has no flight side.
- Label: potential (from the score), confidence (from data completeness and warnings) and a recommendation, all set by fixed rules in code; strengths and weaknesses are the components with high or low percentiles. Thresholds are in the generated "Scoring rules" section.
- Profit proxy: the score ranks capacity need, meaning how much added passenger and flight capacity would be filled. No public source gives renovation cost, gate counts, terminal utilization or revenue per passenger, so it is a proxy for profit, never a profit or return estimate.
- Which side to lead with: terminal expansion questions are mainly about passengers, so lead with the passenger side; runway or airside questions lead with the flight side. Always show the total score and both sides.
- Context only, never scored: long-haul share, cargo share, total delay rate, cancellations, departures per usable runway and size tier.
- Robustness: how often an airport stays in the top ranks when the weights are varied at random. When you rank by score, always state the robustness verdict (robust or sensitive to the weights) for the airports you recommend, so the reader knows whether the ranking depends on the weighting.

## Coverage and thresholds
- Covered airports: US airports with at least 250,000 passengers in the current 12-month window.
- Size tiers are by 12-month passengers and are shown for grouping only.

## Known data limits
- Data is historical. The newest month in each source lags by a few months; answers use the latest month available in every source.
- Delay causes cover domestic flights of the larger reporting airlines only; some airports (for example New Haven) have no delay data, which means unknown, not zero.
- The T-100 segment data counts a passenger on each leg of a multi-stop trip.
- At cargo hubs, passenger-based metrics describe only part of the traffic.
- Airports with legal slot limits or operating caps can look less congested than they are.
