"""FAIR-style Monte Carlo risk engine.

Implements the part of the Open FAIR ontology this project actually needs:

    Annualised loss  =  sum over the year's loss events of each event's magnitude
    number of events ~  Poisson(Loss Event Frequency)
    event magnitude  =  downtime_hours x cost_per_hour  +  response_cost  +  fines

The Poisson step matters and is what separates this from the common shortcut of
multiplying a frequency by a magnitude. Multiplying gives you the *mean* and
nothing else; a port that suffers 0 incidents in most years and 2 in a bad one
has a bimodal loss distribution, and the whole point of the exercise is to see
that shape -- the P90 tail is what justifies spending money.

Everything is vectorised over iterations: one `simulate()` call draws all
iterations at once rather than looping, so 100k iterations across a dozen
scenarios stays comfortably interactive inside a Streamlit callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .distributions import Distribution

__all__ = ["LossMagnitude", "Scenario", "SimulationResult", "simulate"]


@dataclass(frozen=True)
class LossMagnitude:
    """Cost of a single loss event, decomposed into inspectable parts.

    Kept as separate components rather than one lump sum so the dashboard can
    answer "why is this number so big?" -- which is the question that decides
    whether a stakeholder trusts the model. Primary loss is the direct
    operational hit; secondary loss covers consequences that only sometimes
    follow (regulatory penalties, customers leaving).

    Parameters
    ----------
    downtime_hours
        Hours of service outage caused by the event.
    cost_per_hour
        Euro cost of one hour of that outage. Calibrated per port and per
        service from AIS-derived traffic and published port accounts.
    response_cost
        One-off incident response, forensics, overtime, rebuild.
    secondary_loss
        Fines, legal costs, lost customers. Only realised with probability
        `secondary_probability`.
    secondary_probability
        Chance the secondary loss materialises at all. NIS2 penalties, for
        instance, follow only a fraction of reportable incidents.
    """

    downtime_hours: Distribution
    cost_per_hour: Distribution
    response_cost: Distribution
    secondary_loss: Distribution | None = None
    secondary_probability: float = 0.0
    #: Probability that the event disrupts *operations* at all, as opposed to
    #: hitting IT while the quay keeps working.
    #:
    #: Added in response to a validation failure rather than by design. Held-out
    #: incident replay showed Barcelona and San Diego (both 2018) suffered
    #: ransomware with no reported effect on vessel operations, an outcome the
    #: model could not produce because its downtime estimate had a floor of 24
    #: hours. Separating "an incident happened" from "operations stopped" is the
    #: faithful fix; simply lowering the floor would have blurred two distinct
    #: things together.
    disruption_probability: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.disruption_probability <= 1.0:
            raise ValueError(
                f"disruption_probability must be in [0, 1], "
                f"got {self.disruption_probability}"
            )

    def sample_downtime(self, rng: np.random.Generator, size: int) -> np.ndarray:
        """Effective operational downtime, after the disruption gate."""
        hours = self.downtime_hours.sample(rng, size)
        if self.disruption_probability >= 1.0:
            return hours
        disrupts = rng.random(size) < self.disruption_probability
        return np.where(disrupts, hours, 0.0)

    def sample(self, rng: np.random.Generator, size: int) -> dict[str, np.ndarray]:
        """Draw `size` event magnitudes, returning each component separately."""
        hours = self.sample_downtime(rng, size)
        rate = self.cost_per_hour.sample(rng, size)
        outage = hours * rate
        response = self.response_cost.sample(rng, size)

        if self.secondary_loss is not None and self.secondary_probability > 0:
            secondary = self.secondary_loss.sample(rng, size)
            realised = rng.random(size) < self.secondary_probability
            secondary = np.where(realised, secondary, 0.0)
        else:
            secondary = np.zeros(size)

        return {
            "downtime_hours": hours,
            "outage_cost": outage,
            "response_cost": response,
            "secondary_loss": secondary,
            "total": outage + response + secondary,
        }


@dataclass(frozen=True)
class Scenario:
    """One risk scenario: how often it happens, and what it costs when it does.

    `loss_event_frequency` is in events per year and may be well below 1 -- a
    frequency of 0.05 means "expected once every twenty years", which the
    Poisson step turns into "no event in 95% of years, one event in most of the
    rest, occasionally two".
    """

    id: str
    name: str
    loss_event_frequency: Distribution
    loss_magnitude: LossMagnitude
    enisa_threat: str = ""
    attack_techniques: tuple[str, ...] = ()
    stride: tuple[str, ...] = ()
    notes: str = ""


@dataclass
class SimulationResult:
    """Annualised loss distribution for one scenario or a portfolio of them."""

    annual_loss: np.ndarray
    annual_downtime_hours: np.ndarray
    event_counts: np.ndarray
    label: str = ""
    components: dict[str, float] = field(default_factory=dict)

    @property
    def ale(self) -> float:
        """Annualised Loss Expectancy -- the mean. Useful for ranking and for
        the optimiser's objective, but never quote it alone: for a low-frequency
        high-impact risk the mean falls in a gap where no actual year lands."""
        return float(self.annual_loss.mean())

    def percentile(self, p: float) -> float:
        return float(np.percentile(self.annual_loss, p))

    @property
    def p10(self) -> float:
        return self.percentile(10)

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p90(self) -> float:
        return self.percentile(90)

    @property
    def probability_of_any_loss(self) -> float:
        """Share of simulated years with at least one loss event."""
        return float((self.event_counts > 0).mean())

    def exceedance_curve(self, points: int = 200) -> tuple[np.ndarray, np.ndarray]:
        """Loss exceedance curve: P(annual loss > x) as a function of x.

        This is the chart that communicates risk to non-specialists better than
        any single number -- "there is a 1-in-10 chance of losing more than
        EUR X this year" is a sentence a port director can act on.
        """
        losses = np.sort(self.annual_loss)
        probs = 1.0 - np.arange(1, losses.size + 1) / losses.size
        if losses.size > points:
            idx = np.linspace(0, losses.size - 1, points).astype(int)
            losses, probs = losses[idx], probs[idx]
        return losses, probs

    def summary(self) -> dict[str, float]:
        return {
            "ale": self.ale,
            "p10": self.p10,
            "p50": self.p50,
            "p90": self.p90,
            "p99": self.percentile(99),
            "max": float(self.annual_loss.max()),
            "mean_downtime_hours": float(self.annual_downtime_hours.mean()),
            "p90_downtime_hours": float(np.percentile(self.annual_downtime_hours, 90)),
            "prob_any_loss": self.probability_of_any_loss,
            "mean_events_per_year": float(self.event_counts.mean()),
        }


def _simulate_one(
    scenario: Scenario, rng: np.random.Generator, iterations: int
) -> SimulationResult:
    """Simulate a single scenario over `iterations` synthetic years."""
    # Frequency is itself uncertain: draw a rate per simulated year, then draw
    # the actual event count from a Poisson with that rate. This nests
    # uncertainty about the rate inside randomness of occurrence, which is the
    # behaviour FAIR intends and a plain Poisson with a fixed rate would lose.
    rates = np.clip(scenario.loss_event_frequency.sample(rng, iterations), 0.0, None)
    counts = rng.poisson(rates)

    annual_loss = np.zeros(iterations)
    annual_hours = np.zeros(iterations)
    components: dict[str, float] = {}

    total_events = int(counts.sum())
    if total_events > 0:
        draws = scenario.loss_magnitude.sample(rng, total_events)
        # Map each drawn event back to the year it belongs to, then aggregate.
        year_index = np.repeat(np.arange(iterations), counts)
        annual_loss = np.bincount(
            year_index, weights=draws["total"], minlength=iterations
        )
        annual_hours = np.bincount(
            year_index, weights=draws["downtime_hours"], minlength=iterations
        )
        components = {
            "outage_cost": float(draws["outage_cost"].sum() / iterations),
            "response_cost": float(draws["response_cost"].sum() / iterations),
            "secondary_loss": float(draws["secondary_loss"].sum() / iterations),
        }

    return SimulationResult(
        annual_loss=annual_loss,
        annual_downtime_hours=annual_hours,
        event_counts=counts,
        label=scenario.name,
        components=components,
    )


def simulate(
    scenarios: Scenario | list[Scenario],
    iterations: int = 50_000,
    seed: int | None = 42,
) -> dict[str, SimulationResult]:
    """Run the Monte Carlo over one or more scenarios.

    Returns a dict keyed by scenario id, plus a ``"__portfolio__"`` entry
    holding the summed annual loss across all scenarios. The portfolio entry is
    what the optimiser measures its mitigations against.

    The default seed is fixed so results are reproducible; pass ``seed=None``
    for a fresh stream. Reproducibility matters here -- a risk figure that
    changes every time you reload the dashboard destroys trust in it.
    """
    if isinstance(scenarios, Scenario):
        scenarios = [scenarios]
    if not scenarios:
        raise ValueError("simulate() needs at least one scenario")
    if iterations < 1:
        raise ValueError(f"iterations must be >= 1, got {iterations}")

    rng = np.random.default_rng(seed)
    results: dict[str, SimulationResult] = {}

    for scenario in scenarios:
        results[scenario.id] = _simulate_one(scenario, rng, iterations)

    portfolio_loss = np.sum([r.annual_loss for r in results.values()], axis=0)
    portfolio_hours = np.sum([r.annual_downtime_hours for r in results.values()], axis=0)
    portfolio_counts = np.sum([r.event_counts for r in results.values()], axis=0)

    results["__portfolio__"] = SimulationResult(
        annual_loss=portfolio_loss,
        annual_downtime_hours=portfolio_hours,
        event_counts=portfolio_counts,
        label="All scenarios",
    )
    return results


def annual_disturbance_pct(
    result: SimulationResult, annual_service_hours: float
) -> np.ndarray:
    """Convert annual downtime hours into "operations disturbance in %".

    The assignment asks for disturbance as a percentage, which is only
    meaningful against a stated denominator. Here that denominator is the
    port's annual service hours, derived from AIS-observed operating patterns
    rather than assumed to be 24x365 -- a port that works 16-hour days is not
    disturbed for two thirds of the year simply by being closed at night.
    """
    if annual_service_hours <= 0:
        raise ValueError("annual_service_hours must be positive")
    return 100.0 * result.annual_downtime_hours / annual_service_hours
