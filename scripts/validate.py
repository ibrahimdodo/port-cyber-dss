#!/usr/bin/env python3
"""Run the validation suite: incident replay, baseline duel, persona sweep.

Usage
-----
    python scripts/validate.py
    python scripts/validate.py --budget 25000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from portscra.controls import CATALOGUE  # noqa: E402
from portscra.risk import RONNE_2024, OutageCostPerHour, simulate  # noqa: E402
from portscra.taxonomy import build_scenarios  # noqa: E402
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES  # noqa: E402
from portscra.validation import (  # noqa: E402
    INCIDENTS,
    compare_to_matrix,
    qualitative_score,
    range_compression,
    rank_agreement,
    replay_incident,
)


def eur(value: float) -> str:
    return f"EUR {value:,.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=float, default=25_000)
    args = parser.parse_args()

    cost = OutageCostPerHour(RONNE_2024)
    scenarios = build_scenarios(cost)
    by_id = {s.id: s for s in scenarios}
    names = {t.id: t.name for t in SCENARIO_TEMPLATES}

    # ---------------------------------------------------------------- 1
    print("\n" + "=" * 78)
    print("1. INCIDENT REPLAY -- does the model contain what actually happened?")
    print("=" * 78)
    print("\n  Anchoring incidents set the estimates, so they can only check")
    print("  consistency. Only the held-out ones are evidence.\n")

    for held_out in (False, True):
        group = [i for i in INCIDENTS if i.used_as_anchor != held_out]
        label = "HELD OUT (evidence)" if held_out else "ANCHORS (consistency only)"
        print(f"  --- {label} ---")
        print(f"  {'incident':34s} {'observed':>9s} {'model P10-P90':>18s} "
              f"{'pctile':>7s}  verdict")
        for incident in group:
            scenario = by_id.get(incident.scenario_id)
            if scenario is None:
                continue
            r = replay_incident(scenario, incident)
            band = f"{r.p10:.0f}-{r.p90:.0f} h"
            print(f"  {incident.name[:32]:34s} {incident.downtime_hours:7.0f} h "
                  f"{band:>18s} {r.percentile:6.0f}%  {r.verdict}")
        print()

    misses = [
        replay_incident(by_id[i.scenario_id], i)
        for i in INCIDENTS
        if not i.used_as_anchor and i.scenario_id in by_id
    ]
    outside = [r for r in misses if not r.inside_band]
    print(f"  {len(misses) - len(outside)} of {len(misses)} held-out incidents "
          f"fall inside the predicted band.")

    # Band containment is a weak test once the band starts at zero. The sharper
    # check is whether the model gets the *rate* of no-disruption events right.
    s2 = by_id["S2"]
    modelled = 1.0 - s2.loss_magnitude.disruption_probability
    s2_incidents = [i for i in INCIDENTS if i.scenario_id == "S2"]
    observed_zero = sum(1 for i in s2_incidents if i.downtime_hours == 0)
    observed = observed_zero / len(s2_incidents)
    print(f"\n  Sharper check -- share of ransomware events causing NO "
          f"operational downtime:")
    print(f"    model {modelled:.0%}   observed {observed:.0%} "
          f"({observed_zero} of {len(s2_incidents)} documented incidents)")
    print("    Containment inside a band that begins at zero is easy to pass.")
    print("    Matching the rate at which nothing operational happens is not,")
    print("    and it is the parameter the replay actually forced us to add.")
    if outside:
        print("\n  Failures, stated rather than buried:")
        for r in outside:
            print(f"    - {r.incident.name} at {r.incident.downtime_hours:.0f} h "
                  f"sits {r.verdict.lower()} ({r.percentile:.0f}th percentile)")
        if any(r.percentile < 10 for r in outside):
            print("\n    Barcelona and San Diego both suffered ransomware without")
            print("    stopping the quay: IT was hit, ships kept working. The S2")
            print("    downtime estimate has a floor of 24 hours and therefore")
            print("    cannot produce that outcome at all. The model overstates")
            print("    how often a supplier-borne ransomware event becomes an")
            print("    operational outage. Fix: lower the minimum toward zero and")
            print("    re-anchor the mode, which will reduce S2's expected loss.")

    # ---------------------------------------------------------------- 2
    print("\n" + "=" * 78)
    print("2. BASELINE DUEL -- quantitative model against a 5x5 risk matrix")
    print("=" * 78)

    print(f"\n  {'scenario':46s} {'matrix':>18s} {'quantitative ALE':>18s}")
    for scenario in sorted(scenarios, key=lambda s: -qualitative_score(s).score):
        score = qualitative_score(scenario)
        from portscra.controls.optimiser import scenario_ale
        print(f"  {names[scenario.id][:44]:46s} "
              f"{score.rating + ' (' + str(score.score) + ')':>18s} "
              f"{eur(scenario_ale(scenario)):>18s}")

    print("\n  --- range compression (Cox 2008) ---")
    for rating, ids in range_compression(scenarios).items():
        if len(ids) > 1:
            from portscra.controls.optimiser import scenario_ale
            ales = sorted(scenario_ale(by_id[i]) for i in ids)
            spread = ales[-1] / ales[0] if ales[0] else float("inf")
            print(f"  {rating:10s} {', '.join(ids):28s} "
                  f"expected loss spans {spread:.1f}x within one rating")
    print("\n  The matrix cannot separate risks it rates alike, even when they")
    print("  differ several-fold in expected loss. That is the range compression")
    print("  Cox identifies, and it is why a heat map cannot prioritise spending.")

    print(f"\n  rank agreement (Spearman) with quantitative ordering: "
          f"{rank_agreement(scenarios):+.2f}")

    print("\n  --- the decision test: same budget, both methods ---")
    print(f"  {'budget':>9s}  {'matrix residual':>16s} {'optimised residual':>19s} "
          f"{'advantage':>11s}")
    for budget in (10_000, 15_000, 25_000, 40_000, 60_000):
        c = compare_to_matrix(scenarios, CATALOGUE, budget)
        print(f"  {eur(budget):>9s}  {eur(c.matrix_residual):>16s} "
              f"{eur(c.quantitative_residual):>19s} "
              f"{eur(c.advantage):>11s}  ({c.advantage_pct:+.0%} of baseline)")

    c = compare_to_matrix(scenarios, CATALOGUE, args.budget)
    print(f"\n  At {eur(args.budget)}:")
    print(f"    matrix buys      {', '.join(c.matrix_controls)}")
    print(f"    optimiser buys   {', '.join(c.quantitative_controls)}")
    only_q = set(c.quantitative_controls) - set(c.matrix_controls)
    only_m = set(c.matrix_controls) - set(c.quantitative_controls)
    if only_q or only_m:
        print(f"    optimiser adds   {', '.join(sorted(only_q)) or 'nothing'}")
        print(f"    optimiser drops  {', '.join(sorted(only_m)) or 'nothing'}")

    # ---------------------------------------------------------------- 3
    print("\n" + "=" * 78)
    print("3. PERSONA SWEEP -- does the recommendation scale sensibly?")
    print("=" * 78)
    print(f"\n  Rønne Havn A/S employs {RONNE_2024.employees_fte} FTE, so the "
          f"brief's 10/50/100 personas")
    print("  bracket the real case rather than describing it.\n")
    print(f"  {'persona':>8s} {'scale':>6s} {'baseline ALE':>14s} "
          f"{'residual':>12s} {'buys':>5s}  portfolio")
    for persona, scale in ((10, 0.25), (50, 0.6), (100, 1.0)):
        scaled = build_scenarios(cost, scale=scale)
        from portscra.controls import optimise
        p = optimise(scaled, CATALOGUE, args.budget)
        print(f"  {persona:>8d} {scale:>6.2f} {eur(p.baseline_ale):>14s} "
              f"{eur(p.residual_ale):>12s} {len(p.controls):>5d}  "
              f"{','.join(sorted(x.id for x in p.controls))}")
    print("\n  Costs scale with persona but the hourly outage cost does not:")
    print("  it comes from Rønne's actual accounts. A smaller port would have")
    print("  lower revenue too, so this sweep varies response and regulatory")
    print("  exposure only -- a limitation worth stating rather than hiding.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
