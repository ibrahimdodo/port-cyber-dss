"""Validation: does the model tell the truth, and does it beat the alternative?

The football-recruitment DSS this project is measured against had one
illustrative case study and no validation section at all. Three checks here,
each answering a question an examiner would actually ask.

**1. Incident replay.** Real port cyber incidents have documented durations. Do
they fall inside the model's predicted band? Incidents are split into those used
to *anchor* the estimates and those *held out*. Only the held-out ones are
evidence: checking a model against the data used to build it is a consistency
check, not a validation, and reporting it as validation would be dishonest.

**2. Baseline duel.** A 5x5 qualitative risk matrix is what CSET, MONARC and
most port risk registers actually produce. Scoring the same scenarios both ways
shows whether the quantitative machinery earns its cost -- in ranking agreement,
in range compression, and most importantly in what each method tells the port to
buy with the same budget.

**3. Persona sweep.** The brief specifies 10, 50 and 100 employees. Rønne Havn
turns out to employ 34, which makes the sweep a real question rather than a
formality.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .controls.catalogue import Control
from .controls.optimiser import optimise, residual_ale, scenario_ale
from .risk.montecarlo import Scenario

__all__ = ["Incident", "INCIDENTS", "ReplayResult", "replay_incident",
           "MatrixScore", "qualitative_score", "matrix_led_portfolio",
           "BaselineComparison", "compare_to_matrix"]


@dataclass(frozen=True)
class Incident:
    """A documented port cyber incident, for replaying against the model."""

    name: str
    year: int
    #: Hours of *operational* disruption -- cargo or passenger handling stopped
    #: or materially degraded. Not IT recovery time, which is usually longer and
    #: is not what the consequence model predicts.
    downtime_hours: float
    scenario_id: str
    source: str
    #: True where this incident informed the model's estimates. Anchoring
    #: incidents cannot validate the model they calibrated.
    used_as_anchor: bool = False
    notes: str = ""


INCIDENTS: tuple[Incident, ...] = (
    # --- anchors: these set the estimates, so they only check consistency ---
    Incident(
        "Port of Nagoya (LockBit)", 2023, 60.0, "S2",
        "Container operations suspended 5 July 2023, fully restarted the "
        "evening of 6 July; roughly two and a half days.",
        used_as_anchor=True,
        notes="Japan's busiest cargo port. Used to set the S2 downtime mode.",
    ),
    Incident(
        "DP World Australia", 2023, 72.0, "S2",
        "Roughly three days of disrupted operations; about 30,000 containers "
        "stranded across four terminals.",
        used_as_anchor=True,
    ),
    # --- held out: genuine tests of the model ---
    Incident(
        "COSCO Americas", 2018, 120.0, "S2",
        "Ransomware on 24 July 2018; network applications in the Americas "
        "reported fully recovered by 30 July -- about five days.",
        notes="Held out. Tests the upper middle of the S2 band.",
    ),
    Incident(
        "Transnet (Durban and others)", 2021, 120.0, "S2",
        "Ransomware 22 July 2021; force majeure declared at Durban, Ngqura, "
        "Port Elizabeth and Cape Town; most systems restored by 26 July, with "
        "disruption over roughly a week.",
        notes="Held out. Four terminals at once, so the upper end is expected.",
    ),
    Incident(
        "Port of Barcelona", 2018, 0.0, "S2",
        "IT systems hit 20 September 2018. Loading and unloading processes were "
        "affected, but maritime operations were reported unaffected and ships "
        "operated within normal parameters.",
        notes="Held out. Tests whether the model admits a near-zero outcome -- "
              "a ransomware incident that does not stop the quay.",
    ),
    Incident(
        "Port of San Diego", 2018, 0.0, "S2",
        "Ransomware 25 September 2018 affecting park permits and records "
        "processing; ordinary operations including ship access reported "
        "unaffected.",
        notes="Held out. Same test as Barcelona.",
    ),
)


@dataclass(frozen=True)
class ReplayResult:
    incident: Incident
    percentile: float
    p10: float
    p50: float
    p90: float
    inside_band: bool

    @property
    def verdict(self) -> str:
        if self.inside_band:
            return "inside P10-P90"
        return "BELOW P10" if self.percentile < 10 else "ABOVE P90"


def replay_incident(
    scenario: Scenario, incident: Incident, *, iterations: int = 100_000,
    seed: int = 42,
) -> ReplayResult:
    """Where does a real incident's duration fall in the modelled distribution?

    Compares against the *per-event* downtime distribution, not the annualised
    aggregate: the question is "when this happens, does the model predict a
    duration like the one observed", which is a statement about one event.
    """
    rng = np.random.default_rng(seed)
    # Through the disruption gate, not the raw duration distribution: the
    # question is what operational downtime the model predicts, and a share of
    # incidents produce none at all.
    draws = scenario.loss_magnitude.sample_downtime(rng, iterations)
    percentile = float((draws < incident.downtime_hours).mean() * 100)
    p10, p50, p90 = (float(np.percentile(draws, q)) for q in (10, 50, 90))
    return ReplayResult(
        incident=incident,
        percentile=percentile,
        p10=p10, p50=p50, p90=p90,
        inside_band=p10 <= incident.downtime_hours <= p90,
    )


# --------------------------------------------------------------------------
# Baseline: the 5x5 qualitative matrix
# --------------------------------------------------------------------------

#: Likelihood bands, in events per year. Conventional wording from ISO 31000
#: style registers.
LIKELIHOOD_BANDS = (
    (0.05, 1, "Rare"),
    (0.20, 2, "Unlikely"),
    (0.50, 3, "Possible"),
    (1.00, 4, "Likely"),
    (float("inf"), 5, "Almost certain"),
)

#: Impact bands, in euro per event.
IMPACT_BANDS = (
    (10_000, 1, "Insignificant"),
    (50_000, 2, "Minor"),
    (250_000, 3, "Moderate"),
    (1_000_000, 4, "Major"),
    (float("inf"), 5, "Catastrophic"),
)


@dataclass(frozen=True)
class MatrixScore:
    scenario_id: str
    likelihood: int
    likelihood_label: str
    impact: int
    impact_label: str

    @property
    def score(self) -> int:
        return self.likelihood * self.impact

    @property
    def rating(self) -> str:
        if self.score >= 15:
            return "Critical"
        if self.score >= 10:
            return "High"
        if self.score >= 5:
            return "Medium"
        return "Low"


def qualitative_score(scenario: Scenario) -> MatrixScore:
    """Score a scenario the way a conventional risk register would.

    Deliberately fed from the same underlying estimates as the quantitative
    model, so the comparison isolates the *method* rather than the inputs. If
    the matrix were given worse data too, any difference would be confounded.
    """
    frequency = scenario.loss_event_frequency.mean
    lm = scenario.loss_magnitude
    per_event = (
        lm.downtime_hours.mean * lm.disruption_probability * lm.cost_per_hour.mean
        + lm.response_cost.mean
        + (lm.secondary_loss.mean * lm.secondary_probability
           if lm.secondary_loss is not None else 0.0)
    )

    likelihood, likelihood_label = next(
        (score, label) for threshold, score, label in LIKELIHOOD_BANDS
        if frequency < threshold
    )
    impact, impact_label = next(
        (score, label) for threshold, score, label in IMPACT_BANDS
        if per_event < threshold
    )
    return MatrixScore(scenario.id, likelihood, likelihood_label,
                       impact, impact_label)


def matrix_led_portfolio(
    scenarios: list[Scenario],
    catalogue: tuple[Control, ...] | list[Control],
    budget: float,
) -> list[Control]:
    """What "fix the reddest cell first" actually buys.

    The policy a heat map induces: work down the scenarios by rating, and for
    each one buy the controls that address it, cheapest first, until the money
    runs out. This is a fair rendering of how risk registers drive spending --
    not a straw man, and notably it is not stupid. It simply cannot see that a
    cheap control touching four amber risks may beat an expensive one touching a
    single red.
    """
    scores = {s.id: qualitative_score(s) for s in scenarios}
    order = sorted(scenarios, key=lambda s: scores[s.id].score, reverse=True)

    selected: list[Control] = []
    spent = 0.0
    for scenario in order:
        addressing = sorted(
            (c for c in catalogue
             if c.id not in {x.id for x in selected} and scenario.id in c.effects),
            key=lambda c: c.annual_cost_eur,
        )
        for control in addressing:
            if spent + control.annual_cost_eur <= budget:
                selected.append(control)
                spent += control.annual_cost_eur
    return selected


@dataclass(frozen=True)
class BaselineComparison:
    budget: float
    matrix_controls: tuple[str, ...]
    quantitative_controls: tuple[str, ...]
    matrix_residual: float
    quantitative_residual: float
    matrix_cost: float
    quantitative_cost: float
    baseline: float

    @property
    def advantage(self) -> float:
        """Extra expected loss avoided per year by optimising rather than
        following the heat map."""
        return self.matrix_residual - self.quantitative_residual

    @property
    def advantage_pct(self) -> float:
        return self.advantage / self.baseline if self.baseline else 0.0


def compare_to_matrix(
    scenarios: list[Scenario],
    catalogue: tuple[Control, ...] | list[Control],
    budget: float,
) -> BaselineComparison:
    """Spend the same budget both ways and measure the difference."""
    matrix = matrix_led_portfolio(scenarios, catalogue, budget)
    quantitative = optimise(scenarios, catalogue, budget)
    return BaselineComparison(
        budget=budget,
        matrix_controls=tuple(sorted(c.id for c in matrix)),
        quantitative_controls=tuple(sorted(c.id for c in quantitative.controls)),
        matrix_residual=residual_ale(scenarios, matrix),
        quantitative_residual=quantitative.residual_ale,
        matrix_cost=sum(c.annual_cost_eur for c in matrix),
        quantitative_cost=quantitative.cost,
        baseline=sum(scenario_ale(s) for s in scenarios),
    )


def range_compression(scenarios: list[Scenario]) -> dict[str, list[str]]:
    """Which scenarios the matrix cannot tell apart.

    Cox (2008) calls this range compression: a 5x5 grid has 25 cells but only
    four ratings, so risks differing by an order of magnitude in expected loss
    land in the same colour and become indistinguishable to whoever is
    allocating budget.
    """
    grouped: dict[str, list[str]] = {}
    for scenario in scenarios:
        grouped.setdefault(qualitative_score(scenario).rating, []).append(scenario.id)
    return grouped


def rank_agreement(scenarios: list[Scenario]) -> float:
    """Spearman rank correlation between matrix score and quantitative ALE.

    A high correlation would mean the matrix orders risks acceptably and the
    quantitative machinery is buying precision rather than a different answer.
    Computed directly rather than pulled from scipy so the arithmetic is
    visible, and because ties need explicit handling -- ties are the interesting
    part here, since the matrix produces many and the quantitative model none.
    """
    ids = [s.id for s in scenarios]
    matrix = {s.id: qualitative_score(s).score for s in scenarios}
    quant = {s.id: scenario_ale(s) for s in scenarios}

    def ranks(values: dict[str, float]) -> dict[str, float]:
        ordered = sorted(ids, key=lambda k: values[k])
        result: dict[str, float] = {}
        i = 0
        while i < len(ordered):
            j = i
            while j + 1 < len(ordered) and values[ordered[j + 1]] == values[ordered[i]]:
                j += 1
            average = (i + j) / 2 + 1
            for k in range(i, j + 1):
                result[ordered[k]] = average
            i = j + 1
        return result

    a, b = ranks(matrix), ranks(quant)
    x = np.array([a[i] for i in ids])
    y = np.array([b[i] for i in ids])
    x, y = x - x.mean(), y - y.mean()
    denominator = np.sqrt((x**2).sum() * (y**2).sum())
    return float((x * y).sum() / denominator) if denominator else 0.0
