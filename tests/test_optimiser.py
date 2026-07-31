"""Tests for the control catalogue and the budget-constrained optimiser.

The critical property is that greedy selection actually finds good portfolios.
That is checked against brute force on instances small enough to enumerate, so
the claim rests on a computed optimum rather than on the theoretical guarantee.
"""

import unittest

from portscra.controls.catalogue import (
    CATALOGUE,
    Control,
    ControlEffect,
    catalogue_for_group,
    find_control,
    total_cost,
)
from portscra.controls.optimiser import (
    baseline_ale,
    efficient_frontier,
    exhaustive_optimise,
    optimise,
    residual_ale,
    scenario_ale,
    tornado,
)
from portscra.risk.distributions import Constant, PERT
from portscra.risk.montecarlo import LossMagnitude, Scenario


def scenario(sid: str, lef: float, hours: float, rate: float = 1000.0,
             response: float = 0.0) -> Scenario:
    return Scenario(
        id=sid, name=f"scenario {sid}",
        loss_event_frequency=Constant(lef),
        loss_magnitude=LossMagnitude(
            downtime_hours=Constant(hours),
            cost_per_hour=Constant(rate),
            response_cost=Constant(response),
        ),
    )


def control(cid: str, cost: float, effects: dict) -> Control:
    return Control(
        cid, f"control {cid}", "test", cost, ("1.1",), ("d",), 1,
        {k: ControlEffect(*v) for k, v in effects.items()},
    )


