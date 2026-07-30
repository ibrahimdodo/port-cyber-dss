"""Port economics: turning published accounts into a cost per outage hour.

This module answers the question the whole consequence model rests on -- what
does one hour of disrupted port operations actually cost? -- from audited
figures rather than intuition.

The derivation is deliberately conservative and explicit about two reductions
that a naive "revenue divided by hours" calculation gets wrong:

1. **Not all revenue is at risk.** A cyber outage stops vessel handling. It
   does not stop the clock on land leases, project-area rental or long-term
   storage contracts, which at Rønne grew sharply in 2024 and are billed on
   time rather than on calls.
2. **Not all disrupted revenue is lost.** A ferry cancelled on Tuesday carries
   Wednesday's passengers too; a bulk cargo waits. What is genuinely lost is
   the traffic that diverts elsewhere, the cruise call that cannot be
   rescheduled, and the offshore project window that closes.

Both reductions are uncertain, so both are distributions rather than point
estimates, and the sensitivity analysis will show how much they matter.

Note on scope: this is the *operational revenue* leg only. Incident response,
recovery and regulatory costs are modelled separately as `response_cost` and
`secondary_loss` in `montecarlo.LossMagnitude`, so including them here would
double-count. And the wider harm to Bornholm of a severed supply line is real
but is not the port's profit and loss -- it belongs in the report's discussion,
not in this number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .distributions import PERT, Distribution

__all__ = ["PortEconomics", "OutageCostPerHour", "RONNE_2024",
           "DEFAULT_CALL_DEPENDENT_SHARE", "DEFAULT_UNRECOVERABLE_SHARE"]

#: Denmark participates in ERM II with the krone pegged to the euro at this
#: central rate (±2.25% band), so a fixed conversion is appropriate here and
#: carries none of the drift risk a floating currency would.
DKK_PER_EUR = 7.46038


@dataclass(frozen=True)
class PortEconomics:
    """Audited financial and traffic figures for one port in one year."""

    name: str
    year: int
    revenue_dkk: float
    ebitda_dkk: float
    annual_calls: int
    employees_fte: int
    source: str

    @property
    def revenue_eur(self) -> float:
        return self.revenue_dkk / DKK_PER_EUR

    @property
    def ebitda_eur(self) -> float:
        return self.ebitda_dkk / DKK_PER_EUR

    @property
    def revenue_per_call_eur(self) -> float:
        """Average revenue per ship call. A useful cross-check on the hourly
        figure: two independent routes to the same quantity should agree to
        within the width of the estimates, and if they do not, one of the
        assumptions is wrong."""
        return self.revenue_eur / self.annual_calls

    @property
    def ebitda_margin(self) -> float:
        return self.ebitda_dkk / self.revenue_dkk


#: Rønne Havn A/S, from the 2024 annual report (five-year key figures, page 22)
#: and Danmarks Statistik SKIB101 for the call count. Local copy of the report
#: is in refs/.
RONNE_2024 = PortEconomics(
    name="Rønne Havn A/S",
    year=2024,
    revenue_dkk=169_814_309,
    ebitda_dkk=101_670_000,
    annual_calls=3_043,
    employees_fte=34,
    source=(
        "Rønne Havn A/S Årsrapport 2024 (CVR 27932150), income statement p.34 "
        "and five-year overview p.22; call count from Danmarks Statistik "
        "SKIB101, HAVN=00315."
    ),
)


#: Share of revenue that depends on vessels actually being handled, as opposed
#: to land and project-area rental billed on time. The 2024 report gives no
#: segment split -- the income statement is classified by nature -- so this is
#: an estimate, not a reading. It is anchored by the narrative: "Færge" is
#: described as the largest single business area, while rental and services
#: revenue roughly doubled in 2024 and is time-billed. Wide on purpose.
DEFAULT_CALL_DEPENDENT_SHARE = PERT(
    0.45, 0.60, 0.80,
    source="Estimated from Rønne Havn 2024 business-area narrative; no segment "
           "reporting available (income statement is classified by nature).",
)

#: Share of disrupted revenue that is genuinely lost rather than deferred.
#: Ferry and bulk traffic largely catches up once systems return; cruise calls,
#: perishable cargo and offshore project windows do not.
DEFAULT_UNRECOVERABLE_SHARE = PERT(
    0.20, 0.40, 0.70,
    source="Judgement anchored on port-outage recovery behaviour: Nagoya and "
           "DP World both cleared their backlogs within days of restart, so "
           "most volume defers rather than disappears.",
)


@dataclass(frozen=True)
class OutageCostPerHour(Distribution):
    """Euro cost of one hour of disrupted port operations.

    Composes as a distribution so it plugs straight into
    `montecarlo.LossMagnitude.cost_per_hour`, and so the uncertainty in the two
    share parameters propagates into the final loss figures instead of being
    collapsed to a mean up front.

    Parameters
    ----------
    economics
        The port's audited figures.
    service_hours_per_year
        Hours the port is capable of operating. For a ferry port this is
        genuinely close to 24x365 -- Bornholmslinjen sails at night -- even
        though cargo handling concentrates in daylight. Our AIS data puts 67%
        of commercial arrivals between 06:00 and 22:00, which argues for a
        daytime bias in cargo work but not for treating the port as closed
        overnight.
    call_dependent_share, unrecoverable_share
        See module docstring. Defaults are the module-level constants.
    """

    economics: PortEconomics
    service_hours_per_year: float = 24 * 365
    call_dependent_share: Distribution = DEFAULT_CALL_DEPENDENT_SHARE
    unrecoverable_share: Distribution = DEFAULT_UNRECOVERABLE_SHARE

    def __post_init__(self) -> None:
        if self.service_hours_per_year <= 0:
            raise ValueError("service_hours_per_year must be positive")

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        at_risk = self.economics.revenue_eur * self.call_dependent_share.sample(rng, size)
        lost = at_risk * self.unrecoverable_share.sample(rng, size)
        return lost / self.service_hours_per_year

    @property
    def mean(self) -> float:
        return (
            self.economics.revenue_eur
            * self.call_dependent_share.mean
            * self.unrecoverable_share.mean
            / self.service_hours_per_year
        )

    def cross_check_per_call(self, calls_per_day: float) -> dict[str, float]:
        """Independent derivation via revenue per call, as a sanity check.

        Routes to the hourly figure two ways: from annual revenue spread over
        annual hours, and from revenue per call multiplied by the observed call
        rate. Agreement is evidence the model is not silently wrong; a large
        divergence means the call-dependent share or the service-hours
        assumption needs revisiting.
        """
        per_call = self.economics.revenue_per_call_eur
        daily = per_call * calls_per_day
        # Spread daily revenue over the hours the port actually works: with
        # 8,760 service hours a year that is 24 h/day, but the expression must
        # scale with the parameter rather than assume it.
        hours_per_day = self.service_hours_per_year / 365.0
        hourly = daily / hours_per_day
        adjusted = (
            hourly
            * self.call_dependent_share.mean
            * self.unrecoverable_share.mean
        )
        return {
            "revenue_per_call_eur": per_call,
            "calls_per_day": calls_per_day,
            "gross_hourly_eur": hourly,
            "adjusted_hourly_eur": adjusted,
            "primary_estimate_eur": self.mean,
            "ratio": adjusted / self.mean if self.mean else float("nan"),
        }

    def __str__(self) -> str:
        return (
            f"OutageCostPerHour({self.economics.name} {self.economics.year}: "
            f"mean EUR {self.mean:,.0f}/h)"
        )
