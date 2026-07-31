"""Probability distributions for expert-estimated risk inputs.

The FAIR method asks analysts for *ranges* rather than point values, because a
calibrated expert can honestly say "between 4 and 30 hours, most likely 12" but
cannot honestly say "17.4 hours". The PERT distribution is the standard vehicle
for that kind of three-point estimate: it is bounded (unlike a lognormal, it
cannot produce a 900-hour outage), and it concentrates mass around the mode
without pretending the tails do not exist.

Every estimate used anywhere in this project should be expressible here, with a
`source` string recording where the numbers came from. An estimate without a
source is a guess wearing a lab coat.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

__all__ = ["PERT", "Constant", "Distribution"]


class Distribution:
    """Minimal interface every input distribution implements."""

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        raise NotImplementedError

    @property
    def mean(self) -> float:
        raise NotImplementedError

    def scale(self, factor: float) -> "Distribution":
        """Return this distribution multiplied by a constant.

        Needed so that applying a control's residual factor works on any
        distribution, not only PERT. Without it, callers reach for
        `PERT(d.minimum * f, ...)` and silently break the moment a frequency
        stops being a plain three-point estimate -- which is exactly what
        happens once frequencies are derived from a vendor list.
        """
        raise NotImplementedError


@dataclass(frozen=True)
class Constant(Distribution):
    """A value known exactly. Rare in risk work; useful for tests and for
    contractually fixed costs such as an annual licence fee."""

    value: float
    source: str = ""

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        return np.full(size, float(self.value))

    @property
    def mean(self) -> float:
        return float(self.value)

    def scale(self, factor: float) -> "Constant":
        if factor < 0:
            raise ValueError(f"scale factor must not be negative, got {factor}")
        return Constant(self.value * factor, self.source)


@dataclass(frozen=True)
class PERT(Distribution):
    """Beta-PERT distribution from a three-point estimate.

    Parameters
    ----------
    minimum, most_likely, maximum
        The three-point estimate. Must satisfy min <= mode <= max.
    lam
        Confidence in the mode. The classic PERT value is 4 (the mode gets four
        times the weight of either bound in the mean). Lower it to ~2 when the
        estimate is shaky; raise it when the mode is well evidenced.
    source
        Provenance of the numbers -- an incident report, a vendor quote, EPSS,
        a published base rate. Carried through so the model can explain itself.

    Notes
    -----
    Mean is (min + lam*mode + max) / (lam + 2), the standard PERT mean. The
    degenerate case min == max is supported and collapses to a constant, which
    keeps callers from having to special-case zero-width ranges.
    """

    minimum: float
    most_likely: float
    maximum: float
    lam: float = 4.0
    source: str = ""

    # Cached beta shape parameters, computed once in __post_init__.
    _alpha: float = field(default=0.0, init=False, repr=False, compare=False)
    _beta: float = field(default=0.0, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        lo, mode, hi = float(self.minimum), float(self.most_likely), float(self.maximum)

        if not (lo <= mode <= hi):
            raise ValueError(
                f"PERT requires minimum <= most_likely <= maximum, "
                f"got ({lo}, {mode}, {hi})"
            )
        if self.lam <= 0:
            raise ValueError(f"PERT lam must be positive, got {self.lam}")

        object.__setattr__(self, "minimum", lo)
        object.__setattr__(self, "most_likely", mode)
        object.__setattr__(self, "maximum", hi)

        if hi > lo:
            width = hi - lo
            alpha = 1.0 + self.lam * (mode - lo) / width
            beta = 1.0 + self.lam * (hi - mode) / width
        else:
            # Degenerate: min == max. Shapes are unused but must stay valid.
            alpha = beta = 1.0

        object.__setattr__(self, "_alpha", alpha)
        object.__setattr__(self, "_beta", beta)

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        if self.maximum == self.minimum:
            return np.full(size, self.minimum)
        draws = rng.beta(self._alpha, self._beta, size=size)
        return self.minimum + draws * (self.maximum - self.minimum)

    @property
    def mean(self) -> float:
        return (self.minimum + self.lam * self.most_likely + self.maximum) / (self.lam + 2.0)

    def scale(self, factor: float) -> "PERT":
        """Multiply the estimate by a constant, preserving its shape and source.

        Linear scaling of all three points keeps the distribution a PERT with
        the same relative skew, which is the behaviour wanted when a control
        removes a proportion of a frequency or duration.
        """
        if factor < 0:
            raise ValueError(f"scale factor must not be negative, got {factor}")
        return PERT(
            self.minimum * factor,
            self.most_likely * factor,
            self.maximum * factor,
            self.lam,
            self.source,
        )

    def __str__(self) -> str:
        src = f" [{self.source}]" if self.source else ""
        return (
            f"PERT({self.minimum:g}, {self.most_likely:g}, {self.maximum:g})"
            f"{src}"
        )
