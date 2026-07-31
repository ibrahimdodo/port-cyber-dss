#!/usr/bin/env python3
"""Answer Problem #1: given a budget, which controls should the port buy?

Runs the full chain -- derived port economics, scenario catalogue, control
catalogue -- through the budget-constrained optimiser, then hands the chosen
portfolio to the Monte Carlo for the distributional answer the mean cannot give.

Usage
-----
    python scripts/demo_optimise.py
    python scripts/demo_optimise.py --budget 40000
    python scripts/demo_optimise.py --ig 1        # essential hygiene only
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("portscra") is None:  # not pip-installed; run in place
    sys.path.insert(0, str(REPO / "src"))

from portscra.controls import (  # noqa: E402
    CATALOGUE,
    apply_controls,
    catalogue_for_group,
    efficient_frontier,
    optimise,
    tornado,
    total_cost,
)
from portscra.risk import RONNE_2024, OutageCostPerHour, simulate  # noqa: E402
from portscra.taxonomy import build_scenarios  # noqa: E402
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES  # noqa: E402


def eur(value: float) -> str:
    return f"EUR {value:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=25_000)
    parser.add_argument("--ig", type=int, choices=(1, 2, 3), default=3,
                        help="Restrict to controls at or below this CIS "
                             "implementation group. IG1 is essential hygiene.")
    parser.add_argument("--iterations", type=int, default=100_000)
    args = parser.parse_args()

    cost_per_hour = OutageCostPerHour(RONNE_2024)
    scenarios = build_scenarios(cost_per_hour)
    catalogue = catalogue_for_group(args.ig) if args.ig < 3 else CATALOGUE
    names = {t.id: t.name for t in SCENARIO_TEMPLATES}

    print(f"\n=== Mitigation portfolio for {RONNE_2024.name} ===")
    print(f"budget {eur(args.budget)} | catalogue {len(catalogue)} controls "
          f"(IG<={args.ig}, full cost {eur(total_cost(catalogue))})")
    print(f"cost per outage hour {eur(cost_per_hour.mean)} (derived from "
          f"{RONNE_2024.year} accounts)\n")

    portfolio = optimise(scenarios, catalogue, args.budget)
    print(portfolio.explain())

    print("\n--- where the risk goes ---")
    print(f"  {'scenario':46s} {'before':>12s} {'after':>12s} {'cut':>6s}")
    for sid, (before, after) in sorted(
        portfolio.per_scenario.items(), key=lambda kv: -kv[1][0]
    ):
        cut = 1 - after / before if before else 0.0
        print(f"  {names.get(sid, sid)[:44]:46s} {eur(before):>12s} "
              f"{eur(after):>12s} {cut:5.0%}")

    # The mean drove the search; the distribution is what justifies the spend.
    print("\n--- what it does to the distribution ---")
    residual_scenarios = apply_controls(scenarios, portfolio.controls)

    before = simulate(scenarios, iterations=args.iterations, seed=42)["__portfolio__"]
    after = simulate(residual_scenarios, iterations=args.iterations, seed=42)["__portfolio__"]

    print(f"  {'':16s} {'before':>14s} {'after':>14s}")
    for label, fn in (
        ("mean (ALE)", lambda r: r.ale),
        ("median", lambda r: r.p50),
        ("P90", lambda r: r.p90),
        ("P99", lambda r: r.percentile(99)),
        ("worst simulated", lambda r: float(r.annual_loss.max())),
    ):
        print(f"  {label:16s} {eur(fn(before)):>14s} {eur(fn(after)):>14s}")
    quiet_before = (before.annual_loss == 0).mean()
    quiet_after = (after.annual_loss == 0).mean()
    print(f"  {'loss-free years':16s} {quiet_before:>13.1%} {quiet_after:>13.1%}")

    tail_cut = 1 - after.percentile(99) / before.percentile(99)
    mean_cut = 1 - after.ale / before.ale
    print(f"\n  Mean falls {mean_cut:.0%}; the P99 tail falls only {tail_cut:.0%}.")
    if tail_cut < mean_cut:
        print("  The tail is stickier than the average. Most of what the portfolio")
        print("  buys is *frequency* reduction -- loss-free years rise from "
              f"{quiet_before:.0%} to {quiet_after:.0%} -- but the bad year that")
        print("  still happens remains expensive, because the residual tail is")
        print("  dominated by whichever scenarios the budget could not cover.")
        print("  Reporting only the mean would overstate how much protection has")
        print("  been bought. This is the argument for the exceedance curve, and")
        print("  it points the opposite way to the usual intuition.")
    else:
        print("  The portfolio bites hardest on the tail, which is where the")
        print("  case for spending lives. A single expected value would hide this.")

    print("\n--- sensitivity: which effectiveness estimates matter ---")
    print("  (residual loss if each control is 50% better or worse than assumed)")
    for control_id, low, high in tornado(scenarios, portfolio):
        control = next(c for c in portfolio.controls if c.id == control_id)
        print(f"  {control_id}  {eur(low):>12s} .. {eur(high):<12s}  {control.name[:38]}")
    print("\n  Wide bars are the assumptions worth researching before committing")
    print("  budget. Narrow ones are assumptions that do not change the answer.")

    print("\n--- how much is enough? ---")
    budgets = [10_000, 20_000, 30_000, 50_000, 75_000, total_cost(catalogue)]
    for p in efficient_frontier(scenarios, catalogue, budgets):
        bar = "#" * int(50 * p.reduction_pct)
        print(f"  {eur(p.cost):>10s} spent -> {eur(p.residual_ale):>10s} residual "
              f"({p.reduction_pct:4.0%} cut, ROSI {p.rosi:+5.1f}x) {bar}")
    print("\n  Diminishing returns are visible in the curve: the question for a")
    print("  port director is not 'what should I buy' but 'where does this stop")
    print("  paying', and that is a shape rather than a number.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
