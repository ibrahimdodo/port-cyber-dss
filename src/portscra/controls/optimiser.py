"""Choose a mitigation portfolio under a budget constraint.

This is Problem #1 of the brief -- "make key decisions about security
tools/techniques/procedures the organization require to use/install" -- treated
as what it actually is: constrained portfolio selection, not a ranked list.

Two modelling points that decide whether the answer is any good:

**Risk reduction composes multiplicatively, not additively.** Two controls that
each cut a scenario's frequency by 50% leave 25% of it, not 0%. Adding
percentages would let the optimiser "eliminate" a risk by stacking three
mediocre controls, and would systematically over-buy. Multiplicative composition
also makes the objective submodular -- diminishing returns -- which is what
makes greedy selection near-optimal rather than arbitrary.

**Frequency and magnitude are separate levers.** Backups do not stop ransomware;
they make it survivable. A model that collapses both into one "effectiveness"
number cannot distinguish a control that prevents an incident from one that
shortens it, and those buy very different things.

Search uses the analytic mean loss rather than a Monte Carlo run per candidate:
tens of thousands of evaluations inside the search would be intolerably slow,
and the mean is a sound ranking signal. The chosen portfolio is then handed back
to the full simulation for the distributional answer, where the tail -- which is
what actually justifies the spend -- becomes visible.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

from ..risk.montecarlo import Scenario
from .catalogue import Control

__all__ = ["Portfolio", "scenario_ale", "baseline_ale", "residual_ale",
           "optimise", "exhaustive_optimise", "efficient_frontier", "tornado"]


def scenario_ale(scenario: Scenario) -> float:
    """Analytic expected annual loss for one scenario, before any controls.

    Uses distribution means throughout. This is the search objective, not the
    reported figure -- the mean of a low-frequency high-impact risk sits in a
    gap where no actual year lands, which is why the final answer comes from
    the simulation instead.
    """
    lm = scenario.loss_magnitude
    per_event = (
        lm.downtime_hours.mean * lm.cost_per_hour.mean
        + lm.response_cost.mean
        + (lm.secondary_loss.mean * lm.secondary_probability
           if lm.secondary_loss is not None else 0.0)
    )
    return scenario.loss_event_frequency.mean * per_event


def _residual_factors(
    scenario_id: str, controls: tuple[Control, ...] | list[Control]
) -> tuple[float, float]:
    """Combined residual frequency and magnitude factors for one scenario.

    Multiplicative: each control removes a proportion of what remains after the
    others, so overlapping controls correctly show diminishing returns.
    """
    freq = 1.0
    mag = 1.0
    for control in controls:
        effect = control.effects.get(scenario_id)
        if effect is None:
            continue
        freq *= 1.0 - effect.frequency_reduction
        mag *= 1.0 - effect.magnitude_reduction
    return freq, mag


def baseline_ale(scenarios: list[Scenario]) -> float:
    return sum(scenario_ale(s) for s in scenarios)


def residual_ale(
    scenarios: list[Scenario], controls: tuple[Control, ...] | list[Control]
) -> float:
    """Expected annual loss remaining after applying a set of controls."""
    total = 0.0
    for scenario in scenarios:
        freq, mag = _residual_factors(scenario.id, controls)
        total += scenario_ale(scenario) * freq * mag
    return total


def apply_controls(
    scenarios: list[Scenario], controls: tuple[Control, ...] | list[Control]
) -> list[Scenario]:
    """Return the scenarios as they stand once a portfolio is in place.

    Frequency and magnitude distributions are scaled by their residual factors,
    producing a set of scenarios that can be simulated to get the *distribution*
    of residual risk rather than only its mean. That distinction matters: the
    optimiser searches on means for speed, but the tail is what the port is
    actually buying protection against.

    Scaling goes through `Distribution.scale`, so this works for derived
    vendor-driven frequencies as well as plain three-point estimates.
    """
    from ..risk.montecarlo import LossMagnitude, Scenario as _Scenario

    adjusted = []
    for scenario in scenarios:
        freq_factor, mag_factor = _residual_factors(scenario.id, controls)
        lm = scenario.loss_magnitude
        adjusted.append(
            _Scenario(
                id=scenario.id,
                name=scenario.name,
                loss_event_frequency=scenario.loss_event_frequency.scale(freq_factor),
                loss_magnitude=LossMagnitude(
                    downtime_hours=lm.downtime_hours.scale(mag_factor),
                    cost_per_hour=lm.cost_per_hour,
                    response_cost=lm.response_cost.scale(mag_factor),
                    secondary_loss=lm.secondary_loss,
                    secondary_probability=lm.secondary_probability * mag_factor,
                ),
                enisa_threat=scenario.enisa_threat,
                attack_techniques=scenario.attack_techniques,
                stride=scenario.stride,
                notes=scenario.notes,
            )
        )
    return adjusted


@dataclass(frozen=True)
class Portfolio:
    """A selected set of controls and what it buys."""

    controls: tuple[Control, ...]
    budget: float
    cost: float
    baseline_ale: float
    residual_ale: float
    per_scenario: dict[str, tuple[float, float]]
    method: str = "greedy"

    @property
    def reduction(self) -> float:
        return self.baseline_ale - self.residual_ale

    @property
    def reduction_pct(self) -> float:
        return self.reduction / self.baseline_ale if self.baseline_ale else 0.0

    @property
    def rosi(self) -> float:
        """Return on security investment: (loss avoided - cost) / cost.

        Reported because stakeholders ask for it, but it deserves a caveat in
        any write-up: it compares an expected value against a certain cost, so
        a positive ROSI is not a promise of a positive year. The exceedance
        curve is the honest companion figure.
        """
        return (self.reduction - self.cost) / self.cost if self.cost else 0.0

    @property
    def headroom(self) -> float:
        return self.budget - self.cost

    def explain(self) -> str:
        lines = [
            f"Budget EUR {self.budget:,.0f} | spent EUR {self.cost:,.0f} "
            f"| unspent EUR {self.headroom:,.0f}",
            f"Expected annual loss EUR {self.baseline_ale:,.0f} -> "
            f"EUR {self.residual_ale:,.0f} "
            f"({self.reduction_pct:.0%} reduction, ROSI {self.rosi:+.1f}x)",
            "",
            "Selected:",
        ]
        for control in sorted(self.controls, key=lambda c: -c.annual_cost_eur):
            lines.append(
                f"  {control.id}  EUR {control.annual_cost_eur:>7,.0f}  "
                f"IG{control.implementation_group}  {control.name}"
            )
        return "\n".join(lines)


def _make_portfolio(
    scenarios: list[Scenario],
    selected: list[Control],
    budget: float,
    method: str,
) -> Portfolio:
    per_scenario = {}
    for scenario in scenarios:
        freq, mag = _residual_factors(scenario.id, selected)
        base = scenario_ale(scenario)
        per_scenario[scenario.id] = (base, base * freq * mag)

    return Portfolio(
        controls=tuple(selected),
        budget=budget,
        cost=sum(c.annual_cost_eur for c in selected),
        baseline_ale=baseline_ale(scenarios),
        residual_ale=residual_ale(scenarios, selected),
        per_scenario=per_scenario,
        method=method,
    )


def optimise(
    scenarios: list[Scenario],
    catalogue: tuple[Control, ...] | list[Control],
    budget: float,
    *,
    local_search: bool = True,
) -> Portfolio:
    """Select the best affordable portfolio by greedy marginal value.

    At each step, choose the affordable control with the highest reduction in
    expected loss *per euro*, recomputing marginals after every pick so that
    overlap with already-selected controls is accounted for.

    Greedy is a defensible choice rather than a shortcut: the objective is
    submodular, for which greedy carries a (1 - 1/e) worst-case guarantee under
    a knapsack constraint and typically lands on the optimum for catalogues this
    size. `local_search` then attempts single swaps, which closes most of the
    remaining gap. `exhaustive_optimise` verifies the result on small instances.
    """
    if budget < 0:
        raise ValueError("budget must not be negative")

    remaining = [c for c in catalogue if c.annual_cost_eur <= budget]
    selected: list[Control] = []
    spent = 0.0

    while remaining:
        current = residual_ale(scenarios, selected)
        best, best_value = None, 0.0

        for control in remaining:
            if spent + control.annual_cost_eur > budget:
                continue
            candidate_loss = residual_ale(scenarios, selected + [control])
            gain = current - candidate_loss
            if control.annual_cost_eur <= 0:
                value = float("inf") if gain > 0 else 0.0
            else:
                value = gain / control.annual_cost_eur
            if value > best_value:
                best, best_value = control, value

        if best is None:
            break
        selected.append(best)
        spent += best.annual_cost_eur
        remaining.remove(best)

    if local_search:
        selected = _improve_by_swapping(scenarios, catalogue, selected, budget)

    return _make_portfolio(scenarios, selected, budget, "greedy+swap" if local_search else "greedy")


def _improve_by_swapping(
    scenarios: list[Scenario],
    catalogue: tuple[Control, ...] | list[Control],
    selected: list[Control],
    budget: float,
) -> list[Control]:
    """Escape the standard greedy-knapsack trap.

    Greedy buys by value per euro, so it can fill the budget with cheap
    high-ratio controls and then be unable to afford a single better one. A
    one-for-one swap does not recover that -- affording the better control may
    require evicting *several* cheap picks at once.

    So for each control not selected, this tries to make room by evicting
    already-selected controls in ascending order of what they contribute, and
    keeps the result if total loss falls. Repeats until no move improves.
    """
    selected = list(selected)
    improved = True

    while improved:
        improved = False
        current = residual_ale(scenarios, selected)
        cost = sum(c.annual_cost_eur for c in selected)
        outside = [c for c in catalogue if c not in selected]

        # Plain additions first: strictly better whenever budget allows.
        for candidate in outside:
            if cost + candidate.annual_cost_eur <= budget:
                trial = selected + [candidate]
                if residual_ale(scenarios, trial) < current - 1e-9:
                    selected, improved = trial, True
                    break
        if improved:
            continue

        # Then admit a candidate by evicting whatever it takes to afford it.
        for candidate in outside:
            if candidate.annual_cost_eur > budget:
                continue

            # Rank incumbents by marginal contribution, cheapest-to-lose first.
            def _marginal(control: Control) -> float:
                without = [c for c in selected if c is not control]
                return residual_ale(scenarios, without) - current

            evictable = sorted(selected, key=_marginal)
            kept = list(selected)
            for victim in evictable:
                if sum(c.annual_cost_eur for c in kept) + candidate.annual_cost_eur <= budget:
                    break
                kept = [c for c in kept if c is not victim]

            trial_cost = sum(c.annual_cost_eur for c in kept) + candidate.annual_cost_eur
            if trial_cost > budget:
                continue
            trial = kept + [candidate]
            if residual_ale(scenarios, trial) < current - 1e-9:
                selected, improved = trial, True
                break

    return selected


def exhaustive_optimise(
    scenarios: list[Scenario],
    catalogue: tuple[Control, ...] | list[Control],
    budget: float,
) -> Portfolio:
    """Brute-force optimum over every affordable subset.

    Exponential, so only usable for small catalogues -- its purpose is to verify
    that the greedy result is optimal on instances where the truth is knowable,
    not to be run on the full catalogue.
    """
    catalogue = list(catalogue)
    if len(catalogue) > 22:
        raise ValueError(
            f"exhaustive search over {len(catalogue)} controls is infeasible; "
            "use optimise() instead"
        )

    best_selection: list[Control] = []
    best_loss = residual_ale(scenarios, [])

    for size in range(1, len(catalogue) + 1):
        for combination in itertools.combinations(catalogue, size):
            if sum(c.annual_cost_eur for c in combination) > budget:
                continue
            loss = residual_ale(scenarios, list(combination))
            if loss < best_loss - 1e-9:
                best_loss, best_selection = loss, list(combination)

    return _make_portfolio(scenarios, best_selection, budget, "exhaustive")


def efficient_frontier(
    scenarios: list[Scenario],
    catalogue: tuple[Control, ...] | list[Control],
    budgets: list[float],
) -> list[Portfolio]:
    """Optimal portfolio at each budget level.

    The resulting curve is the most useful single artefact for a budget
    conversation: it shows where diminishing returns set in, which is the
    question a port director actually has -- not "what should I buy" but "how
    much is enough".
    """
    return [optimise(scenarios, catalogue, budget) for budget in sorted(budgets)]


def tornado(
    scenarios: list[Scenario],
    portfolio: Portfolio,
    *,
    perturbation: float = 0.5,
) -> list[tuple[str, float, float]]:
    """Sensitivity of the portfolio's residual loss to each control's assumed
    effectiveness.

    Returns (control id, low, high) residual losses when that control's
    effectiveness is scaled by (1 - perturbation) and (1 + perturbation). Wide
    bars mark the estimates worth researching before committing budget; narrow
    ones mark assumptions that do not matter, which is equally useful to know.
    """
    if not 0 < perturbation <= 1:
        raise ValueError("perturbation must be in (0, 1]")

    from .catalogue import Control as _Control, ControlEffect

    results = []
    for target in portfolio.controls:
        variants = []
        for scale in (1 - perturbation, 1 + perturbation):
            effects = {
                sid: ControlEffect(
                    min(1.0, e.frequency_reduction * scale),
                    min(1.0, e.magnitude_reduction * scale),
                    e.rationale,
                )
                for sid, e in target.effects.items()
            }
            adjusted = _Control(
                target.id, target.name, target.description, target.annual_cost_eur,
                target.cis_safeguards, target.nis2, target.implementation_group,
                effects, target.foundational,
            )
            others = [c for c in portfolio.controls if c.id != target.id]
            variants.append(residual_ale(scenarios, others + [adjusted]))
        results.append((target.id, variants[1], variants[0]))

    # Widest swing first: that is the ordering a tornado chart needs.
    return sorted(results, key=lambda r: r[2] - r[1], reverse=True)
