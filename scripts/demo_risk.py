#!/usr/bin/env python3
"""Run the risk engine on the default scenario catalogue and print results.

Needs no data download -- it exercises the Monte Carlo, the scenario catalogue,
the taxonomy wiring and the economics derivation end to end.

The cost per outage hour is now derived from Rønne Havn A/S's 2024 audited
accounts and Danmarks Statistik call figures rather than assumed. See
`portscra.risk.economics` for the derivation and its two documented reductions.

Usage
-----
    python scripts/demo_risk.py
    python scripts/demo_risk.py --iterations 200000 --persona 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from portscra.risk import (  # noqa: E402
    RONNE_2024,
    OutageCostPerHour,
    annual_disturbance_pct,
    simulate,
)
from portscra.taxonomy import build_scenarios, stride_coverage  # noqa: E402

#: Hours a year the port can operate. Rønne is effectively a 24-hour operation
#: because Bornholmslinjen sails overnight, even though our AIS data puts 67%
#: of commercial arrivals between 06:00 and 22:00 -- cargo work is daytime, the
#: port is not closed.
ANNUAL_SERVICE_HOURS = 24 * 365

COST_PER_HOUR = OutageCostPerHour(RONNE_2024, service_hours_per_year=ANNUAL_SERVICE_HOURS)


def eur(value: float) -> str:
    if abs(value) >= 1_000_000:
        return f"EUR {value / 1_000_000:6.2f}M"
    return f"EUR {value / 1_000:8.1f}k"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=100_000)
    parser.add_argument("--persona", type=int, choices=(10, 50, 100), default=100,
                        help="Port size persona; scales response and secondary costs.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    scale = {10: 0.25, 50: 0.6, 100: 1.0}[args.persona]
    scenarios = build_scenarios(COST_PER_HOUR, scale=scale)
    results = simulate(scenarios, iterations=args.iterations, seed=args.seed)

    print(f"\n=== PortSCRA risk engine ===")
    print(f"persona: {args.persona}-employee mixed port | "
          f"{args.iterations:,} simulated years | seed {args.seed}")
    draws = COST_PER_HOUR.sample(np.random.default_rng(1), 100_000)
    print(f"cost/hour: EUR {COST_PER_HOUR.mean:,.0f}/h mean "
          f"(P10 {np.percentile(draws,10):,.0f} / P90 {np.percentile(draws,90):,.0f})")
    print(f"  derived from {RONNE_2024.name} {RONNE_2024.year}: "
          f"EUR {RONNE_2024.revenue_eur/1e6:.1f}M revenue, "
          f"{RONNE_2024.annual_calls:,} calls, {RONNE_2024.employees_fte} FTE\n")

    header = f"{'ID':4s} {'scenario':46s} {'ALE':>12s} {'P50':>12s} {'P90':>12s} {'P(any)':>7s}"
    print(header)
    print("-" * len(header))

    ranked = sorted(
        (s for s in scenarios),
        key=lambda s: results[s.id].ale,
        reverse=True,
    )
    for scenario in ranked:
        r = results[scenario.id]
        name = scenario.name[:44]
        print(f"{scenario.id:4s} {name:46s} {eur(r.ale):>12s} "
              f"{eur(r.p50):>12s} {eur(r.p90):>12s} {r.probability_of_any_loss:6.1%}")

    portfolio = results["__portfolio__"]
    print("-" * len(header))
    print(f"{'ALL':4s} {'total across all scenarios':46s} {eur(portfolio.ale):>12s} "
          f"{eur(portfolio.p50):>12s} {eur(portfolio.p90):>12s} "
          f"{portfolio.probability_of_any_loss:6.1%}")

    disturbance = annual_disturbance_pct(portfolio, ANNUAL_SERVICE_HOURS)
    print(f"\nOperations impact (all scenarios, per year):")
    print(f"  downtime hours   mean {portfolio.annual_downtime_hours.mean():6.1f}   "
          f"P90 {sorted(portfolio.annual_downtime_hours)[int(0.9 * args.iterations)]:6.1f}")
    print(f"  disturbance      mean {disturbance.mean():6.2f}%  "
          f"P90 {sorted(disturbance)[int(0.9 * args.iterations)]:6.2f}%   "
          f"(of {ANNUAL_SERVICE_HOURS:,} service hours)")

    print(f"\nWhy the mean is not the whole story:")
    quiet = (portfolio.annual_loss == 0).mean()
    print(f"  {quiet:.1%} of simulated years cost nothing at all, while the worst 1% "
          f"exceed {eur(portfolio.percentile(99))}.")
    print(f"  A single expected-value figure sits in a gap where few actual years land,")
    print(f"  which is exactly why the optimiser will target the tail, not the mean.")

    print(f"\nSTRIDE completeness audit:")
    for category, ids in stride_coverage().items():
        print(f"  {category:24s} {', '.join(ids) if ids else 'NOT COVERED'}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
