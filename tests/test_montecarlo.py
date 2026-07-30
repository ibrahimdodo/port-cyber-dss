"""Tests for the FAIR Monte Carlo engine.

The properties worth testing here are statistical rather than exact: that the
long-run mean matches the analytic expectation, that the Poisson step produces
the discrete year-to-year behaviour it is supposed to, and that a zero-frequency
scenario is genuinely free.
"""

import unittest

import numpy as np

from portscra.risk.distributions import PERT, Constant
from portscra.risk.montecarlo import (
    LossMagnitude,
    Scenario,
    annual_disturbance_pct,
    simulate,
)


def make_scenario(sid="T1", lef=0.5, hours=10.0, rate=1000.0, response=0.0,
                  secondary=None, secondary_p=0.0):
    return Scenario(
        id=sid,
        name=f"test scenario {sid}",
        loss_event_frequency=Constant(lef),
        loss_magnitude=LossMagnitude(
            downtime_hours=Constant(hours),
            cost_per_hour=Constant(rate),
            response_cost=Constant(response),
            secondary_loss=Constant(secondary) if secondary is not None else None,
            secondary_probability=secondary_p,
        ),
    )


class TestSimulate(unittest.TestCase):
    def test_output_shapes(self):
        results = simulate(make_scenario(), iterations=5_000)
        self.assertIn("T1", results)
        self.assertIn("__portfolio__", results)
        self.assertEqual(results["T1"].annual_loss.shape, (5_000,))
        self.assertEqual(results["T1"].event_counts.shape, (5_000,))

    def test_mean_matches_analytic_expectation(self):
        """With fixed frequency and magnitude, mean annual loss must converge to
        frequency x magnitude. This is the sanity anchor for the whole engine."""
        scenario = make_scenario(lef=0.5, hours=10.0, rate=1000.0)
        results = simulate(scenario, iterations=200_000, seed=1)
        expected = 0.5 * 10.0 * 1000.0
        self.assertAlmostEqual(results["T1"].ale / expected, 1.0, delta=0.02)

    def test_response_and_secondary_costs_are_included(self):
        scenario = make_scenario(
            lef=1.0, hours=0.0, rate=0.0, response=5_000,
            secondary=10_000, secondary_p=0.5,
        )
        results = simulate(scenario, iterations=100_000, seed=2)
        # 1 event/yr x (5,000 response + 0.5 x 10,000 expected secondary)
        self.assertAlmostEqual(results["T1"].ale / 10_000.0, 1.0, delta=0.03)

    def test_zero_frequency_yields_zero_loss(self):
        results = simulate(make_scenario(lef=0.0), iterations=1_000)
        self.assertEqual(results["T1"].annual_loss.sum(), 0.0)
        self.assertEqual(results["T1"].probability_of_any_loss, 0.0)

    def test_poisson_produces_incident_free_years(self):
        """A low-frequency risk must produce mostly quiet years. This is the
        behaviour lost when frequency is naively multiplied by magnitude, and
        it is what makes the P90 tail meaningful."""
        results = simulate(make_scenario(lef=0.1), iterations=100_000, seed=3)
        quiet = 1.0 - results["T1"].probability_of_any_loss
        # P(no event) = exp(-0.1) ~ 0.905
        self.assertAlmostEqual(quiet, np.exp(-0.1), delta=0.01)

    def test_multiple_events_in_one_year_accumulate(self):
        """A bad year with two incidents must cost roughly twice one incident."""
        scenario = make_scenario(lef=3.0, hours=1.0, rate=100.0)
        results = simulate(scenario, iterations=50_000, seed=4)
        two_event_years = results["T1"].annual_loss[results["T1"].event_counts == 2]
        self.assertGreater(two_event_years.size, 0)
        np.testing.assert_allclose(two_event_years, 200.0)

    def test_portfolio_is_the_sum_of_scenarios(self):
        scenarios = [make_scenario("A", lef=0.5), make_scenario("B", lef=0.3)]
        results = simulate(scenarios, iterations=10_000, seed=5)
        expected = results["A"].annual_loss + results["B"].annual_loss
        np.testing.assert_allclose(results["__portfolio__"].annual_loss, expected)

    def test_percentiles_are_ordered(self):
        results = simulate(make_scenario(lef=1.0), iterations=20_000)
        r = results["T1"]
        self.assertLessEqual(r.p10, r.p50)
        self.assertLessEqual(r.p50, r.p90)

    def test_uncertain_frequency_widens_the_distribution(self):
        """Uncertainty about the rate itself must widen outcomes relative to a
        known rate with the same mean -- that nesting is the point of drawing
        the rate per simulated year."""
        known = Scenario(
            id="known", name="known rate",
            loss_event_frequency=Constant(0.5),
            loss_magnitude=LossMagnitude(Constant(10), Constant(1000), Constant(0)),
        )
        uncertain = Scenario(
            id="uncertain", name="uncertain rate",
            loss_event_frequency=PERT(0.1, 0.5, 0.9),
            loss_magnitude=LossMagnitude(Constant(10), Constant(1000), Constant(0)),
        )
        a = simulate(known, iterations=100_000, seed=6)["known"]
        b = simulate(uncertain, iterations=100_000, seed=6)["uncertain"]
        self.assertAlmostEqual(a.ale / b.ale, 1.0, delta=0.05)
        self.assertGreater(b.annual_loss.std(), a.annual_loss.std())

    def test_exceedance_curve_is_monotonic(self):
        results = simulate(make_scenario(lef=1.0), iterations=10_000)
        losses, probs = results["T1"].exceedance_curve(points=100)
        self.assertTrue(np.all(np.diff(losses) >= 0))
        self.assertTrue(np.all(np.diff(probs) <= 0))

    def test_downtime_is_tracked_separately_from_cost(self):
        """The assignment asks for hours and percent, not only euro."""
        results = simulate(make_scenario(lef=2.0, hours=12.0), iterations=50_000, seed=7)
        self.assertAlmostEqual(
            results["T1"].annual_downtime_hours.mean() / 24.0, 1.0, delta=0.03
        )

    def test_reproducibility(self):
        a = simulate(make_scenario(), iterations=5_000, seed=99)["T1"].annual_loss
        b = simulate(make_scenario(), iterations=5_000, seed=99)["T1"].annual_loss
        np.testing.assert_array_equal(a, b)

    def test_rejects_empty_and_invalid_input(self):
        with self.assertRaises(ValueError):
            simulate([], iterations=100)
        with self.assertRaises(ValueError):
            simulate(make_scenario(), iterations=0)

    def test_summary_keys(self):
        summary = simulate(make_scenario(), iterations=5_000)["T1"].summary()
        for key in ("ale", "p10", "p50", "p90", "prob_any_loss", "mean_downtime_hours"):
            self.assertIn(key, summary)


class TestDisturbancePercentage(unittest.TestCase):
    def test_percentage_against_service_hours(self):
        results = simulate(make_scenario(lef=1.0, hours=100.0), iterations=10_000, seed=8)
        pct = annual_disturbance_pct(results["T1"], annual_service_hours=1000.0)
        # 1 event/yr x 100h out of 1000 service hours ~ 10%
        self.assertAlmostEqual(float(pct.mean()), 10.0, delta=0.5)

    def test_rejects_non_positive_denominator(self):
        results = simulate(make_scenario(), iterations=100)
        with self.assertRaises(ValueError):
            annual_disturbance_pct(results["T1"], annual_service_hours=0)


if __name__ == "__main__":
    unittest.main()
