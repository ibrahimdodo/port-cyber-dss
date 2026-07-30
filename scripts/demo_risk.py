#!/usr/bin/env python3
"""Run the risk engine on the default scenario catalogue and print results.

Needs no data download -- it exercises the Monte Carlo, the scenario catalogue
and the taxonomy wiring end to end using placeholder cost-per-hour figures.

The euro-per-hour range below is a PLACEHOLDER, and deliberately labelled as
one. Replacing it with a figure derived from AIS-observed traffic at Rønne plus
Port of Rønne's published accounts is the substance of the consequence-model
phase. Everything downstream of it is already wired.

Usage
-----
    python scripts/demo_risk.py
    python scripts/demo_risk.py --iterations 200000 --persona 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from portscra.risk import PERT, annual_disturbance_pct, simulate  # noqa: E402
from portscra.taxonomy import build_scenarios, stride_coverage  # noqa: E402

#: Placeholder only. See module docstring.
PLACEHOLDER_COST_PER_HOUR = PERT(
    800, 2_500, 9_000,
    source="PLACEHOLDER pending AIS calibration -- order-of-magnitude figure for "
           "a small mixed port, to be replaced from port-call throughput and "
           "published port accounts.",
)

#: Rough annual service hours for a mixed port working extended but not
#: continuous days. The denominator matters: expressing disturbance as a
#: percentage of 24x365 would flatter the port by counting closed hours as
#: undisturbed operation.
ANNUAL_SERVICE_HOURS = 16 * 365


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
    scenarios = build_scenarios(PLACEHOLDER_COST_PER_HOUR, scale=scale)
    results = simulate(scenarios, iterations=args.iterations, seed=args.seed)

    print(f"\n=== PortSCRA risk engine ===")
    print(f"persona: {args.persona}-employee mixed port | "
          f"{args.iterations:,} simulated years | seed {args.seed}")
    print(f"cost/hour: {PLACEHOLDER_COST_PER_HOUR}  <-- PLACEHOLDER\n")

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
