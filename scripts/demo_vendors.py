#!/usr/bin/env python3
"""Assess a small port's supplier list and rank it by compromise likelihood.

The vendors below are ILLUSTRATIVE ROLES, not real companies, and the answers
are plausible profiles rather than findings about anyone's actual security. A
real assessment replaces them with responses from the suppliers themselves.
Naming real vendors here would assert things about their posture that this
project has no evidence for.

Usage
-----
    python scripts/demo_vendors.py
    python scripts/demo_vendors.py --ahp     # run the pairwise weighting demo
    python scripts/demo_vendors.py --nis2    # show NIS2 Article 21 coverage
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("portscra") is None:  # not pip-installed; run in place
    sys.path.insert(0, str(REPO / "src"))

from portscra.examples import EXAMPLE_VENDORS  # noqa: E402
from portscra.vendor import (  # noqa: E402
    CRITERIA,
    DEFAULT_WEIGHTS,
    LikelihoodModel,
    matrix_from_comparisons,
    nis2_coverage,
    weights_from_matrix,
)


#: Imported from the package so the dashboard and any notebook can use the
#: same list without importing data out of a script.
VENDORS = EXAMPLE_VENDORS


def run_ahp_demo() -> dict[str, float]:
    """Elicit criterion weights by pairwise comparison, with a consistency check.

    Stands in for the session the original brief offered teacher help with.
    Since this is a solo build, the elicitation became a feature: the port does
    the exercise and the tool checks whether its answers hang together.
    """
    criteria = [c.key for c in CRITERIA]
    # A plausible set of judgements from a port IT manager, on Saaty's 1-9 scale.
    comparisons = {
        ("access", "posture"): 3,
        ("access", "data_exposure"): 5,
        ("access", "incident_history"): 5,
        ("asset_criticality", "posture"): 3,
        ("asset_criticality", "data_exposure"): 4,
        ("asset_criticality", "incident_history"): 5,
        ("update_channel", "posture"): 2,
        ("update_channel", "incident_history"): 3,
        ("substitutability", "incident_history"): 2,
        ("posture", "incident_history"): 2,
        ("data_exposure", "incident_history"): 2,
    }
    matrix = matrix_from_comparisons(criteria, comparisons)
    result = weights_from_matrix(criteria, matrix)

    print("\n=== AHP criterion weighting ===\n")
    for name, weight in result.ranked():
        label = next(c.name for c in CRITERIA if c.key == name)
        bar = "#" * int(60 * weight)
        print(f"  {label:36s} {weight:.3f} {bar}")
    verdict = "acceptable" if result.is_consistent else "TOO INCONSISTENT - revisit"
    print(f"\n  consistency ratio {result.consistency_ratio:.4f} ({verdict})")
    print(f"  lambda_max {result.lambda_max:.4f} against n = {len(criteria)}")
    return result.as_dict()


def show_nis2() -> None:
    print("\n=== NIS2 Article 21(2) coverage ===\n")
    for point, questions in nis2_coverage().items():
        marker = ", ".join(questions) if questions else "-- not covered --"
        print(f"  {point}")
        print(f"      {marker}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ahp", action="store_true",
                        help="Derive weights by pairwise comparison instead of defaults.")
    parser.add_argument("--nis2", action="store_true",
                        help="Show which questions evidence each NIS2 measure.")
    args = parser.parse_args()

    if args.nis2:
        show_nis2()
        return 0

    weights = run_ahp_demo() if args.ahp else dict(DEFAULT_WEIGHTS)
    model = LikelihoodModel(weights=weights)
    ranked = model.rank(VENDORS)

    source = "AHP pairwise session" if args.ahp else "literature defaults"
    print(f"\n=== Vendor compromise likelihood ({source}) ===\n")
    header = (f"{'vendor':44s} {'posture':>8s} {'signals':>8s} "
              f"{'P(compromise)/yr':>22s} {'cover':>6s}")
    print(header)
    print("-" * len(header))

    for assessment in ranked:
        p = assessment.annual_probability
        band = f"{p.minimum:5.1%} .. {p.maximum:5.1%} ({p.most_likely:4.1%})"
        print(f"{assessment.vendor.name[:42]:44s} "
              f"{assessment.posture_score:8.2f} "
              f"{assessment.signal_multiplier:7.2f}x "
              f"{band:>22s} {assessment.coverage:5.0%}")

    print("\n--- worst vendor, in full ---\n")
    print(ranked[0].explain())

    print("\n--- what the ranking is telling you ---")
    worst = ranked[0]
    unassessed = [r for r in ranked if r.coverage == 0.0]
    print(f"  Highest likelihood: {worst.vendor.name}.")
    print(f"    {worst.vendor.notes}")
    if unassessed:
        print(f"  {len(unassessed)} vendor(s) could not be sent a questionnaire "
              f"and rest entirely on public signals:")
        for r in unassessed:
            print(f"    - {r.vendor.name}")
        print("    An unassessed vendor scores mid-range, not low. Refusing to")
        print("    answer must never be the cheapest route to looking safe.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
