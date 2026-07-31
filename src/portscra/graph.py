"""The dependency graph: vendor -> asset -> port service.

This is the join that makes the whole system specific to one port rather than to
ports in general. Without it there are two good engines sitting side by side: a
vendor assessment that produces probabilities nobody reads, and a scenario
catalogue whose frequencies are assumed rather than derived.

With it, the chain runs end to end. The gate integrator's assessed 13% annual
compromise probability becomes the frequency of the OT scenario, which drives
the euro figures, which drive what the optimiser buys. Improve that vendor and
the recommended portfolio changes -- which is the feedback loop a decision
support system exists to provide, and the thing a static risk register cannot do.

Two modelling choices worth stating plainly:

**Frequencies add, probabilities do not.** A scenario's loss event frequency is
the expected number of events per year, so contributions from several vendors
sum. This is correct for Poisson rates and would be wrong if these were
probabilities -- the distinction matters once a port has three suppliers touching
the same system.

**A vendor contributes in proportion to how much of the scenario it could
drive.** A supplier of one of a scenario's four target assets contributes a
quarter of its compromise rate to that scenario. This is a proxy, not a
measurement, and is the assumption in this module most worth challenging.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .risk.distributions import Distribution
from .risk.montecarlo import Scenario
from .taxonomy.assets import find_asset
from .taxonomy.scenarios import SCENARIO_TEMPLATES, ScenarioTemplate
from .vendor.likelihood import Vendor, VendorAssessment

__all__ = ["PortService", "SERVICES", "ASSET_SERVICES", "SummedFrequency",
           "DependencyGraph", "build_scenarios_from_vendors", "find_service"]


@dataclass(frozen=True)
class PortService:
    """A thing the port does for its customers, which a cyber incident can stop.

    Services rather than systems are the right unit for impact: ENISA's phase
    one recommends a service-based assessment precisely because it aggregates
    to business consequence, and because a port manager can say what a stopped
    service costs while nobody can say what a stopped server costs.
    """

    key: str
    name: str
    description: str
    #: Share of the port's call-dependent revenue this service carries. Used to
    #: apportion outage cost when only some services are affected.
    revenue_share: float
    #: Hours the port can sustain losing this service before material harm.
    tolerance_hours: float


SERVICES: tuple[PortService, ...] = (
    PortService(
        "vessel_handling", "Vessel arrival, berthing and departure",
        "Pilotage coordination, berth allocation, mooring, traffic management.",
        revenue_share=0.30, tolerance_hours=4,
    ),
    PortService(
        "cargo_handling", "Cargo loading and unloading",
        "Crane and ramp operations, freight tracking, cargo release.",
        revenue_share=0.25, tolerance_hours=8,
    ),
    PortService(
        "passenger_handling", "Passenger and vehicle handling",
        "Ferry check-in, boarding, vehicle marshalling. Schedule-critical: a "
        "ferry that misses its slot cannot simply run late.",
        revenue_share=0.25, tolerance_hours=2,
    ),
    PortService(
        "gate_operations", "Gate and access control",
        "Truck gate processing, ANPR, credentialing, perimeter access.",
        revenue_share=0.08, tolerance_hours=6,
    ),
    PortService(
        "declarations", "Customs and regulatory declarations",
        "Mandatory FAL declarations, customs clearance, single-window filing. "
        "Legally required before a vessel may work cargo.",
        revenue_share=0.05, tolerance_hours=12,
    ),
    PortService(
        "billing", "Invoicing and payments",
        "Port dues, service billing, supplier payments.",
        revenue_share=0.07, tolerance_hours=72,
    ),
)


#: Which services each asset class supports. Derived from the ENISA asset
#: taxonomy: an asset that supports no service cannot carry operational impact,
#: and is therefore absent here rather than mapped to something vague.
ASSET_SERVICES: dict[str, tuple[str, ...]] = {
    "tos": ("cargo_handling", "vessel_handling"),
    "pcs": ("vessel_handling", "declarations"),
    "ccs": ("cargo_handling", "declarations"),
    "corporate_systems": ("billing",),
    "commercial_financial": ("billing",),
    "cloud": ("billing", "declarations"),
    "mandatory_declarations": ("declarations",),
    "operational_data": ("vessel_handling", "cargo_handling"),
    "navigation_data": ("vessel_handling",),
    "ics": ("cargo_handling", "vessel_handling"),
    "loading_unloading": ("cargo_handling", "passenger_handling"),
    "temporary_storage": ("cargo_handling",),
    "hinterland_devices": ("gate_operations", "cargo_handling"),
    "access_control": ("gate_operations", "passenger_handling"),
    "detection": ("gate_operations",),
    "traffic_monitoring": ("vessel_handling",),
    "portuary_infrastructure": ("gate_operations", "vessel_handling"),
    "servers": ("cargo_handling", "billing", "declarations"),
    "workstations": ("billing", "declarations", "gate_operations"),
    "networks": ("vessel_handling", "cargo_handling", "gate_operations"),
    "switching": ("cargo_handling", "gate_operations"),
    "network_security": ("cargo_handling", "billing"),
    "radio": ("vessel_handling",),
}


def find_service(key: str) -> PortService | None:
    return next((s for s in SERVICES if s.key == key), None)


@dataclass(frozen=True)
class SummedFrequency(Distribution):
    """Total loss event frequency from several vendors' contributions.

    Samples each contributing vendor's probability distribution and sums, rather
    than approximating the sum as another PERT. The sum of PERTs is not a PERT,
    and with a handful of vendors the difference is visible in the tail -- which
    is the part of the distribution the whole exercise is about.
    """

    #: (vendor key, probability distribution, weight) per contributor.
    contributions: tuple[tuple[str, Distribution, float], ...]
    source: str = ""

    def sample(self, rng: np.random.Generator, size: int) -> np.ndarray:
        if not self.contributions:
            return np.zeros(size)
        total = np.zeros(size)
        for _, distribution, weight in self.contributions:
            total += distribution.sample(rng, size) * weight
        return total

    @property
    def mean(self) -> float:
        return sum(d.mean * w for _, d, w in self.contributions)

    def scale(self, factor: float) -> "SummedFrequency":
        if factor < 0:
            raise ValueError(f"scale factor must not be negative, got {factor}")
        return SummedFrequency(
            tuple((k, d, w * factor) for k, d, w in self.contributions),
            self.source,
        )

    @property
    def drivers(self) -> list[tuple[str, float]]:
        """Vendors ordered by how much of this frequency they contribute.

        The explanation a port manager actually wants: not "this risk is 0.14"
        but "this risk is 0.14 and three-quarters of it is your MSP".
        """
        return sorted(
            ((k, d.mean * w) for k, d, w in self.contributions),
            key=lambda kv: kv[1], reverse=True,
        )


@dataclass
class DependencyGraph:
    """Vendors, the assets they supply, and the services those assets support."""

    vendors: list[Vendor]

    def vendors_for_asset(self, asset_key: str) -> list[Vendor]:
        return [v for v in self.vendors if asset_key in v.supplies]

    def services_for_asset(self, asset_key: str) -> tuple[str, ...]:
        return ASSET_SERVICES.get(asset_key, ())

    def services_for_vendor(self, vendor: Vendor) -> set[str]:
        """Every port service that stops, or degrades, if this vendor fails."""
        services: set[str] = set()
        for asset in vendor.supplies:
            services.update(self.services_for_asset(asset))
        return services

    def revenue_at_risk(self, vendor: Vendor) -> float:
        """Share of call-dependent revenue exposed to one vendor's failure."""
        return sum(
            s.revenue_share for s in SERVICES
            if s.key in self.services_for_vendor(vendor)
        )

    def vendors_for_scenario(
        self, template: ScenarioTemplate
    ) -> list[tuple[Vendor, float]]:
        """Vendors that could drive a scenario, with their coverage of it.

        Coverage is the fraction of the scenario's target assets the vendor
        supplies -- a proxy for how completely that vendor could bring the
        scenario about on its own.
        """
        targets = set(template.target_assets)
        if not targets:
            return []
        matched = []
        for vendor in self.vendors:
            overlap = targets & set(vendor.supplies)
            if overlap:
                matched.append((vendor, len(overlap) / len(targets)))
        return matched

    def single_points_of_failure(self, threshold: float = 0.25) -> list[tuple[Vendor, float]]:
        """Vendors whose failure would expose more than `threshold` of revenue.

        The concentration question a small port most needs answered, and the one
        a per-vendor score cannot express: risk here is a property of the
        topology, not of any single supplier's security posture.
        """
        exposed = [(v, self.revenue_at_risk(v)) for v in self.vendors]
        return sorted(
            [(v, share) for v, share in exposed if share >= threshold],
            key=lambda kv: kv[1], reverse=True,
        )

    def unsupplied_assets(self, scenario_templates=SCENARIO_TEMPLATES) -> list[str]:
        """Assets that scenarios target but no known vendor supplies.

        Usually means the vendor register is incomplete rather than that the
        asset is vendor-free, so it is worth surfacing: an unlisted supplier is
        an unassessed one.
        """
        targeted: set[str] = set()
        for template in scenario_templates:
            targeted.update(template.target_assets)
        supplied = {a for v in self.vendors for a in v.supplies}
        return sorted(targeted - supplied)

    def validate(self) -> list[str]:
        """Structural problems worth reporting before trusting the output."""
        problems = []

        # Catch dangling service keys in the asset map. A typo here would
        # silently drop a service from every impact calculation that uses it.
        known_services = {s.key for s in SERVICES}
        for asset, services in ASSET_SERVICES.items():
            for service in services:
                if service not in known_services:
                    problems.append(
                        f"asset {asset!r} maps to unknown service {service!r}")

        for vendor in self.vendors:
            for asset in vendor.supplies:
                if find_asset(asset) is None:
                    problems.append(
                        f"{vendor.key}: supplies unknown asset {asset!r}")
                elif asset not in ASSET_SERVICES:
                    problems.append(
                        f"{vendor.key}: asset {asset!r} maps to no port service, "
                        f"so it cannot carry operational impact")
        for asset in self.unsupplied_assets():
            problems.append(
                f"asset {asset!r} is targeted by a scenario but no vendor supplies it")
        return problems


