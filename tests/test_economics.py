"""Tests for the port economics derivation.

The important property here is not that the numbers are correct in an absolute
sense -- they rest on estimates that are documented as estimates -- but that the
arithmetic is right and that the two independent derivations agree. A silent
unit error in this module would propagate into every euro figure the DSS
produces, which is exactly the class of mistake that is hard to spot by eye.
"""

import unittest

import numpy as np

from portscra.risk.distributions import PERT, Constant
from portscra.risk.economics import (
    DKK_PER_EUR,
    RONNE_2024,
    OutageCostPerHour,
    PortEconomics,
)


class TestPortEconomics(unittest.TestCase):
    def test_currency_conversion(self):
        self.assertAlmostEqual(
            RONNE_2024.revenue_eur, 169_814_309 / DKK_PER_EUR, places=2
        )
        # Sanity: revenue is around EUR 23M, not 2.3M or 230M.
        self.assertTrue(20e6 < RONNE_2024.revenue_eur < 25e6)

    def test_revenue_per_call(self):
        expected = RONNE_2024.revenue_eur / RONNE_2024.annual_calls
        self.assertAlmostEqual(RONNE_2024.revenue_per_call_eur, expected, places=6)
        self.assertTrue(5_000 < RONNE_2024.revenue_per_call_eur < 10_000)

    def test_ebitda_margin(self):
        self.assertAlmostEqual(RONNE_2024.ebitda_margin, 101_670_000 / 169_814_309,
                               places=6)

    def test_figures_carry_provenance(self):
        """A financial input without a citation cannot be defended in a report."""
        self.assertIn("Årsrapport", RONNE_2024.source)
        self.assertIn("SKIB101", RONNE_2024.source)


class TestOutageCostPerHour(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7)

    def test_mean_matches_the_closed_form(self):
        cost = OutageCostPerHour(RONNE_2024)
        draws = cost.sample(self.rng, 200_000)
        self.assertAlmostEqual(draws.mean() / cost.mean, 1.0, delta=0.01)

    def test_both_reductions_are_applied(self):
        """Cost must be strictly below naive revenue-over-hours: rental income
        continues during an outage, and deferred traffic is recovered."""
        cost = OutageCostPerHour(RONNE_2024)
        naive = RONNE_2024.revenue_eur / (24 * 365)
        self.assertLess(cost.mean, naive)

    def test_shares_of_one_reproduce_the_naive_figure(self):
        cost = OutageCostPerHour(
            RONNE_2024,
            call_dependent_share=Constant(1.0),
            unrecoverable_share=Constant(1.0),
        )
        self.assertAlmostEqual(cost.mean, RONNE_2024.revenue_eur / (24 * 365), places=6)

    def test_shorter_service_year_raises_the_hourly_rate(self):
        """The same lost revenue spread over fewer operating hours costs more
        per hour -- the disturbance denominator has to behave this way."""
        full = OutageCostPerHour(RONNE_2024, service_hours_per_year=24 * 365)
        short = OutageCostPerHour(RONNE_2024, service_hours_per_year=16 * 365)
        self.assertGreater(short.mean, full.mean)
        self.assertAlmostEqual(short.mean / full.mean, 24 / 16, places=6)

    def test_uncertainty_propagates(self):
        """Share parameters are uncertain, so the output must be a spread, not
        a point -- that is the entire reason these are distributions."""
        draws = OutageCostPerHour(RONNE_2024).sample(self.rng, 50_000)
        self.assertGreater(draws.std(), 0)
        self.assertLess(draws.min(), draws.max())

    def test_samples_are_all_positive(self):
        draws = OutageCostPerHour(RONNE_2024).sample(self.rng, 50_000)
        self.assertGreater(draws.min(), 0)

    def test_rejects_non_positive_service_hours(self):
        with self.assertRaises(ValueError):
            OutageCostPerHour(RONNE_2024, service_hours_per_year=0)

    def test_result_is_a_plausible_hourly_figure(self):
        """Guard against unit slips: a small port losing millions per hour, or
        pennies, means something upstream is wrong by orders of magnitude."""
        cost = OutageCostPerHour(RONNE_2024)
        self.assertTrue(100 < cost.mean < 5_000, f"implausible: {cost.mean}")


