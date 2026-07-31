"""Analytic Hierarchy Process for weighting vendor-risk criteria.

The problem AHP solves here: a port manager can say confidently that "a vendor
holding remote admin access worries me more than one holding our passenger
data", but cannot say "access is 0.23 of my concern". Pairwise comparisons are
answerable; direct weights are not.

Saaty's method turns those comparisons into weights via the principal
eigenvector of the comparison matrix, and -- crucially for our purposes -- also
reports whether the answers were *coherent*. If someone says access beats data,
data beats patching, and patching beats access, the consistency ratio exposes
the contradiction instead of silently averaging it away.

The original brief offered teacher help with "criteria ranking". Since this is
now a solo build, that elicitation session becomes a feature instead: the app
runs the pairwise comparison with the user, checks their consistency, and uses
their weights rather than ones baked in by us. Literature-derived defaults are
provided in `questionnaire.py` for users who would rather not do the exercise.

Reference: Saaty, T.L. (1980) *The Analytic Hierarchy Process*.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["SAATY_SCALE", "RANDOM_INDEX", "AHPResult", "weights_from_matrix",
           "matrix_from_comparisons", "consistency_ratio"]

#: Saaty's fundamental scale. The verbal anchors matter more than the numbers:
#: users pick a phrase, the tool records the integer.
SAATY_SCALE = {
    1: "equally important",
    2: "equal to moderately more important",
    3: "moderately more important",
    4: "moderately to strongly more important",
    5: "strongly more important",
    6: "strongly to very strongly more important",
    7: "very strongly more important",
    8: "very strongly to extremely more important",
    9: "extremely more important",
}

#: Saaty's random consistency index: the average consistency ratio of randomly
#: generated reciprocal matrices of each size. Judgements are considered
#: acceptable when their inconsistency is under 10% of this random baseline.
RANDOM_INDEX = {
    1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
    6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
    11: 1.51, 12: 1.48, 13: 1.56, 14: 1.57, 15: 1.59,
}

#: Conventional threshold for acceptable inconsistency.
CONSISTENCY_THRESHOLD = 0.10


@dataclass(frozen=True)
class AHPResult:
    """Weights derived from a pairwise comparison matrix, plus a health check."""

    criteria: tuple[str, ...]
    weights: np.ndarray
    lambda_max: float
    consistency_index: float
    consistency_ratio: float

    @property
    def is_consistent(self) -> bool:
        """Whether the judgements hang together well enough to trust.

        An inconsistent result is not necessarily wrong, but it means the user
        contradicted themselves somewhere and should revisit rather than have
        the tool quietly proceed on incoherent weights.
        """
        return self.consistency_ratio <= CONSISTENCY_THRESHOLD

    def as_dict(self) -> dict[str, float]:
        return {c: float(w) for c, w in zip(self.criteria, self.weights)}

    def ranked(self) -> list[tuple[str, float]]:
        return sorted(self.as_dict().items(), key=lambda kv: kv[1], reverse=True)

    def explain(self) -> str:
        lines = [f"{name}: {weight:.3f}" for name, weight in self.ranked()]
        verdict = "consistent" if self.is_consistent else "INCONSISTENT - revisit judgements"
        lines.append(f"consistency ratio {self.consistency_ratio:.3f} ({verdict})")
        return "\n".join(lines)


def matrix_from_comparisons(
    criteria: list[str] | tuple[str, ...],
    comparisons: dict[tuple[str, str], float],
) -> np.ndarray:
    """Assemble a reciprocal comparison matrix from the answers given.

    `comparisons[(a, b)] = 5` reads "a is strongly more important than b". The
    reciprocal is filled automatically, so the user answers each pair once --
    n(n-1)/2 questions rather than n².

    Unstated pairs default to 1 (equal importance), which keeps a partially
    completed questionnaire usable instead of erroring out.
    """
    n = len(criteria)
    index = {name: i for i, name in enumerate(criteria)}
    matrix = np.ones((n, n), dtype=float)

    for (a, b), value in comparisons.items():
        if a not in index or b not in index:
            raise ValueError(f"comparison references unknown criterion: {(a, b)}")
        if value <= 0:
            raise ValueError(f"comparison value must be positive, got {value} for {(a, b)}")
        i, j = index[a], index[b]
        if i == j:
            raise ValueError(f"cannot compare {a!r} with itself")
        matrix[i, j] = value
        matrix[j, i] = 1.0 / value

    return matrix


def consistency_ratio(matrix: np.ndarray) -> tuple[float, float, float]:
    """Return (lambda_max, consistency index, consistency ratio) for a matrix."""
    n = matrix.shape[0]
    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    principal = int(np.argmax(eigenvalues.real))
    lambda_max = float(eigenvalues[principal].real)

    if n <= 2:
        # A matrix this small cannot be inconsistent: with one comparison there
        # is nothing to contradict.
        return lambda_max, 0.0, 0.0

    ci = (lambda_max - n) / (n - 1)
    ri = RANDOM_INDEX.get(n)
    if ri is None or ri == 0:
        return lambda_max, ci, 0.0
    return lambda_max, ci, ci / ri


def weights_from_matrix(
    criteria: list[str] | tuple[str, ...], matrix: np.ndarray
) -> AHPResult:
    """Derive normalised criterion weights from a pairwise comparison matrix.

    Uses the principal eigenvector, which is Saaty's original formulation and
    the one that degrades gracefully under inconsistency -- unlike the
    normalised-column-mean approximation, which is only exact when the matrix
    is perfectly consistent and quietly diverges when it is not.
    """
    criteria = tuple(criteria)
    n = len(criteria)

    if matrix.shape != (n, n):
        raise ValueError(f"matrix shape {matrix.shape} does not match {n} criteria")
    if not np.allclose(np.diag(matrix), 1.0):
        raise ValueError("comparison matrix must have 1 on the diagonal")
    if not np.allclose(matrix * matrix.T, 1.0, atol=1e-8):
        raise ValueError("comparison matrix must be reciprocal: a[i,j] == 1/a[j,i]")

    eigenvalues, eigenvectors = np.linalg.eig(matrix)
    principal = int(np.argmax(eigenvalues.real))
    vector = np.abs(eigenvectors[:, principal].real)
    weights = vector / vector.sum()

    lambda_max, ci, cr = consistency_ratio(matrix)
    return AHPResult(
        criteria=criteria,
        weights=weights,
        lambda_max=lambda_max,
        consistency_index=ci,
        consistency_ratio=cr,
    )


def weights_from_ranking(criteria: list[str] | tuple[str, ...]) -> AHPResult:
    """Fallback weights for a user who will not do the pairwise exercise.

    Applies rank-order centroid weights to the criteria in the order given --
    a standard, defensible way to turn a simple ranking into numbers, and far
    better than equal weights when the user does have an ordering in mind.
    """
    criteria = tuple(criteria)
    n = len(criteria)
    if n == 0:
        raise ValueError("need at least one criterion")
    # Rank-order centroid: w_i = (1/n) * sum_{k=i}^{n} 1/k
    weights = np.array([sum(1.0 / k for k in range(i + 1, n + 1)) / n for i in range(n)])
    weights = weights / weights.sum()
    return AHPResult(
        criteria=criteria,
        weights=weights,
        lambda_max=float(n),
        consistency_index=0.0,
        consistency_ratio=0.0,
    )
