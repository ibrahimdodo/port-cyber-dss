#!/usr/bin/env python3
"""Awareness assessment driven by this port's own top risks.

Answers the brief's "identify cyber-security awareness level for specific
vendor-related risks" -- the operative word being *specific*. The vignettes are
selected by the risk engine's ranking, so a port whose largest exposure is
invoice fraud is trained on invoice fraud.

Then it closes the loop: the measured score feeds back into scenario
frequencies, so training moves the expected loss and the recommended portfolio.

Usage
-----
    python scripts/demo_awareness.py
    python scripts/demo_awareness.py --show-quiz   # print the selected vignettes
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("portscra") is None:  # not pip-installed; run in place
    sys.path.insert(0, str(REPO / "src"))

from portscra.awareness import (  # noqa: E402
    HUMAN_FACTOR_WEIGHT,
    ROLE_NAMES,
    VIGNETTES,
    apply_awareness,
    awareness_multiplier,
    score_responses,
    vignettes_for,
)
from portscra.controls import CATALOGUE, optimise  # noqa: E402
from portscra.controls.optimiser import baseline_ale, scenario_ale  # noqa: E402
from portscra.examples import EXAMPLE_VENDORS  # noqa: E402
from portscra.graph import DependencyGraph, build_scenarios_from_vendors  # noqa: E402
from portscra.risk import RONNE_2024, OutageCostPerHour  # noqa: E402
from portscra.taxonomy import build_scenarios  # noqa: E402
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES  # noqa: E402
from portscra.vendor import LikelihoodModel  # noqa: E402


def eur(value: float) -> str:
    return f"EUR {value:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-quiz", action="store_true")
    parser.add_argument("--budget", type=float, default=25_000)
    args = parser.parse_args()

    cost = OutageCostPerHour(RONNE_2024)
    model = LikelihoodModel()
    graph = DependencyGraph(EXAMPLE_VENDORS)
    assessments = {v.key: model.assess(v) for v in EXAMPLE_VENDORS}
    scenarios = build_scenarios_from_vendors(
        graph, assessments, cost, fallback_scenarios=build_scenarios(cost))
    names = {t.id: t.name for t in SCENARIO_TEMPLATES}

    ranked = [s.id for s in sorted(scenarios, key=scenario_ale, reverse=True)]

    print("\n=== Awareness assessment, generated from this port's risk ranking ===\n")
    print("  Training order follows expected loss, not a course catalogue:")
    for position, sid in enumerate(ranked[:4], 1):
        loss = scenario_ale(next(s for s in scenarios if s.id == sid))
        print(f"   {position}. {names[sid][:52]:54s} {eur(loss):>12s}/yr")

    selected = vignettes_for(ranked)
    print(f"\n  {len(selected)} vignettes selected, covering "
          f"{len({v.scenario_id for v in selected})} scenarios and "
          f"{len({v.role for v in selected})} roles.")
    print("  Change the supplier list and this ordering changes with it.")

    if args.show_quiz:
        for vignette in selected:
            print(f"\n  --- {vignette.id} [{ROLE_NAMES[vignette.role]}] "
                  f"-> {names[vignette.scenario_id]}")
            print(f"  {vignette.situation}")
            print(f"  {vignette.question}")
            for i, option in enumerate(vignette.options):
                print(f"     {i}) {option.text}")
            if vignette.anchor:
                print(f"     anchor: {vignette.anchor}")

    # Three illustrative response sets. Real use collects these from staff.
    perfect = {v.id: v.correct_index for v in VIGNETTES}
    wrong = {v.id: next(i for i in range(len(v.options)) if i != v.correct_index)
             for v in VIGNETTES}
    from portscra.awareness import MANAGEMENT
    mixed = dict(perfect)
    for v in VIGNETTES:
        if v.role == MANAGEMENT or v.scenario_id == "S3":
            mixed[v.id] = wrong[v.id]

    print("\n--- three illustrative cohorts ---")
    header = f"  {'cohort':22s} {'overall':>8s} {'weakest area':>34s} {'mgmt gap':>9s}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    results = {}
    for label, responses in (("well trained", perfect), ("untrained", wrong),
                             ("strong except finance", mixed)):
        result = score_responses(responses)
        results[label] = result
        gap = result.management_gap()
        sid, score = result.weakest_scenarios(1)[0]
        # Naming a "weakest area" when every area scored full marks would be
        # an artefact of sort order, not a finding.
        weakest = "nothing below full marks" if score >= 1.0 else names[sid][:32]
        print(f"  {label:22s} {result.overall:7.0%} "
              f"{weakest:>34s} "
              f"{(f'{gap:+.0%}' if gap is not None else 'n/a'):>9s}")

    print("\n  The management gap is reported separately because NIS2 Article")
    print("  20(2) obliges the management body itself to undergo training. An")
    print("  organisational average can look healthy while the people carrying")
    print("  the legal duty are the weakest group.")

    print("\n--- how much training can actually move ---")
    print(f"  {'scenario':46s} {'human factor':>13s} {'freq x if trained':>18s}")
    trained = results["well trained"]
    for sid in ranked:
        weight = HUMAN_FACTOR_WEIGHT.get(sid, 0.0)
        print(f"  {names[sid][:44]:46s} {weight:12.0%} "
              f"{awareness_multiplier(trained, sid):17.2f}x")
    print("\n  Training moves invoice fraud a long way and a signed trojanized")
    print("  update barely at all. A tool claiming to reduce every risk equally")
    print("  would be selling training rather than measuring it.")

    print("\n--- the closed loop: what training is worth ---")
    base = baseline_ale(scenarios)
    print(f"  {'cohort':22s} {'expected annual loss':>21s} {'vs untrained':>14s}")
    untrained_loss = baseline_ale(apply_awareness(scenarios, results["untrained"]))
    for label in ("untrained", "strong except finance", "well trained"):
        loss = baseline_ale(apply_awareness(scenarios, results[label]))
        delta = loss - untrained_loss
        print(f"  {label:22s} {eur(loss):>21s} "
              f"{(eur(delta) if delta else '--'):>14s}")
    print(f"  {'(no assessment)':22s} {eur(base):>21s}")

    saving = untrained_loss - baseline_ale(
        apply_awareness(scenarios, results["well trained"]))
    print(f"\n  Moving from untrained to well trained is worth {eur(saving)} a year")
    print(f"  in expected loss. Awareness training (control C15) costs EUR 3,500,")
    print("  so the case makes itself -- but only for the scenarios where human")
    print("  judgement is actually in the loop.")

    print("\n--- does it change what to buy? ---")
    for label in ("untrained", "well trained"):
        adjusted = apply_awareness(scenarios, results[label])
        portfolio = optimise(adjusted, CATALOGUE, args.budget)
        print(f"  [{label:13s}] {eur(portfolio.residual_ale):>10s} residual  "
              f"{','.join(sorted(c.id for c in portfolio.controls))}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