class TestCrossCheck(unittest.TestCase):
    def test_two_derivations_agree_once_call_bases_match(self):
        """Deriving the hourly cost from annual revenue and from revenue-per-call
        must give the same answer when both use the same number of calls."""
        cost = OutageCostPerHour(RONNE_2024)
        calls_per_day = RONNE_2024.annual_calls / 365.0
        check = cost.cross_check_per_call(calls_per_day)
        self.assertAlmostEqual(check["ratio"], 1.0, delta=0.01)

    def test_fewer_calls_scales_the_cross_check_proportionally(self):
        cost = OutageCostPerHour(RONNE_2024)
        full = cost.cross_check_per_call(RONNE_2024.annual_calls / 365.0)
        half = cost.cross_check_per_call(RONNE_2024.annual_calls / 365.0 / 2)
        self.assertAlmostEqual(half["adjusted_hourly_eur"] * 2,
                               full["adjusted_hourly_eur"], places=6)

    def test_cross_check_respects_service_hours(self):
        cost = OutageCostPerHour(RONNE_2024, service_hours_per_year=16 * 365)
        check = cost.cross_check_per_call(RONNE_2024.annual_calls / 365.0)
        self.assertAlmostEqual(check["ratio"], 1.0, delta=0.01)


if __name__ == "__main__":
    unittest.main()


class TestScaledPersonas(unittest.TestCase):
    """The brief's 10/50/100 personas need the economics scaled, not only the
    response costs. Holding revenue fixed while scaling costs produced a persona
    sweep in which all three personas chose identically -- an artifact, not a
    finding."""

    def test_scaling_is_proportional_to_headcount(self):
        half = RONNE_2024.scaled_to(17)  # half of 34 FTE
        self.assertAlmostEqual(half.revenue_dkk, RONNE_2024.revenue_dkk / 2, places=2)
        self.assertAlmostEqual(half.ebitda_dkk, RONNE_2024.ebitda_dkk / 2, places=2)
        self.assertEqual(half.employees_fte, 17)

    def test_scaling_to_own_size_is_a_no_op(self):
        same = RONNE_2024.scaled_to(RONNE_2024.employees_fte)
        self.assertAlmostEqual(same.revenue_eur, RONNE_2024.revenue_eur, places=6)
        self.assertEqual(same.annual_calls, RONNE_2024.annual_calls)

    def test_smaller_port_has_a_lower_hourly_outage_cost(self):
        """The whole point: a ten-person port does not merely spend less on
        incident response, it earns less per hour of downtime too."""
        small = OutageCostPerHour(RONNE_2024.scaled_to(10))
        large = OutageCostPerHour(RONNE_2024.scaled_to(100))
        self.assertLess(small.mean, large.mean)
        self.assertAlmostEqual(large.mean / small.mean, 10.0, places=4)

    def test_revenue_per_call_is_preserved_under_scaling(self):
        """Linear scaling of both revenue and calls should leave the per-call
        figure unchanged -- a check that the proxy is at least self-consistent."""
        scaled = RONNE_2024.scaled_to(68)  # double
        self.assertAlmostEqual(scaled.revenue_per_call_eur,
                               RONNE_2024.revenue_per_call_eur, delta=100)

    def test_calls_never_round_to_zero(self):
        tiny = RONNE_2024.scaled_to(1)
        self.assertGreaterEqual(tiny.annual_calls, 1)

    def test_scaled_source_records_the_assumption(self):
        """Linear scaling by headcount is a crude proxy for a capital-intensive
        industry. It must say so where anyone reading the figures will see it."""
        scaled = RONNE_2024.scaled_to(10)
        self.assertIn("Proxy", scaled.source)
        self.assertIn("Linear scale", scaled.source)

    def test_rejects_non_positive_headcount(self):
        with self.assertRaises(ValueError):
            RONNE_2024.scaled_to(0)
        with self.assertRaises(ValueError):
            RONNE_2024.scaled_to(-5)
