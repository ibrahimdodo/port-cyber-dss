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
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from portscra.vendor import (  # noqa: E402
    CRITERIA,
    DEFAULT_WEIGHTS,
    LikelihoodModel,
    Vendor,
    VendorSignals,
    matrix_from_comparisons,
    nis2_coverage,
    weights_from_matrix,
)


def a(**kwargs) -> dict[str, int]:
    """Shorthand: a(Q1=0, Q2=3) -> {"Q1": 0, "Q2": 3}."""
    return dict(kwargs)


#: A plausible supplier list for a port of Rønne's size and mix.
VENDORS = [
    Vendor(
        "msp", "Managed service provider (outsourced IT)", "MSP",
        supplies=("workstations", "servers", "networks", "corporate_systems"),
        answers=a(Q1=0, Q2=1, Q3=1, Q4=1, Q5=1, Q6=3, Q7=1, Q8=1, Q9=1, Q10=1,
                  Q11=1, Q12=1, Q13=0, Q14=1, Q15=3, Q16=2, Q17=1, Q18=2, Q19=1, Q20=1),
        notes="Holds standing administrative access to the whole estate. For a "
              "port with no in-house security function this is the single "
              "largest concentration of risk -- the Kaseya shape.",
    ),
    Vendor(
        "tos", "Terminal operating system vendor", "software",
        supplies=("tos",),
        answers=a(Q1=1, Q2=2, Q3=2, Q4=0, Q5=0, Q6=2, Q7=3, Q8=2, Q9=2, Q10=2,
                  Q11=1, Q12=1, Q13=1, Q14=2, Q15=3, Q16=2, Q17=1, Q18=2, Q19=0, Q20=0),
        signals=VendorSignals(max_epss=0.12, source="illustrative"),
        notes="Operations stop without it and replacement would take years. "
              "The SolarWinds vector runs through its update channel.",
    ),
    Vendor(
        "cloud_office", "Cloud productivity and email suite", "SaaS",
        supplies=("cloud", "corporate_systems", "commercial_financial"),
        answers=a(Q1=2, Q2=3, Q3=3, Q4=2, Q5=2, Q6=3, Q7=3, Q8=3, Q9=3, Q10=2,
                  Q11=3, Q12=1, Q13=2, Q14=3, Q15=2, Q16=3, Q17=0, Q18=2, Q19=2, Q20=2),
        notes="Strong posture, but holds the mailboxes through which invoices "
              "are agreed -- the business email compromise path.",
    ),
    Vendor(
        "crane_oem", "Crane and handling equipment OEM", "OT",
        supplies=("loading_unloading", "ics"),
        answers=a(Q1=1, Q2=0, Q3=0, Q4=1, Q5=1, Q6=0, Q7=1, Q8=0, Q9=0, Q10=1,
                  Q11=0, Q12=0, Q13=0, Q14=0, Q15=3, Q16=0, Q17=2, Q18=0, Q19=0, Q20=0),
        notes="Remote diagnostics into safety-relevant equipment, minimal "
              "security programme. Typical of OT suppliers to small ports.",
    ),
    Vendor(
        "gate_cctv", "Gate, ANPR and CCTV integrator", "OT",
        supplies=("access_control", "detection", "portuary_infrastructure"),
        answers=a(Q1=1, Q2=1, Q3=1, Q4=1, Q5=1, Q6=1, Q7=0, Q8=0, Q9=0, Q10=1,
                  Q11=0, Q12=0, Q13=0, Q14=0, Q15=1, Q16=1, Q17=1, Q18=1, Q19=2, Q20=2),
        signals=VendorSignals(kev_count=1, max_epss=0.35, source="illustrative"),
        notes="The least-patched estate in most ports; the Antwerp "
              "container-release manipulation ran through this class of system.",
    ),
    Vendor(
        "pcs", "Port community system operator", "platform",
        supplies=("pcs", "mandatory_declarations", "operational_data"),
        answers=a(Q1=2, Q2=2, Q3=2, Q4=1, Q5=1, Q6=3, Q7=2, Q8=2, Q9=2, Q10=2,
                  Q11=2, Q12=2, Q13=1, Q14=2, Q15=3, Q16=2, Q17=0, Q18=2, Q19=0, Q20=1),
        notes="Shared across many ports, so one compromise reaches all of them. "
              "Holds crew and passenger declarations.",
    ),
    Vendor(
        "booking", "Ferry booking and check-in platform", "SaaS",
        supplies=("corporate_systems", "commercial_financial"),
        answers=a(Q1=2, Q2=2, Q3=2, Q4=1, Q5=1, Q6=3, Q7=2, Q8=1, Q9=1, Q10=1,
                  Q11=1, Q12=2, Q13=1, Q14=1, Q15=1, Q16=2, Q17=0, Q18=2, Q19=1, Q20=1),
        signals=VendorSignals(recent_breach=True, source="illustrative"),
        notes="Holds passenger personal data at volume -- GDPR and NIS2 exposure.",
    ),
    Vendor(
        "oss_lib", "Open-source component in supplied software", "freeware",
        supplies=("servers", "workstations"),
        # No questionnaire is possible: there is no vendor to send it to. This
        # is the brief's "freeware?" case, and the reason external signals are
        # not optional.
        signals=VendorSignals(openssf_scorecard=3.2, max_epss=0.08,
                              source="illustrative OpenSSF Scorecard"),
        notes="Nobody to send a questionnaire to. Assessed entirely on public "
              "signals; the xz-utils backdoor was this shape.",
    ),
]


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
