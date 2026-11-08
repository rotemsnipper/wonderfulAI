## Definitions
- Passengers, seats, departures: T-100 airport-month summary, all carriers, domestic plus international, summed over the 12-month window.
- Load factor: passengers divided by seats. A practical ceiling is 85%; above it, flights are hard to book.
- Growth: compound annual passenger growth from the 2019 baseline year to the current window, plus the change against the prior 12 months.
- Delay rate: share of arriving flights 15 or more minutes late, from BTS delay causes.
- System delay rate: share of arriving flights delayed by the national aviation system (NAS) cause. NAS is mostly congestion and air traffic control but also includes ordinary weather.
- Cancellation rate: cancelled arrivals divided by scheduled arrivals.
- Departures per usable runway: departures in the window divided by open runways of at least 3,000 feet. This is context, not a score component.
- Long-haul share: share of departures at or above a distance cutoff (2,000, 2,500 and 3,000 miles; 3,000 is the default). The headline uses scheduled passenger flights (class F); the share including cargo and charter flights (classes F, G, L, P) is shown beside it.
- Seat gap: extra seats a year needed to bring the load factor down to 85%. Zero is a valid, measured result.
- Excess delayed flights: delayed arrivals above what the national median delay rate would give. A lower bound of congestion-related unmet demand.
- Delay-cause shares: each cause's share of the delay cause counts (system, airline, late-arriving aircraft, extreme weather, security).
- Expansion score: weighted rank percentiles (0-100) of growth, load factor and congestion across covered airports. Missing a component means no total score; a labeled partial score is shown instead.
- Robustness: how often an airport stays in the top ranks when the weights are varied at random.

## Coverage and thresholds
- Covered airports: US airports with at least 250,000 passengers in the current 12-month window.
- Size tiers are by 12-month passengers and are shown for grouping only.

## Known data limits
- Data is historical. The newest month in each source lags by a few months; answers use the latest month available in every source.
- Delay causes cover domestic flights of the larger reporting airlines only; some airports (for example New Haven) have no delay data, which means unknown, not zero.
- The T-100 segment data counts a passenger on each leg of a multi-stop trip.
- At cargo hubs, passenger-based metrics describe only part of the traffic.
- Airports with legal slot limits or operating caps can look less congested than they are.
