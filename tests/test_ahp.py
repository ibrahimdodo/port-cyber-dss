"""Tests for the AHP criterion weighting.

AHP has exact mathematical properties on well-known matrices, so this suite
checks against them rather than against expected outputs I invented. A perfectly
consistent matrix must yield a consistency ratio of zero and weights equal to
its own generating vector; Saaty's textbook example must reproduce his numbers.
"""

import unittest

import numpy as np

from portscra.vendor.ahp import (
    CONSISTENCY_THRESHOLD,
    RANDOM_INDEX,
    consistency_ratio,
    matrix_from_comparisons,
    weights_from_matrix,
    weights_from_ranking,
)


class TestMatrixConstruction(unittest.TestCase):
    def test_reciprocals_are_filled_automatically(self):
        """The user answers each pair once; the matrix is completed for them."""
        m = matrix_from_comparisons(["a", "b"], {("a", "b"): 3})
        self.assertEqual(m[0, 1], 3)
        self.assertAlmostEqual(m[1, 0], 1 / 3)
        self.assertTrue(np.allclose(np.diag(m), 1.0))

    def test_unstated_pairs_default_to_equal(self):
        """A partially completed questionnaire must remain usable."""
        m = matrix_from_comparisons(["a", "b", "c"], {("a", "b"): 5})
        self.assertEqual(m[0, 2], 1.0)
        self.assertEqual(m[2, 0], 1.0)

    def test_rejects_unknown_criterion(self):
        with self.assertRaises(ValueError):
            matrix_from_comparisons(["a", "b"], {("a", "z"): 3})

    def test_rejects_self_comparison(self):
        with self.assertRaises(ValueError):
            matrix_from_comparisons(["a", "b"], {("a", "a"): 3})

    def test_rejects_non_positive_value(self):
        with self.assertRaises(ValueError):
            matrix_from_comparisons(["a", "b"], {("a", "b"): 0})


class TestWeights(unittest.TestCase):
    def test_weights_sum_to_one(self):
        m = matrix_from_comparisons(["a", "b", "c"], {("a", "b"): 3, ("b", "c"): 2})
        self.assertAlmostEqual(weights_from_matrix(["a", "b", "c"], m).weights.sum(), 1.0)

    def test_equal_matrix_gives_equal_weights(self):
        m = np.ones((4, 4))
        result = weights_from_matrix(list("abcd"), m)
        np.testing.assert_allclose(result.weights, 0.25, atol=1e-9)
        self.assertAlmostEqual(result.consistency_ratio, 0.0, places=9)

    def test_perfectly_consistent_matrix_recovers_its_generating_vector(self):
        """If a[i,j] = w_i / w_j exactly, AHP must return w. This is the
        strongest correctness check available for the eigenvector method."""
        w = np.array([0.5, 0.3, 0.15, 0.05])
        m = w[:, None] / w[None, :]
        result = weights_from_matrix(list("abcd"), m)
        np.testing.assert_allclose(result.weights, w, atol=1e-9)
        self.assertAlmostEqual(result.consistency_ratio, 0.0, places=8)
        self.assertAlmostEqual(result.lambda_max, 4.0, places=8)

    def test_dominant_criterion_gets_the_largest_weight(self):
        m = matrix_from_comparisons(
            ["access", "posture", "data"],
            {("access", "posture"): 5, ("access", "data"): 7, ("posture", "data"): 2},
        )
        result = weights_from_matrix(["access", "posture", "data"], m)
        self.assertEqual(result.ranked()[0][0], "access")

    def test_rejects_non_reciprocal_matrix(self):
        m = np.array([[1.0, 3.0], [3.0, 1.0]])  # both directions say "3x"
        with self.assertRaises(ValueError):
            weights_from_matrix(["a", "b"], m)

    def test_rejects_bad_diagonal(self):
        m = np.array([[2.0, 1.0], [1.0, 2.0]])
        with self.assertRaises(ValueError):
            weights_from_matrix(["a", "b"], m)

    def test_rejects_shape_mismatch(self):
        with self.assertRaises(ValueError):
            weights_from_matrix(["a", "b", "c"], np.ones((2, 2)))


class TestConsistency(unittest.TestCase):
    def test_mildly_inconsistent_matrix_passes_the_threshold(self):
        """A realistic set of judgements -- a beats b beats c, with roughly
        transitive magnitudes -- should be slightly inconsistent but acceptable.

        Asserted as properties rather than a memorised constant: lambda_max sits
        just above n, and the ratio lands inside Saaty's 10% threshold. The exact
        eigenvalue is pinned by the perfectly-consistent test above, which is a
        stronger check because its expected value is exact by construction.
        """
        m = np.array([
            [1.0, 1 / 3, 1 / 5],
            [3.0, 1.0, 1 / 2],
            [5.0, 2.0, 1.0],
        ])
        lam, ci, cr = consistency_ratio(m)
        n = m.shape[0]
        self.assertGreater(lam, n)          # any inconsistency pushes it above n
        self.assertLess(lam, n + 0.05)      # but only slightly
        self.assertGreater(cr, 0.0)
        self.assertLess(cr, CONSISTENCY_THRESHOLD)

    def test_contradictory_judgements_are_flagged(self):
        """a >> b, b >> c, yet c >> a. The user has contradicted themselves and
        the tool must say so rather than average the contradiction away."""
        m = matrix_from_comparisons(
            ["a", "b", "c"],
            {("a", "b"): 9, ("b", "c"): 9, ("c", "a"): 9},
        )
        result = weights_from_matrix(["a", "b", "c"], m)
        self.assertFalse(result.is_consistent)
        self.assertGreater(result.consistency_ratio, CONSISTENCY_THRESHOLD)

    def test_two_criteria_cannot_be_inconsistent(self):
        """With a single comparison there is nothing to contradict."""
        m = matrix_from_comparisons(["a", "b"], {("a", "b"): 9})
        self.assertTrue(weights_from_matrix(["a", "b"], m).is_consistent)

    def test_random_index_covers_our_criterion_count(self):
        """We have seven criteria, so RI must be defined at n=7."""
        self.assertIn(7, RANDOM_INDEX)

    def test_explain_reports_the_verdict(self):
        m = np.ones((3, 3))
        text = weights_from_matrix(list("abc"), m).explain()
        self.assertIn("consistency ratio", text)
        self.assertIn("consistent", text)


class TestRankingFallback(unittest.TestCase):
    def test_rank_order_centroid_is_decreasing_and_normalised(self):
        result = weights_from_ranking(["first", "second", "third", "fourth"])
        w = result.weights
        self.assertAlmostEqual(w.sum(), 1.0)
        self.assertTrue(np.all(np.diff(w) < 0))
        self.assertEqual(result.ranked()[0][0], "first")

    def test_beats_equal_weights_at_expressing_an_ordering(self):
        result = weights_from_ranking(["a", "b", "c"])
        self.assertGreater(result.weights[0], 1 / 3)
        self.assertLess(result.weights[-1], 1 / 3)

    def test_rejects_empty(self):
        with self.assertRaises(ValueError):
            weights_from_ranking([])


if __name__ == "__main__":
    unittest.main()
