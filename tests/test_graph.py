"""Tests for the vendor -> asset -> service dependency graph.

This module is the join that makes the system port-specific, so the tests focus
on the join actually happening: that vendor probabilities reach scenario
frequencies, that the arithmetic of combining several vendors is right, and
that a missing vendor degrades safely rather than silently zeroing a risk.
"""

import unittest

import numpy as np

from portscra.graph import (
    ASSET_SERVICES,
    SERVICES,
    DependencyGraph,
    SummedFrequency,
    build_scenarios_from_vendors,
    find_service,
)
from portscra.risk.distributions import Constant, PERT
from portscra.risk.economics import RONNE_2024, OutageCostPerHour
from portscra.taxonomy.assets import find_asset
from portscra.taxonomy.scenarios import SCENARIO_TEMPLATES, build_scenarios
from portscra.vendor.likelihood import LikelihoodModel, Vendor
from portscra.vendor.questionnaire import QUESTIONS

BEST = {q.id: len(q.options) - 1 for q in QUESTIONS}
WORST = {q.id: 0 for q in QUESTIONS}


class TestServices(unittest.TestCase):
    def test_service_keys_are_unique(self):
        keys = [s.key for s in SERVICES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_revenue_shares_sum_to_one(self):
        """Shares apportion the port's call-dependent revenue, so they must
        partition it -- otherwise impact is silently over- or under-counted."""
        self.assertAlmostEqual(sum(s.revenue_share for s in SERVICES), 1.0, places=6)

    def test_asset_map_references_only_real_assets(self):
        for asset in ASSET_SERVICES:
            self.assertIsNotNone(find_asset(asset), f"unknown asset {asset!r}")

    def test_asset_map_references_only_real_services(self):
        """A typo here would silently drop a service from every impact
        calculation that used it."""
        known = {s.key for s in SERVICES}
        for asset, services in ASSET_SERVICES.items():
            for service in services:
                self.assertIn(service, known, f"{asset} -> unknown service {service!r}")

    def test_lookup(self):
        self.assertIsNotNone(find_service("cargo_handling"))
        self.assertIsNone(find_service("nope"))


class TestSummedFrequency(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(3)

    def test_empty_contributes_nothing(self):
        f = SummedFrequency(())
        self.assertEqual(f.mean, 0.0)
        self.assertTrue(np.all(f.sample(self.rng, 100) == 0))

    def test_mean_is_the_weighted_sum(self):
        f = SummedFrequency((("a", Constant(0.1), 1.0), ("b", Constant(0.2), 0.5)))
        self.assertAlmostEqual(f.mean, 0.1 + 0.1)

    def test_sampling_matches_the_analytic_mean(self):
        f = SummedFrequency((("a", PERT(0.02, 0.05, 0.12), 1.0),
                             ("b", PERT(0.01, 0.03, 0.08), 0.5)))
        draws = f.sample(self.rng, 200_000)
        self.assertAlmostEqual(draws.mean(), f.mean, delta=0.002)

    def test_frequencies_add_rather_than_compose_as_probabilities(self):
        """Loss event frequency is a rate, so two vendors each contributing 0.1
        events a year give 0.2 -- not the 0.19 that treating them as
        independent probabilities would produce."""
        f = SummedFrequency((("a", Constant(0.1), 1.0), ("b", Constant(0.1), 1.0)))
        self.assertAlmostEqual(f.mean, 0.2)

    def test_scaling_is_proportional(self):
        f = SummedFrequency((("a", PERT(0.02, 0.05, 0.12), 1.0),))
        self.assertAlmostEqual(f.scale(0.5).mean, f.mean * 0.5)

    def test_rejects_negative_scale(self):
        with self.assertRaises(ValueError):
            SummedFrequency(()).scale(-1)

    def test_drivers_rank_contributors(self):
        f = SummedFrequency((("small", Constant(0.01), 1.0),
                             ("big", Constant(0.20), 1.0)))
        self.assertEqual(f.drivers[0][0], "big")


class TestDependencyGraph(unittest.TestCase):
    def setUp(self):
        self.msp = Vendor("msp", "MSP", "MSP",
                          supplies=("workstations", "servers", "networks"))
        self.tos = Vendor("tos", "TOS vendor", "software", supplies=("tos",))
        self.gate = Vendor("gate", "Gate integrator", "OT",
                           supplies=("access_control", "detection"))
        self.graph = DependencyGraph([self.msp, self.tos, self.gate])

    def test_vendors_for_asset(self):
        self.assertEqual(self.graph.vendors_for_asset("tos"), [self.tos])
        self.assertEqual(self.graph.vendors_for_asset("nothing"), [])

    def test_services_for_vendor_aggregates_across_assets(self):
        services = self.graph.services_for_vendor(self.msp)
        self.assertIn("cargo_handling", services)
        self.assertIn("billing", services)

    def test_revenue_at_risk_is_a_share(self):
        for vendor in self.graph.vendors:
            share = self.graph.revenue_at_risk(vendor)
            self.assertGreaterEqual(share, 0.0)
            self.assertLessEqual(share, 1.0)

    def test_broad_vendor_exposes_more_revenue_than_narrow_one(self):
        """The concentration question: an MSP touching everything is a bigger
        topological risk than a specialist, independent of security posture."""
        self.assertGreater(
            self.graph.revenue_at_risk(self.msp),
            self.graph.revenue_at_risk(self.gate),
        )

    def test_single_points_of_failure_are_ranked(self):
        spofs = self.graph.single_points_of_failure(threshold=0.0)
        shares = [s for _, s in spofs]
        self.assertEqual(shares, sorted(shares, reverse=True))

    def test_scenario_matching_uses_target_assets(self):
        s1 = next(t for t in SCENARIO_TEMPLATES if t.id == "S1")  # targets tos, pcs
        matched = dict(
            (v.key, coverage) for v, coverage in self.graph.vendors_for_scenario(s1)
        )
        self.assertIn("tos", matched)
        # Supplies one of the two target assets.
        self.assertAlmostEqual(matched["tos"], 0.5)

    def test_unmatched_scenario_returns_nothing(self):
        s5 = next(t for t in SCENARIO_TEMPLATES if t.id == "S5")  # navigation assets
        self.assertEqual(self.graph.vendors_for_scenario(s5), [])

    def test_validate_flags_unknown_asset(self):
        bad = DependencyGraph([Vendor("x", "X", "y", supplies=("not_an_asset",))])
        self.assertTrue(any("unknown asset" in p for p in bad.validate()))

    def test_validate_flags_unsupplied_scenario_targets(self):
        """An asset a scenario targets but no vendor supplies usually means the
        vendor register is incomplete, which is worth surfacing."""
        problems = self.graph.validate()
        self.assertTrue(any("no vendor supplies" in p for p in problems))

    def test_unsupplied_assets_listed(self):
        self.assertIn("navigation_data", self.graph.unsupplied_assets())


class TestScenarioDerivation(unittest.TestCase):
    def setUp(self):
        self.cost = OutageCostPerHour(RONNE_2024)
        self.model = LikelihoodModel()
        self.generic = build_scenarios(self.cost)
        self.by_id = {s.id: s for s in self.generic}

    def _derive(self, vendors):
        graph = DependencyGraph(vendors)
        assessments = {v.key: self.model.assess(v) for v in vendors}
        return {
            s.id: s for s in
            build_scenarios_from_vendors(graph, assessments, self.cost,
                                         fallback_scenarios=self.generic)
        }

    def test_every_scenario_survives_derivation(self):
        derived = self._derive([Vendor("tos", "T", "sw", supplies=("tos",),
                                       answers=BEST)])
        self.assertEqual(set(derived), set(self.by_id))

    def test_scenario_with_no_vendor_keeps_its_generic_frequency(self):
        """Absence of a listed supplier almost always means an incomplete
        register, not an impossible risk. Zeroing it would reward not writing
        the vendor down."""
        derived = self._derive([Vendor("tos", "T", "sw", supplies=("tos",),
                                       answers=BEST)])
        self.assertAlmostEqual(
            derived["S5"].loss_event_frequency.mean,
            self.by_id["S5"].loss_event_frequency.mean,
        )

    def test_matched_scenario_frequency_comes_from_the_vendor(self):
        derived = self._derive([Vendor("tos", "T", "sw", supplies=("tos",),
                                       answers=WORST)])
        self.assertIsInstance(derived["S1"].loss_event_frequency, SummedFrequency)
        self.assertIn("Derived from", derived["S1"].loss_event_frequency.source)

    def test_a_worse_vendor_raises_its_scenario_frequency(self):
        """The feedback loop the whole system exists for: improve the supplier,
        and the risk figures move."""
        good = self._derive([Vendor("tos", "T", "sw", supplies=("tos",), answers=BEST)])
        bad = self._derive([Vendor("tos", "T", "sw", supplies=("tos",), answers=WORST)])
        self.assertGreater(
            bad["S1"].loss_event_frequency.mean,
            good["S1"].loss_event_frequency.mean,
        )

    def test_more_vendors_on_one_scenario_raise_its_frequency(self):
        one = self._derive([Vendor("a", "A", "sw", supplies=("tos",), answers=WORST)])
        two = self._derive([
            Vendor("a", "A", "sw", supplies=("tos",), answers=WORST),
            Vendor("b", "B", "sw", supplies=("pcs",), answers=WORST),
        ])
        self.assertGreater(
            two["S1"].loss_event_frequency.mean,
            one["S1"].loss_event_frequency.mean,
        )

    def test_coverage_weights_the_contribution(self):
        """A vendor supplying both of S1's target assets contributes twice what
        one supplying a single asset does."""
        half = self._derive([Vendor("a", "A", "sw", supplies=("tos",), answers=WORST)])
        full = self._derive([Vendor("a", "A", "sw", supplies=("tos", "pcs"),
                                    answers=WORST)])
        self.assertAlmostEqual(
            full["S1"].loss_event_frequency.mean / half["S1"].loss_event_frequency.mean,
            2.0, places=6,
        )

    def test_loss_magnitude_is_untouched(self):
        """Magnitudes depend on port operations and economics, not on which
        supplier was breached."""
        derived = self._derive([Vendor("tos", "T", "sw", supplies=("tos",),
                                       answers=WORST)])
        self.assertIs(derived["S1"].loss_magnitude, self.by_id["S1"].loss_magnitude)

    def test_metadata_is_preserved(self):
        derived = self._derive([Vendor("tos", "T", "sw", supplies=("tos",),
                                       answers=BEST)])
        self.assertEqual(derived["S1"].attack_techniques,
                         self.by_id["S1"].attack_techniques)

    def test_derived_scenarios_simulate(self):
        from portscra.risk.montecarlo import simulate
        derived = self._derive([
            Vendor("tos", "T", "sw", supplies=("tos",), answers=WORST),
            Vendor("msp", "M", "MSP", supplies=("workstations", "servers"),
                   answers=WORST),
        ])
        results = simulate(list(derived.values()), iterations=5_000, seed=1)
        self.assertGreater(results["__portfolio__"].ale, 0)

    def test_derived_scenarios_work_with_the_optimiser(self):
        """End to end: vendor evidence -> frequencies -> portfolio selection."""
        from portscra.controls import CATALOGUE, optimise
        derived = self._derive([
            Vendor("gate", "G", "OT", supplies=("access_control", "detection"),
                   answers=WORST),
        ])
        portfolio = optimise(list(derived.values()), CATALOGUE, 20_000)
        self.assertLessEqual(portfolio.cost, 20_000)
        self.assertLess(portfolio.residual_ale, portfolio.baseline_ale)


if __name__ == "__main__":
    unittest.main()