class TestCatalogue(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [c.id for c in CATALOGUE]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_control_affects_something(self):
        """A control with no effects can never be selected and is dead weight
        in the catalogue."""
        for c in CATALOGUE:
            self.assertTrue(c.effects, f"{c.id} affects no scenario")

    def test_every_effect_references_a_real_scenario(self):
        from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES
        known = {t.id for t in SCENARIO_TEMPLATES}
        for c in CATALOGUE:
            for sid in c.effects:
                self.assertIn(sid, known, f"{c.id} references unknown scenario {sid}")

    def test_every_control_cites_cis_and_nis2(self):
        for c in CATALOGUE:
            self.assertTrue(c.cis_safeguards, f"{c.id} cites no CIS safeguard")
            self.assertTrue(c.nis2, f"{c.id} cites no NIS2 point")

    def test_reductions_are_proportions(self):
        with self.assertRaises(ValueError):
            ControlEffect(frequency_reduction=1.5)
        with self.assertRaises(ValueError):
            ControlEffect(magnitude_reduction=-0.1)

    def test_rejects_negative_cost(self):
        with self.assertRaises(ValueError):
            Control("X", "x", "x", -1, ("1.1",), ("d",), 1)

    def test_rejects_bad_implementation_group(self):
        with self.assertRaises(ValueError):
            Control("X", "x", "x", 100, ("1.1",), ("d",), 9)

    def test_ig1_is_a_cheaper_subset(self):
        """IG1 is CIS's essential-hygiene baseline and must be affordable
        relative to the whole catalogue for a small port."""
        ig1 = catalogue_for_group(1)
        self.assertLess(total_cost(ig1), total_cost(CATALOGUE))
        self.assertTrue(set(ig1).issubset(set(CATALOGUE)))

    def test_lookup(self):
        self.assertIsNotNone(find_control("C01"))
        self.assertIsNone(find_control("nope"))


class TestRiskArithmetic(unittest.TestCase):
    def test_scenario_ale_is_frequency_times_magnitude(self):
        s = scenario("S1", lef=0.5, hours=10, rate=1000, response=2000)
        self.assertAlmostEqual(scenario_ale(s), 0.5 * (10 * 1000 + 2000))

    def test_secondary_loss_is_weighted_by_its_probability(self):
        s = Scenario(
            id="S1", name="s",
            loss_event_frequency=Constant(1.0),
            loss_magnitude=LossMagnitude(
                Constant(0), Constant(0), Constant(0),
                secondary_loss=Constant(10_000), secondary_probability=0.3),
        )
        self.assertAlmostEqual(scenario_ale(s), 3_000)

    def test_no_controls_means_no_reduction(self):
        s = [scenario("S1", 1.0, 10)]
        self.assertAlmostEqual(residual_ale(s, []), baseline_ale(s))

    def test_frequency_reduction_scales_loss(self):
        s = [scenario("S1", 1.0, 10)]
        c = control("A", 100, {"S1": (0.5, 0.0)})
        self.assertAlmostEqual(residual_ale(s, [c]), baseline_ale(s) * 0.5)

    def test_magnitude_reduction_scales_loss(self):
        s = [scenario("S1", 1.0, 10)]
        c = control("A", 100, {"S1": (0.0, 0.25)})
        self.assertAlmostEqual(residual_ale(s, [c]), baseline_ale(s) * 0.75)

    def test_frequency_and_magnitude_compose(self):
        s = [scenario("S1", 1.0, 10)]
        c = control("A", 100, {"S1": (0.5, 0.5)})
        self.assertAlmostEqual(residual_ale(s, [c]), baseline_ale(s) * 0.25)

    def test_overlapping_controls_compose_multiplicatively(self):
        """Two controls each cutting frequency by half leave a quarter, not
        zero. Adding percentages would let the optimiser 'eliminate' a risk by
        stacking mediocre controls, and would systematically over-buy."""
        s = [scenario("S1", 1.0, 10)]
        a = control("A", 100, {"S1": (0.5, 0.0)})
        b = control("B", 100, {"S1": (0.5, 0.0)})
        self.assertAlmostEqual(residual_ale(s, [a, b]), baseline_ale(s) * 0.25)

    def test_diminishing_returns(self):
        """The second copy of an equally effective control must buy strictly
        less than the first -- that submodularity is what makes greedy sound."""
        s = [scenario("S1", 1.0, 10)]
        a = control("A", 100, {"S1": (0.5, 0.0)})
        b = control("B", 100, {"S1": (0.5, 0.0)})
        first = baseline_ale(s) - residual_ale(s, [a])
        second = residual_ale(s, [a]) - residual_ale(s, [a, b])
        self.assertGreater(first, second)

    def test_control_affecting_another_scenario_does_nothing_here(self):
        s = [scenario("S1", 1.0, 10)]
        c = control("A", 100, {"S2": (1.0, 1.0)})
        self.assertAlmostEqual(residual_ale(s, [c]), baseline_ale(s))


class TestOptimiser(unittest.TestCase):
    def setUp(self):
        self.scenarios = [
            scenario("S1", 1.0, 10, 1000),   # ALE 10,000
            scenario("S2", 0.5, 40, 1000),   # ALE 20,000
            scenario("S3", 2.0, 2, 1000),    # ALE  4,000
        ]
        self.catalogue = [
            control("A", 1_000, {"S1": (0.5, 0.0)}),
            control("B", 2_000, {"S2": (0.5, 0.0)}),
            control("C", 500, {"S3": (0.5, 0.0)}),
            control("D", 5_000, {"S1": (0.3, 0.3), "S2": (0.3, 0.3)}),
            control("E", 300, {"S3": (0.0, 0.9)}),
        ]

    def test_respects_the_budget(self):
        for budget in (0, 500, 1_000, 3_000, 10_000):
            p = optimise(self.scenarios, self.catalogue, budget)
            self.assertLessEqual(p.cost, budget, f"overspent at budget {budget}")

    def test_zero_budget_buys_nothing(self):
        p = optimise(self.scenarios, self.catalogue, 0)
        self.assertEqual(p.controls, ())
        self.assertAlmostEqual(p.residual_ale, p.baseline_ale)
        self.assertAlmostEqual(p.rosi, 0.0)

    def test_more_budget_never_does_worse(self):
        """Monotonicity: a larger budget must not produce a worse portfolio."""
        losses = [
            optimise(self.scenarios, self.catalogue, b).residual_ale
            for b in (0, 1_000, 2_000, 5_000, 10_000, 20_000)
        ]
        for earlier, later in zip(losses, losses[1:]):
            self.assertLessEqual(later, earlier + 1e-9)

    def test_matches_brute_force(self):
        """The claim that greedy is good enough, checked against a computed
        optimum rather than against the theoretical guarantee."""
        for budget in (500, 1_000, 2_000, 3_000, 5_000, 8_000):
            greedy = optimise(self.scenarios, self.catalogue, budget)
            best = exhaustive_optimise(self.scenarios, self.catalogue, budget)
            self.assertAlmostEqual(
                greedy.residual_ale, best.residual_ale, places=6,
                msg=f"greedy suboptimal at budget {budget}: "
                    f"{[c.id for c in greedy.controls]} vs {[c.id for c in best.controls]}",
            )

    def test_prefers_value_per_euro_not_raw_effect(self):
        """E costs 300 and removes 90% of a 4,000 risk; A costs 1,000 and
        removes 50% of a 10,000 risk. With only 300 to spend, E is the answer."""
        p = optimise(self.scenarios, self.catalogue, 300)
        self.assertEqual([c.id for c in p.controls], ["E"])

    def test_reduction_and_rosi_are_consistent(self):
        p = optimise(self.scenarios, self.catalogue, 5_000)
        self.assertAlmostEqual(p.reduction, p.baseline_ale - p.residual_ale)
        self.assertAlmostEqual(p.rosi, (p.reduction - p.cost) / p.cost)

    def test_per_scenario_breakdown_is_reported(self):
        p = optimise(self.scenarios, self.catalogue, 5_000)
        self.assertEqual(set(p.per_scenario), {"S1", "S2", "S3"})
        for base, residual in p.per_scenario.values():
            self.assertLessEqual(residual, base + 1e-9)

    def test_rejects_negative_budget(self):
        with self.assertRaises(ValueError):
            optimise(self.scenarios, self.catalogue, -1)

    def test_explain_is_readable(self):
        text = optimise(self.scenarios, self.catalogue, 5_000).explain()
        for fragment in ("Budget", "Expected annual loss", "ROSI", "Selected:"):
            self.assertIn(fragment, text)

    def test_exhaustive_refuses_infeasible_sizes(self):
        big = [control(f"X{i}", 100, {"S1": (0.1, 0)}) for i in range(25)]
        with self.assertRaises(ValueError):
            exhaustive_optimise(self.scenarios, big, 1_000)


class TestFrontier(unittest.TestCase):
    def test_frontier_is_monotone_in_budget(self):
        scenarios = [scenario("S1", 1.0, 10), scenario("S2", 0.5, 40)]
        catalogue = [
            control("A", 1_000, {"S1": (0.5, 0.0)}),
            control("B", 3_000, {"S2": (0.6, 0.0)}),
            control("C", 8_000, {"S1": (0.4, 0.4), "S2": (0.4, 0.4)}),
        ]
        frontier = efficient_frontier(scenarios, catalogue, [0, 1_000, 5_000, 20_000])
        losses = [p.residual_ale for p in frontier]
        self.assertEqual(losses, sorted(losses, reverse=True))

    def test_frontier_shows_diminishing_returns(self):
        """Real catalogue: the marginal euro must buy less as budget grows.
        That curve is the answer to 'how much is enough', which is the question
        a port director actually has."""
        from portscra.risk.economics import RONNE_2024, OutageCostPerHour
        from portscra.taxonomy.scenarios import build_scenarios

        scenarios = build_scenarios(OutageCostPerHour(RONNE_2024))
        frontier = efficient_frontier(scenarios, CATALOGUE, [10_000, 30_000, 60_000])
        gains = [p.reduction for p in frontier]
        costs = [p.cost for p in frontier]
        first = gains[0] / costs[0]
        last = (gains[-1] - gains[-2]) / max(costs[-1] - costs[-2], 1)
        self.assertGreater(first, last)


class TestTornado(unittest.TestCase):
    def setUp(self):
        self.scenarios = [scenario("S1", 1.0, 10), scenario("S2", 0.5, 40)]
        self.catalogue = [
            control("A", 1_000, {"S1": (0.5, 0.0)}),
            control("B", 2_000, {"S2": (0.6, 0.0)}),
        ]

    def test_returns_a_band_per_selected_control(self):
        p = optimise(self.scenarios, self.catalogue, 10_000)
        bars = tornado(self.scenarios, p)
        self.assertEqual(len(bars), len(p.controls))
        for _, low, high in bars:
            self.assertLessEqual(low, high)

    def test_sorted_by_widest_swing(self):
        p = optimise(self.scenarios, self.catalogue, 10_000)
        bars = tornado(self.scenarios, p)
        widths = [high - low for _, low, high in bars]
        self.assertEqual(widths, sorted(widths, reverse=True))

    def test_control_on_the_larger_risk_dominates_sensitivity(self):
        """B protects a 20,000 risk, A a 10,000 one, so uncertainty in B's
        effectiveness matters more -- that is what a tornado chart should say."""
        p = optimise(self.scenarios, self.catalogue, 10_000)
        self.assertEqual(tornado(self.scenarios, p)[0][0], "B")

    def test_rejects_bad_perturbation(self):
        p = optimise(self.scenarios, self.catalogue, 10_000)
        with self.assertRaises(ValueError):
            tornado(self.scenarios, p, perturbation=0)


if __name__ == "__main__":
    unittest.main()
