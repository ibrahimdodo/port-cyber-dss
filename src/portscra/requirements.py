"""Security requirements to place on suppliers, derived from what they supply.

The brief asks the DSS to "elaborate security requirements for Vendors/Assets"
and to "identify the security requirements for the vendors of that assets". The
second phrasing carries the design: requirements are a function of *what the
supplier touches*, not a single checklist issued to everyone.

That matters practically. A small port has no leverage to impose enterprise
security terms on every supplier, and trying would get the important clauses
negotiated away alongside the trivial ones. So requirements are tiered by what
the asset can actually do to the port if the supplier fails, and the essential
tier is kept short enough to survive a procurement conversation.

Three things this produces that a static checklist cannot:

* **Scoping** -- the crane OEM and the stationery supplier get different demands,
  because the dependency graph knows one can stop cargo and the other cannot.
* **Gap analysis** -- requirements are keyed to the questionnaire questions that
  verify them, so the port can see which of its own requirements a supplier has
  already failed to meet, from answers it has already collected.
* **Procurement text** -- output as clauses, because a requirement that never
  reaches a contract is an opinion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .taxonomy.assets import Relevance, find_asset
from .taxonomy.scenarios import SCENARIO_TEMPLATES

__all__ = ["Tier", "Requirement", "REQUIREMENTS", "RequirementSet",
           "requirements_for_assets", "requirements_for_vendor", "as_clauses",
           "MAX_ESSENTIAL"]

#: Ceiling on how many requirements any one supplier sees as ESSENTIAL.
#: The essential tier is the list a port is willing to lose a supplier over, so
#: it has to be short enough to hold in a negotiation. Without a cap, escalation
#: put nine of ten items in the tier for the most exposed suppliers, at which
#: point the important clauses get traded away alongside the rest.
MAX_ESSENTIAL = 8


class Tier(str, Enum):
    """How hard to push for a requirement.

    ESSENTIAL is the short list a port should be willing to lose a supplier
    over. RECOMMENDED is what to ask for and accept a plan against. ADVANCED
    applies where the supplier can stop operations outright.
    """

    ESSENTIAL = "essential"
    RECOMMENDED = "recommended"
    ADVANCED = "advanced"


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    #: The requirement as it should appear in a contract or RFP.
    text: str
    #: Why this one, for a port specifically.
    rationale: str
    #: What the port should ask to see. A requirement with no evidence test is
    #: a statement of hope.
    evidence: str
    tier: Tier
    #: NIS2 Article 21(2) points this discharges.
    nis2: tuple[str, ...]
    cis_safeguards: tuple[str, ...] = ()
    #: Questionnaire question ids that verify it, enabling gap analysis against
    #: answers the port has already collected.
    verified_by: tuple[str, ...] = ()
    #: Scenario ids this requirement bears on. Used to scope requirements to the
    #: assets a supplier actually provides.
    scenarios: tuple[str, ...] = ()
    #: Restrict to suppliers of these asset classes. Empty means it applies to
    #: any supplier with access to port systems or data.
    asset_keys: tuple[str, ...] = ()


REQUIREMENTS: tuple[Requirement, ...] = (
    # ---------------------------------------------------------- universal
    Requirement(
        "R01", "Incident notification within 24 hours",
        "The supplier shall notify the port within 24 hours of becoming aware "
        "of any security incident that affects, or may affect, the port's data, "
        "systems or services, and shall provide updates until the incident is "
        "resolved.",
        "NIS2 Article 23 gives the port 24 hours to submit an early warning. A "
        "supplier that reports on its own timetable makes that deadline "
        "impossible to meet, and the obligation rests with the port regardless.",
        "The clause itself, plus a named contact and out-of-hours route tested "
        "at least annually.",
        Tier.ESSENTIAL, ("b", "d"), ("15.4",), ("Q16",), ("S1", "S2", "S7"),
    ),
    Requirement(
        "R02", "Multi-factor authentication on all access to port systems",
        "All supplier access to port systems, including remote maintenance and "
        "administrative accounts, shall be protected by multi-factor "
        "authentication.",
        "Credential theft is the commonest route into a small organisation, and "
        "supplier accounts are frequently the ones exempted from the port's own "
        "MFA rollout.",
        "Configuration evidence or an attestation naming the mechanism; verify "
        "by attempting access.",
        Tier.ESSENTIAL, ("j", "i"), ("6.3", "6.4"), ("Q3",), ("S2", "S3", "S7"),
    ),
    Requirement(
        "R03", "Named, individually attributable accounts",
        "The supplier shall not use shared or generic accounts to access port "
        "systems. Each individual shall hold a named account, and the supplier "
        "shall notify the port when a holder leaves.",
        "Shared credentials destroy attribution. After an incident the first "
        "question is which account acted, and a shared login makes it "
        "unanswerable.",
        "Account list on request; leaver notifications in practice, not policy.",
        Tier.ESSENTIAL, ("i",), ("5.1", "6.2"), ("Q2",), ("S2", "S4"),
    ),
    Requirement(
        "R04", "Right to audit and to receive assessment results",
        "The port may assess the supplier's security controls, or require "
        "evidence of independent assessment, at reasonable intervals.",
        "Without an audit right the port's only information about a supplier is "
        "what the supplier chooses to say. NIS2 Article 21(2)(d) expects the "
        "relationship to be managed, not assumed.",
        "The clause, exercised at least once.",
        Tier.RECOMMENDED, ("d", "f"), ("15.5",), ("Q10",), (),
    ),
    Requirement(
        "R05", "Supplier assesses its own suppliers",
        "The supplier shall maintain a documented process for assessing the "
        "security of its own critical suppliers, and shall disclose material "
        "dependencies relevant to the services provided to the port.",
        "Supply chains are transitive. Kaseya's customers were compromised "
        "through a supplier they had never assessed, and MOVEit reached "
        "organisations that had never heard of it.",
        "Their supplier assessment policy, and a list of subprocessors.",
        Tier.RECOMMENDED, ("d",), ("15.1", "15.2"), ("Q11",), ("S1", "S6", "S7"),
    ),
    # ------------------------------------------------- software and updates
    Requirement(
        "R06", "Port-controlled update scheduling",
        "Software updates shall not be applied to production systems without "
        "the port's authorisation. The supplier shall provide release notes and "
        "a test package sufficiently in advance for validation.",
        "The SolarWinds vector: a signed update from a trusted vendor bypasses "
        "every perimeter control the port has, and automatic application removes "
        "the only remaining opportunity to notice.",
        "The update procedure in writing, and a staging environment that is "
        "actually used.",
        Tier.ESSENTIAL, ("e",), ("7.4", "16.1"), ("Q12",), ("S1",),
        asset_keys=("tos", "pcs", "ccs", "corporate_systems", "ics"),
    ),
    Requirement(
        "R07", "Software bill of materials on request",
        "The supplier shall provide a software bill of materials (SBOM) in a "
        "machine-readable format for each release, or on request.",
        "Turns 'are we exposed to this library?' from a week of telephone calls "
        "into a query. The question every port asked itself during xz-utils and "
        "Log4Shell, and most could not answer.",
        "An SBOM in CycloneDX or SPDX format for the current release.",
        Tier.ADVANCED, ("e", "d"), ("2.4", "16.4"), ("Q13",), ("S1", "S6"),
        asset_keys=("tos", "pcs", "ccs", "corporate_systems"),
    ),
    Requirement(
        "R08", "Vulnerability remediation timelines",
        "The supplier shall remediate vulnerabilities of critical severity, or "
        "any vulnerability listed in CISA's Known Exploited Vulnerabilities "
        "catalogue, within 30 days of a fix becoming available.",
        "Most exploitation happens well after a patch exists. A contractual "
        "window converts a vague expectation into something the port can hold "
        "the supplier to.",
        "Their disclosure policy and published remediation targets; check "
        "current CVEs against EPSS and KEV.",
        Tier.RECOMMENDED, ("e", "b"), ("7.3",), ("Q9", "Q14"), ("S6", "S4"),
    ),
    # ----------------------------------------------------------------- OT
    Requirement(
        "R09", "Brokered remote access for maintenance",
        "Remote maintenance shall be conducted through the port's monitored "
        "access broker. The supplier shall not connect unmanaged devices to "
        "operational networks.",
        "How OT compromise actually reaches a small port: an engineer's laptop, "
        "or a standing vendor tunnel nobody reviews.",
        "Access logs showing sessions routed through the broker, with no "
        "direct connections.",
        Tier.ESSENTIAL, ("i", "e"), ("12.7", "13.5"), ("Q1", "Q2"),
        ("S4",),
        asset_keys=("ics", "loading_unloading", "access_control", "detection",
                    "hinterland_devices", "temporary_storage"),
    ),
    Requirement(
        "R10", "Safety impact assessment for changes",
        "The supplier shall assess and document the safety implications of any "
        "change to equipment that controls physical processes, before applying "
        "it.",
        "Port OT moves cargo and people. A change that is merely inconvenient "
        "in an office is a crush hazard on a quay.",
        "Change records including a safety assessment.",
        Tier.ADVANCED, ("e", "c"), (), ("Q6",), ("S4",),
        asset_keys=("ics", "loading_unloading"),
    ),
    # -------------------------------------------------------------- data
    Requirement(
        "R11", "Encryption of port data in transit and at rest",
        "Port data shall be encrypted in transit and at rest, using current "
        "algorithms, and the supplier shall state where the data is stored.",
        "Crew and passenger data carries GDPR exposure; cargo data carries "
        "theft and trafficking risk, as Antwerp demonstrated.",
        "An architecture statement naming the mechanism and storage locations.",
        Tier.ESSENTIAL, ("h",), (), ("Q18",), ("S7",),
        asset_keys=("cloud", "mandatory_declarations", "operational_data",
                    "commercial_financial", "pcs", "ccs"),
    ),
    Requirement(
        "R12", "Data return and deletion on termination",
        "On termination the supplier shall return port data in a usable format "
        "and delete its copies, certifying deletion in writing.",
        "Substitutability is a security property. A supplier holding data it "
        "will not return is one the port cannot leave, and leverage lost at "
        "contract signature is not recovered later.",
        "The clause, plus an export tested before it is needed.",
        Tier.RECOMMENDED, ("d", "c"), (), ("Q19", "Q20"), ("S7",),
        asset_keys=("cloud", "pcs", "ccs", "corporate_systems",
                    "mandatory_declarations"),
    ),
    # ------------------------------------------------------- continuity
    Requirement(
        "R13", "Recovery time commitment",
        "The supplier shall state the recovery time it commits to for the "
        "service provided, and shall test that commitment at least annually.",
        "A recovery objective nobody has tested is an aspiration. The "
        "difference between Nagoya's two and a half days and a fortnight is "
        "mostly preparation.",
        "The stated objective, plus the most recent test result.",
        Tier.ESSENTIAL, ("c",), ("11.5",), ("Q4", "Q5"), ("S1", "S2"),
        asset_keys=("tos", "pcs", "ccs", "ics", "loading_unloading", "cloud",
                    "servers", "networks"),
    ),
    Requirement(
        "R14", "Escrow or operational independence",
        "For systems the port cannot operate without, the supplier shall place "
        "source code or operational documentation in escrow, or demonstrate "
        "that the port could run the system without it.",
        "Applies where replacement would take longer than the port could "
        "survive without the service. Rarely negotiable after signature.",
        "An escrow agreement, or a documented continuity arrangement.",
        Tier.ADVANCED, ("c", "d"), (), ("Q19", "Q20"), ("S2",),
        asset_keys=("tos", "pcs", "ccs", "ics"),
    ),
)


@dataclass(frozen=True)
class RequirementSet:
    """Requirements scoped to one supplier, with gaps against its answers."""

    vendor_key: str
    vendor_name: str
    requirements: tuple[Requirement, ...]
    #: Requirement ids the supplier's questionnaire answers indicate it fails.
    unmet: tuple[str, ...] = ()
    #: Requirement ids with no verifying answer -- unknown, not met.
    unverified: tuple[str, ...] = ()

    def by_tier(self, tier: Tier) -> list[Requirement]:
        return [r for r in self.requirements if r.tier == tier]

    @property
    def essential_gaps(self) -> list[Requirement]:
        """Unmet essential requirements: the list to raise before renewal."""
        return [r for r in self.requirements
                if r.id in self.unmet and r.tier == Tier.ESSENTIAL]

    def nis2_coverage(self) -> dict[str, list[str]]:
        coverage: dict[str, list[str]] = {}
        for requirement in self.requirements:
            for point in requirement.nis2:
                coverage.setdefault(point, []).append(requirement.id)
        return coverage


def requirements_for_assets(
    asset_keys: tuple[str, ...] | list[str],
    *,
    include_universal: bool = True,
) -> list[Requirement]:
    """Requirements applying to a supplier of these asset classes.

    A requirement with no `asset_keys` is universal -- it applies to anyone with
    access to port systems or data. Requirements naming asset classes apply only
    to suppliers of those classes, which is what stops the crane OEM being asked
    for an SBOM and the SaaS provider for a safety assessment.
    """
    supplied = set(asset_keys)
    selected = []
    for requirement in REQUIREMENTS:
        if not requirement.asset_keys:
            if include_universal:
                selected.append(requirement)
        elif supplied & set(requirement.asset_keys):
            selected.append(requirement)
    order = {Tier.ESSENTIAL: 0, Tier.RECOMMENDED: 1, Tier.ADVANCED: 2}
    return sorted(selected, key=lambda r: (order[r.tier], r.id))


def requirements_for_vendor(vendor, *, escalate_critical: bool = True) -> RequirementSet:
    """Requirements for one supplier, with gaps against its questionnaire answers.

    Parameters
    ----------
    escalate_critical
        Promote RECOMMENDED to ESSENTIAL where the supplier provides an asset of
        HIGH supply-chain relevance *and* the requirement bears on a scenario
        that actually targets one of the assets it supplies.

        The second condition matters. Promoting every recommended requirement
        for any critical supplier put nine of ten items in the essential tier,
        which defeats the tier's purpose: a list a port is willing to lose a
        supplier over has to be short enough to survive a procurement
        conversation, or the important clauses get traded away alongside the
        rest. Tying escalation to the risk model keeps it targeted.

    Gap detection uses answers the port already collected. An answer in the
    worst two options of a verifying question counts as unmet; a requirement
    with no verifying answer is reported as *unverified* rather than met,
    because not asking is not the same as passing.
    """
    applicable = requirements_for_assets(vendor.supplies)

    if escalate_critical:
        supplied = set(vendor.supplies)
        critical = any(
            (asset := find_asset(key)) and asset.supply_chain_relevance == Relevance.HIGH
            for key in supplied
        )
        # Scenarios that actually reach this supplier's assets.
        exposed = {
            template.id for template in SCENARIO_TEMPLATES
            if supplied & set(template.target_assets)
        }
        if critical and exposed:
            base_essential = sum(1 for r in applicable if r.tier == Tier.ESSENTIAL)
            budget = max(0, MAX_ESSENTIAL - base_essential)
            # Promote the most exposed first, so if the cap bites it drops the
            # least relevant rather than whatever happened to sort last.
            candidates = sorted(
                (r for r in applicable
                 if r.tier == Tier.RECOMMENDED and exposed & set(r.scenarios)),
                key=lambda r: (-len(exposed & set(r.scenarios)), r.id),
            )
            promoted = {r.id for r in candidates[:budget]}
            applicable = [
                Requirement(**{**r.__dict__, "tier": Tier.ESSENTIAL})
                if r.id in promoted else r
                for r in applicable
            ]

    unmet, unverified = [], []
    for requirement in applicable:
        answers = [vendor.answers[q] for q in requirement.verified_by
                   if q in vendor.answers]
        if not requirement.verified_by or not answers:
            unverified.append(requirement.id)
            continue
        # Option 0 is the worst case and 1 the next worst; anything in that
        # range indicates the requirement is not currently satisfied.
        if any(answer <= 1 for answer in answers):
            unmet.append(requirement.id)

    return RequirementSet(
        vendor_key=vendor.key,
        vendor_name=vendor.name,
        requirements=tuple(applicable),
        unmet=tuple(unmet),
        unverified=tuple(unverified),
    )


def as_clauses(requirement_set: RequirementSet, *, tier: Tier | None = None) -> str:
    """Render requirements as numbered clauses for a contract or RFP.

    A requirement that never reaches a contract is an opinion. This is the
    output a port actually sends to procurement.
    """
    selected = [r for r in requirement_set.requirements
                if tier is None or r.tier == tier]
    lines = [
        f"Security requirements — {requirement_set.vendor_name}",
        "=" * 72,
        "",
    ]
    for number, requirement in enumerate(selected, 1):
        lines.append(f"{number}. {requirement.title}  [{requirement.tier.value}]")
        lines.append(f"   {requirement.text}")
        lines.append(f"   Evidence: {requirement.evidence}")
        lines.append(f"   NIS2 Art. 21(2): {', '.join(requirement.nis2)}")
        if requirement.id in requirement_set.unmet:
            lines.append("   STATUS: not currently met — raise before renewal.")
        elif requirement.id in requirement_set.unverified:
            lines.append("   STATUS: unverified — no questionnaire evidence either way.")
        lines.append("")
    return "\n".join(lines)


def scenario_requirement_map() -> dict[str, list[str]]:
    """Which requirements bear on each risk scenario.

    Lets the report connect a euro figure to the contract clause that addresses
    it, which is the connection procurement conversations usually lack.
    """
    mapping: dict[str, list[str]] = {t.id: [] for t in SCENARIO_TEMPLATES}
    for requirement in REQUIREMENTS:
        for scenario_id in requirement.scenarios:
            mapping.setdefault(scenario_id, []).append(requirement.id)
    return mapping
