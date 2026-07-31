#!/usr/bin/env python3
"""Security requirements per supplier, plus maturity — ENISA phases 3 and 4.

Answers the brief's "elaborate security requirements for Vendors/Assets" by
deriving them from what each supplier actually provides, then shows where the
port stands on ENISA's maturity scale and what its budget would move.

Usage
-----
    python scripts/demo_requirements.py
    python scripts/demo_requirements.py --vendor msp --clauses
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("portscra") is None:  # not pip-installed; run in place
    sys.path.insert(0, str(REPO / "src"))

from portscra.controls import CATALOGUE, optimise  # noqa: E402
from portscra.examples import EXAMPLE_VENDORS  # noqa: E402
from portscra.maturity import (  # noqa: E402
    CATEGORY_NAMES,
    LEVEL_NAMES,
    MEASURES,
    maturity_from_controls,
)
from portscra.requirements import Tier, as_clauses, requirements_for_vendor  # noqa: E402
from portscra.risk import RONNE_2024, OutageCostPerHour  # noqa: E402
from portscra.taxonomy import build_scenarios  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", default=None, help="Vendor key for full clauses.")
    parser.add_argument("--clauses", action="store_true")
    parser.add_argument("--budget", type=float, default=25_000)
    args = parser.parse_args()

    print("\n=== Security requirements by supplier (ENISA phase 3) ===\n")
    print("  Requirements are scoped to what each supplier provides, so the")
    print("  crane OEM and the SaaS provider get different demands. Strictness")
    print("  escalates where the supplied asset is critical.\n")

    header = (f"  {'supplier':42s} {'reqs':>5s} {'essential':>10s} "
              f"{'unmet':>6s} {'unverified':>11s}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    sets = {}
    for vendor in EXAMPLE_VENDORS:
        result = requirements_for_vendor(vendor)
        sets[vendor.key] = result
        print(f"  {vendor.name[:40]:42s} {len(result.requirements):5d} "
              f"{len(result.by_tier(Tier.ESSENTIAL)):10d} "
              f"{len(result.unmet):6d} {len(result.unverified):11d}")

    print("\n  'Unverified' means the port never asked -- not that the supplier")
    print("  passed. Not asking is not the same as passing.")

    print("\n--- essential gaps, worth raising before renewal ---")
    for vendor in EXAMPLE_VENDORS:
        gaps = sets[vendor.key].essential_gaps
        if gaps:
            print(f"\n  {vendor.name}")
            for requirement in gaps:
                print(f"    {requirement.id}  {requirement.title}")
                print(f"          evidence to request: {requirement.evidence}")

    if args.clauses or args.vendor:
        key = args.vendor or EXAMPLE_VENDORS[0].key
        chosen = next((v for v in EXAMPLE_VENDORS if v.key == key), None)
        if chosen is None:
            print(f"\n  no vendor with key {key!r}")
            return 1
        print("\n" + "=" * 72)
        print(as_clauses(sets[chosen.key], tier=Tier.ESSENTIAL))

    # ------------------------------------------------------------ phase 4
    print("\n=== Cybersecurity maturity (ENISA phase 4) ===\n")
    print("  ENISA's three levels: 1 Basic, 2 Intermediate, 3 Optimal.")
    print("  The port's portfolio implies a maturity profile, so a budget can be")
    print("  read in ENISA's terms as well as in euro.\n")

    scenarios = build_scenarios(OutageCostPerHour(RONNE_2024))
    for budget in (0, args.budget, sum(c.annual_cost_eur for c in CATALOGUE)):
        portfolio = optimise(scenarios, CATALOGUE, budget)
        profile = maturity_from_controls([c.id for c in portfolio.controls])
        by_category = profile.by_category()
        print(f"  EUR {budget:>7,.0f} spent -> overall {profile.overall:.2f}/3  "
              f"(supply-chain measures {profile.supply_chain_score():.2f})")
        for category, score in sorted(by_category.items()):
            print(f"                   {CATEGORY_NAMES[category]:26s} {score:.2f}")

    portfolio = optimise(scenarios, CATALOGUE, args.budget)
    profile = maturity_from_controls([c.id for c in portfolio.controls])
    print(f"\n--- what the EUR {args.budget:,.0f} portfolio leaves behind ---")
    for measure, level in profile.gaps(target=2)[:6]:
        print(f"  {measure.code}  {measure.name[:44]:46s} "
              f"level {level} ({LEVEL_NAMES[level]})")
        print(f"        to reach 2: {measure.evidence[2]}")

    print("\n  Buying every control still does not reach level 3. ENISA is")
    print("  explicit that maturity cannot be achieved through a checklist")
    print("  mentality: the top level requires oversight, testing and continuous")
    print("  improvement, which is a way of working rather than a purchase.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
