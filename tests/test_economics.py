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
