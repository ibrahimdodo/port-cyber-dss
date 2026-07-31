"""Turn vendor evidence into a compromise probability the risk engine can use.

Two sources of evidence, deliberately fused rather than chosen between:

**The questionnaire** covers everything, including vendors no scanner has ever
heard of -- the crane OEM, the local integrator -- but it is self-reported and
static. **External signals** (EPSS, CISA KEV, OpenSSF Scorecard) are objective
and current but only exist for vendors with published software and CVEs.

Neither alone is adequate for a small port's supplier list, which mixes global
SaaS with a two-person integrator. Together they degrade gracefully: a vendor
with no signals falls back to questionnaire evidence, and a vendor that will
not answer the questionnaire is still assessed on what is publicly observable.

The output is a probability *band*, not a point. A vendor assessed as "roughly
3% to 14% chance of a compromise affecting us this year, most likely 6%" is an
honest statement; "7.3%" is not, and the false precision would propagate
straight into the euro figures.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..risk.distributions import PERT
from .questionnaire import CRITERIA, DEFAULT_WEIGHTS, QUESTIONS, Question

__all__ = ["VendorSignals", "Vendor", "VendorAssessment", "LikelihoodModel",
           "BASE_RATE", "EXPOSURE_RANGE"]

#: Prior annual probability that a given supplier suffers a compromise
#: consequential for its customers, before anything is known about this
#: particular vendor. Anchored on the observed cadence of supplier-borne
#: incidents affecting downstream organisations (SolarWinds, Kaseya, 3CX,
#: MOVEit, xz-utils within roughly five years) and on Verizon DBIR's finding
#: that third-party involvement appears in around 30% of breaches.
BASE_RATE = PERT(
    0.02, 0.05, 0.12,
    source="Prior for supplier compromise affecting a customer; anchored on "
           "documented supply-chain incident cadence 2020-2024 and DBIR "
           "third-party involvement trend.",
)

#: How far evidence may move the prior. A vendor with excellent posture and no
#: adverse signals lands at 0.4x the base rate; a poor one at 2.5x. The range
#: is bounded on purpose: a questionnaire cannot justify claiming a supplier is
#: twenty times safer than average, and unbounded multipliers would let a
#: vendor talk its way to negligible risk.
EXPOSURE_RANGE = (0.4, 2.5)


@dataclass(frozen=True)
class VendorSignals:
    """Externally observable evidence. Every field is optional -- absence is
    itself informative and must not be confused with a good result."""

    #: Highest EPSS probability among CVEs known to affect the vendor's product
    #: (0-1, the chance of exploitation within 30 days). From FIRST's daily feed.
    max_epss: float | None = None
    #: Count of the vendor's CVEs in CISA's Known Exploited Vulnerabilities
    #: catalogue. Any entry means exploitation is not hypothetical.
    kev_count: int = 0
    #: OpenSSF Scorecard result (0-10) where the product is open source. This is
    #: the answer to the brief's "freeware?" question -- the one class of
    #: supplier that cannot be sent a questionnaire.
    openssf_scorecard: float | None = None
    #: Disclosed breach within the last 24 months.
    recent_breach: bool = False
    source: str = ""

    @property
    def has_any(self) -> bool:
        return (
            self.max_epss is not None
            or self.kev_count > 0
            or self.openssf_scorecard is not None
            or self.recent_breach
        )


@dataclass
class Vendor:
    """A supplier, the assets it provides, and what we know about it."""

    key: str
    name: str
    category: str
    #: Asset sub-category keys from `taxonomy.assets` that this vendor supplies.
    supplies: tuple[str, ...] = ()
    #: Question id -> chosen option index. Partial answers are fine.
    answers: dict[str, int] = field(default_factory=dict)
    signals: VendorSignals = field(default_factory=VendorSignals)
    notes: str = ""

    @property
    def answered_fraction(self) -> float:
        return len(self.answers) / len(QUESTIONS) if QUESTIONS else 0.0


@dataclass(frozen=True)
class VendorAssessment:
    """Result of assessing one vendor, with the reasoning kept inspectable."""

    vendor: Vendor
    criterion_scores: dict[str, float]
    posture_score: float
    exposure_multiplier: float
    signal_multiplier: float
    annual_probability: PERT
    unanswered: tuple[str, ...]

    @property
    def coverage(self) -> float:
        """Fraction of questions answered. Low coverage does not invalidate the
        assessment but should be shown alongside it -- a confident-looking
        number from three answers deserves scepticism."""
        return 1.0 - len(self.unanswered) / len(QUESTIONS)

    def explain(self) -> str:
        lines = [
            f"{self.vendor.name} ({self.vendor.category})",
            f"  posture score      {self.posture_score:.3f}  (0 best, 1 worst)",
        ]
        for key, score in sorted(self.criterion_scores.items(), key=lambda kv: -kv[1]):
            name = next((c.name for c in CRITERIA if c.key == key), key)
            lines.append(f"    {name:36s} {score:.2f}")
        lines += [
            f"  exposure multiplier {self.exposure_multiplier:.2f}x  (from posture)",
            f"  signal multiplier   {self.signal_multiplier:.2f}x  (from EPSS/KEV/OpenSSF)",
            f"  P(compromise)/yr    {self.annual_probability.minimum:.1%} .. "
            f"{self.annual_probability.maximum:.1%}  "
            f"(most likely {self.annual_probability.most_likely:.1%})",
            f"  questionnaire coverage {self.coverage:.0%}",
        ]
        if self.unanswered:
            lines.append(f"  unanswered: {', '.join(self.unanswered)}")
        return "\n".join(lines)


@dataclass(frozen=True)
class LikelihoodModel:
    """Scores vendors into probability bands.

    Parameters
    ----------
    weights
        Criterion weights, normally from an AHP session with the port. Defaults
        to the literature-derived weights in `questionnaire.DEFAULT_WEIGHTS`.
    base_rate
        Prior annual compromise probability before vendor-specific evidence.
    exposure_range
        Bounds on how far posture may move the prior.
    """

    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    base_rate: PERT = BASE_RATE
    exposure_range: tuple[float, float] = EXPOSURE_RANGE

    def __post_init__(self) -> None:
        known = {c.key for c in CRITERIA}
        unknown = set(self.weights) - known
        if unknown:
            raise ValueError(f"unknown criteria in weights: {sorted(unknown)}")
        total = sum(self.weights.values())
        if total <= 0:
            raise ValueError("criterion weights must sum to a positive value")

    def _criterion_scores(self, vendor: Vendor) -> tuple[dict[str, float], list[str]]:
        """Weighted mean risk score per criterion, plus unanswered question ids.

        Criteria with no answers are omitted rather than defaulted to zero:
        scoring an unasked question as "good" would reward non-disclosure, which
        is the opposite of what a supply-chain assessment should do.
        """
        by_criterion: dict[str, list[tuple[Question, int]]] = {}
        unanswered: list[str] = []

        for question in QUESTIONS:
            if question.id in vendor.answers:
                by_criterion.setdefault(question.criterion, []).append(
                    (question, vendor.answers[question.id])
                )
            else:
                unanswered.append(question.id)

        scores: dict[str, float] = {}
        for criterion, answered in by_criterion.items():
            weight_sum = sum(q.weight for q, _ in answered)
            scores[criterion] = sum(
                q.score(index) * q.weight for q, index in answered
            ) / weight_sum

        return scores, unanswered

    def _posture(self, criterion_scores: dict[str, float]) -> float:
        """Combine criterion scores using the AHP weights.

        Renormalises over the criteria that were actually scored, so a vendor
        who answered only the access questions is judged on access rather than
        being silently credited for the rest.
        """
        if not criterion_scores:
            # No evidence at all. Assume the middle rather than the best case:
            # an unassessed vendor is not a safe vendor.
            return 0.5

        weight_sum = sum(self.weights.get(k, 0.0) for k in criterion_scores)
        if weight_sum <= 0:
            return sum(criterion_scores.values()) / len(criterion_scores)
        return sum(
            score * self.weights.get(key, 0.0)
            for key, score in criterion_scores.items()
        ) / weight_sum

    def _exposure_multiplier(self, posture: float) -> float:
        """Map posture in [0, 1] to a multiplier on the base rate.

        Geometric rather than linear interpolation, because risk multipliers
        compound: the step from "good" to "average" should be the same *factor*
        as from "average" to "poor", not the same absolute amount.
        """
        low, high = self.exposure_range
        return low * (high / low) ** max(0.0, min(1.0, posture))

    def _signal_multiplier(self, signals: VendorSignals) -> float:
        """Adjustment from externally observable evidence.

        Deliberately asymmetric: adverse signals raise risk substantially, but
        their absence lowers it only slightly. Not appearing in CISA KEV is weak
        evidence of safety -- most software never gets the scrutiny -- whereas
        appearing in it is strong evidence of danger.
        """
        multiplier = 1.0

        if signals.kev_count > 0:
            # Known exploited in the wild: not a hypothetical vulnerability.
            multiplier *= 1.0 + min(0.8, 0.3 * signals.kev_count)

        if signals.max_epss is not None:
            # EPSS is P(exploitation within 30 days). 0.5 is very high.
            multiplier *= 1.0 + min(0.6, signals.max_epss)

        if signals.openssf_scorecard is not None:
            # Scorecard runs 0-10, higher is better. 5 is treated as neutral.
            deviation = (5.0 - signals.openssf_scorecard) / 5.0
            multiplier *= 1.0 + 0.3 * max(-1.0, min(1.0, deviation))

        if signals.recent_breach:
            multiplier *= 1.4

        return multiplier

    def assess(self, vendor: Vendor) -> VendorAssessment:
        criterion_scores, unanswered = self._criterion_scores(vendor)
        posture = self._posture(criterion_scores)
        exposure = self._exposure_multiplier(posture)
        signal = self._signal_multiplier(vendor.signals)

        factor = exposure * signal
        # PERT scales linearly, so multiplying the three points preserves the
        # shape of the prior while shifting its location.
        probability = PERT(
            min(1.0, self.base_rate.minimum * factor),
            min(1.0, self.base_rate.most_likely * factor),
            min(1.0, self.base_rate.maximum * factor),
            source=(
                f"{self.base_rate.source} Adjusted x{factor:.2f} for "
                f"{vendor.name} (posture {posture:.2f}, signals {signal:.2f}x)."
            ),
        )

        return VendorAssessment(
            vendor=vendor,
            criterion_scores=criterion_scores,
            posture_score=posture,
            exposure_multiplier=exposure,
            signal_multiplier=signal,
            annual_probability=probability,
            unanswered=tuple(unanswered),
        )

    def rank(self, vendors: list[Vendor]) -> list[VendorAssessment]:
        """Assess every vendor, worst first."""
        return sorted(
            (self.assess(v) for v in vendors),
            key=lambda a: a.annual_probability.mean,
            reverse=True,
        )
