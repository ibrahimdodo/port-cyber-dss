"""Tests for the PERT three-point estimate distribution."""

import unittest

import numpy as np

from portscra.risk.distributions import PERT, Constant


class TestPERT(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(12345)

    def test_samples_stay_within_bounds(self):
        """The bounded support is the whole reason for choosing PERT over a
        lognormal: an outage estimate must not produce negative or absurd hours."""
        dist = PERT(4, 12, 30)
        draws = dist.sample(self.rng, 50_000)
        self.assertGreaterEqual(draws.min(), 4.0)
        self.assertLessEqual(draws.max(), 30.0)

    def test_analytic_mean_matches_sample_mean(self):
        dist = PERT(4, 12, 30)
        self.assertAlmostEqual(dist.mean, (4 + 4 * 12 + 30) / 6, places=10)
        draws = dist.sample(self.rng, 200_000)
        self.assertAlmostEqual(draws.mean(), dist.mean, delta=0.05)

    def test_mode_is_the_densest_region(self):
        """Sanity check that the distribution actually peaks near the mode."""
        dist = PERT(0, 10, 100)
        draws = dist.sample(self.rng, 100_000)
        counts, edges = np.histogram(draws, bins=50)
        peak = (edges[counts.argmax()] + edges[counts.argmax() + 1]) / 2
        self.assertLess(abs(peak - 10), 8.0)

    def test_lambda_controls_concentration(self):
        """Higher lambda means more confidence in the mode, so less spread."""
        loose = PERT(0, 50, 100, lam=1.0).sample(self.rng, 50_000)
        tight = PERT(0, 50, 100, lam=16.0).sample(self.rng, 50_000)
        self.assertLess(tight.std(), loose.std())

    def test_degenerate_range_collapses_to_constant(self):
        """min == max must work: contractually fixed costs are real inputs."""
        dist = PERT(500, 500, 500)
        draws = dist.sample(self.rng, 100)
        self.assertTrue(np.all(draws == 500))
        self.assertEqual(dist.mean, 500)

    def test_skewed_estimates(self):
        """A long right tail -- the usual shape of a cyber loss estimate --
        should put the mean above the mode."""
        dist = PERT(0, 10, 200)
        self.assertGreater(dist.mean, 10)

    def test_rejects_mode_outside_bounds(self):
        with self.assertRaises(ValueError):
            PERT(10, 5, 20)
        with self.assertRaises(ValueError):
            PERT(10, 25, 20)

    def test_rejects_non_positive_lambda(self):
        with self.assertRaises(ValueError):
            PERT(0, 1, 2, lam=0)

    def test_reproducible_with_same_seed(self):
        """Risk figures that move on every page reload are not trusted."""
        dist = PERT(1, 5, 20)
        a = dist.sample(np.random.default_rng(7), 1000)
        b = dist.sample(np.random.default_rng(7), 1000)
        np.testing.assert_array_equal(a, b)

    def test_source_is_carried(self):
        dist = PERT(1, 2, 3, source="ENISA 2019 Table 3")
        self.assertIn("ENISA", str(dist))


class TestConstant(unittest.TestCase):
    def test_always_returns_value(self):
        draws = Constant(42.0).sample(np.random.default_rng(1), 500)
        self.assertTrue(np.all(draws == 42.0))
        self.assertEqual(Constant(42.0).mean, 42.0)


if __name__ == "__main__":
    unittest.main()