def build_scenarios_from_vendors(
    graph: DependencyGraph,
    assessments: dict[str, VendorAssessment],
    cost_per_hour: Distribution,
    *,
    fallback_scenarios: list[Scenario] | None = None,
    scale: float = 1.0,
) -> list[Scenario]:
    """Derive scenario frequencies from the assessed vendor list.

    Replaces the catalogue's generic priors with frequencies built from *this*
    port's suppliers. A scenario with no matching vendor keeps its generic
    frequency from `fallback_scenarios`, since the absence of a listed supplier
    is far more likely to mean an incomplete register than a risk that cannot
    occur -- zeroing it would reward not writing the vendor down.

    Loss magnitudes still come from the fallback catalogue: those depend on port
    operations and economics, not on which supplier was breached.
    """
    from .taxonomy.scenarios import build_scenarios

    generic = fallback_scenarios or build_scenarios(cost_per_hour, scale=scale)
    by_id = {s.id: s for s in generic}
    templates = {t.id: t for t in SCENARIO_TEMPLATES}

    derived: list[Scenario] = []
    for scenario in generic:
        template = templates.get(scenario.id)
        contributors = graph.vendors_for_scenario(template) if template else []

        assessed = [
            (v.key, assessments[v.key].annual_probability, coverage)
            for v, coverage in contributors
            if v.key in assessments
        ]

        if not assessed:
            derived.append(scenario)
            continue

        frequency = SummedFrequency(
            tuple(assessed),
            source=(
                f"Derived from {len(assessed)} assessed vendor(s) supplying "
                f"{scenario.id} target assets, weighted by asset coverage. "
                f"Replaces the generic prior."
            ),
        )
        derived.append(
            Scenario(
                id=scenario.id,
                name=scenario.name,
                loss_event_frequency=frequency,
                loss_magnitude=scenario.loss_magnitude,
                enisa_threat=scenario.enisa_threat,
                attack_techniques=scenario.attack_techniques,
                stride=scenario.stride,
                notes=scenario.notes,
            )
        )
    return derived
