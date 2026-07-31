"""ENISA phase four: cybersecurity maturity self-assessment.

This project describes itself as operationalising ENISA's four-phase approach to
cyber risk management for ports. Phases one to three -- identify assets and
services, identify and evaluate risks, identify security measures -- are covered
by the taxonomy, the risk engine and the control optimiser. Phase four was
claimed and not implemented. This closes that.

The three levels are ENISA's, from *Cyber Risk Management for Ports* (December
2020), Table 2:

    1 Basic         minimum measures achieving a security objective; baseline
                    activities performed, possibly ad hoc
    2 Intermediate  sustained capabilities aligned to standards and best
                    practice; implemented, managed, monitored and measured,
                    with documentation guiding application
    3 Optimal       planned, tested, policy-informed and repeatable; subject to
                    regular oversight and review, with continuous improvement

Descriptions here are paraphrased; the report itself is in `refs/` and is the
authority. The measures below are a representative subset of ENISA's catalogue
across its three categories, not a transcription of it.

The point of connecting this to the rest of the system: **the optimiser's
portfolio implies a maturity profile**. Buying controls moves specific measures
to specific levels, so a port can see what its budget buys in ENISA's own terms
as well as in euro. ENISA is explicit that maturity is not a checklist -- so the
mapping deliberately caps what buying a control alone can achieve. Level 3
requires review, testing and continuous improvement, which is a way of working
rather than a purchase.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Level", "LEVEL_NAMES", "LEVEL_DESCRIPTIONS", "Category", "Measure",
           "MEASURES", "MaturityProfile", "assess_maturity",
           "maturity_from_controls", "find_measure"]

Level = int  # 0 = not implemented, 1 Basic, 2 Intermediate, 3 Optimal

LEVEL_NAMES = {0: "Not implemented", 1: "Basic", 2: "Intermediate", 3: "Optimal"}

LEVEL_DESCRIPTIONS = {
    0: "No evidence the measure is in place.",
    1: "Minimum measures achieving the objective; baseline activities performed, "
       "possibly in an ad hoc manner.",
    2: "Sustained capability aligned to identified standards and best practice; "
       "implemented, managed, monitored and measured, with documentation "
       "guiding how resources are applied.",
    3: "Planned, tested, policy-informed and repeatable; subject to regular "
       "oversight and review to confirm effectiveness, with continuous "
       "improvement against defined performance objectives.",
}


class Category(str):
    """ENISA groups its measures into three categories."""


POLICIES = "policies"
ORGANISATIONAL = "organisational"
TECHNICAL = "technical"

CATEGORY_NAMES = {
    POLICIES: "Policies",
    ORGANISATIONAL: "Organisational practices",
    TECHNICAL: "Technical measures",
}


@dataclass(frozen=True)
class Measure:
    """One ENISA security measure, with what each level looks like."""

    code: str
    category: str
    name: str
    #: What evidence distinguishes each level, paraphrased from ENISA's tables.
    evidence: dict[int, str]
    #: Controls from our catalogue that contribute, and the highest level each
    #: can carry the measure to on its own.
    control_ceiling: dict[str, int]
    #: Whether this measure bears on supply-chain risk specifically. ENISA's
    #: catalogue is broader than this project's scope, and pretending to assess
    #: measures the DSS knows nothing about would inflate the result.
    supply_chain: bool = False


MEASURES: tuple[Measure, ...] = (
    # ------------------------------------------------------------ policies
    Measure(
        "PS-01", POLICIES, "Information systems security policy (ISSP)",
        {
            1: "One or more security policies drafted, covering IT and OT.",
            2: "Policies formally codified and approved by top management, "
               "tailored to the port's own IT/OT environment.",
            3: "Policies reviewed regularly, exercised in drills, and shared "
               "with stakeholders across the port.",
        },
        {"C20": 1},
    ),
    Measure(
        "PS-05", POLICIES, "Risk-based approach and continuous improvement",
        {
            1: "A facility security assessment exists and includes cyber risk.",
            2: "Cyber risk management practices documented and communicated; "
               "risks evaluated for regulatory impact.",
            3: "Risk assessment repeated on a defined cycle, feeding a "
               "continuous improvement process.",
        },
        {"C18": 1, "C10": 2},
        supply_chain=True,
    ),
    Measure(
        "PS-09", POLICIES, "Asset inventory and management policy",
        {
            1: "An inventory of cyber-related assets exists.",
            2: "Assets registered against the systems and services they "
               "support, and maintained as they change.",
            3: "Inventory reconciled automatically and reviewed on a cycle.",
        },
        {"C10": 2},
    ),
    Measure(
        "PS-12", POLICIES, "Business continuity and crisis management",
        {
            1: "Continuity arrangements documented for critical services.",
            2: "Plans maintained, with defined recovery objectives.",
            3: "Plans exercised regularly, with results feeding revision.",
        },
        {"C04": 1, "C05": 2, "C20": 2},
    ),
    # --------------------------------------------- organisational practices
    Measure(
        "OP-03", ORGANISATIONAL, "Vulnerability management",
        {
            1: "Vulnerabilities identified and addressed when noticed.",
            2: "Scanning and remediation on a defined cycle, prioritised and "
               "tracked to closure.",
            3: "Prioritisation informed by exploitation intelligence, with "
               "measured remediation performance.",
        },
        {"C08": 2, "C09": 3},
        supply_chain=True,
    ),
    Measure(
        "OP-06", ORGANISATIONAL, "Supply chain management",
        {
            1: "Suppliers identified and their access recorded.",
            2: "Suppliers assessed against defined criteria, with security "
               "requirements in contracts.",
            3: "Supplier risk reassessed on a cycle, with the assessment "
               "informing procurement decisions.",
        },
        {"C18": 1, "C17": 2, "C11": 2},
        supply_chain=True,
    ),
    Measure(
        "OP-08", ORGANISATIONAL, "Detection and incident response",
        {
            1: "Incidents can be detected and someone is responsible for them.",
            2: "Documented response plan with defined roles; monitoring in "
               "place.",
            3: "Plan exercised, response measured, and lessons applied.",
        },
        {"C06": 1, "C16": 2, "C20": 3},
    ),
    Measure(
        "OP-10", ORGANISATIONAL, "Human resource security and awareness",
        {
            1: "Staff receive basic security awareness.",
            2: "Role-relevant training delivered and recorded, including for "
               "management.",
            3: "Training informed by the organisation's own risk profile, with "
               "effectiveness measured.",
        },
        {"C15": 2},
    ),
    # ---------------------------------------------------- technical measures
    Measure(
        "TM-02", TECHNICAL, "Access control",
        {
            1: "Access is restricted and accounts are individually held.",
            2: "Multi-factor authentication enforced; privileged access "
               "controlled and logged.",
            3: "Access granted just in time and reviewed on a cycle.",
        },
        {"C01": 2, "C02": 2, "C03": 3},
        supply_chain=True,
    ),
    Measure(
        "TM-04", TECHNICAL, "Network security and segmentation",
        {
            1: "Perimeter controls in place.",
            2: "IT and OT separated, with controlled crossings.",
            3: "Segmentation monitored and tested, with supplier access "
               "brokered.",
        },
        {"C07": 2, "C19": 3},
        supply_chain=True,
    ),
    Measure(
        "TM-08", TECHNICAL, "Update management",
        {
            1: "Updates applied when supplied.",
            2: "Updates validated before production, with defined timelines.",
            3: "Update provenance verified and staged, with rollback tested.",
        },
        {"C08": 1, "C12": 3},
        supply_chain=True,
    ),
    Measure(
        "TM-11", TECHNICAL, "Backup and restore",
        {
            1: "Backups taken.",
            2: "Backups held offline or immutably, and restoration verified.",
            3: "Restoration exercised to a measured recovery time.",
        },
        {"C04": 2, "C05": 3},
    ),
)


def find_measure(code: str) -> Measure | None:
    return next((m for m in MEASURES if m.code == code), None)


@dataclass(frozen=True)
class MaturityProfile:
    """Assessed maturity across ENISA's measures."""

    levels: dict[str, int]

    @property
    def overall(self) -> float:
        return sum(self.levels.values()) / len(self.levels) if self.levels else 0.0

    def by_category(self) -> dict[str, float]:
        grouped: dict[str, list[int]] = {}
        for code, level in self.levels.items():
            measure = find_measure(code)
            if measure:
                grouped.setdefault(measure.category, []).append(level)
        return {k: sum(v) / len(v) for k, v in grouped.items()}

    def supply_chain_score(self) -> float:
        """Maturity across the measures that bear on supplier risk.

        Reported separately because this is the DSS's actual scope. A port can
        be mature overall and weak precisely where its suppliers reach it.
        """
        relevant = [self.levels[m.code] for m in MEASURES
                    if m.supply_chain and m.code in self.levels]
        return sum(relevant) / len(relevant) if relevant else 0.0

    def gaps(self, target: int = 2) -> list[tuple[Measure, int]]:
        """Measures below a target level, worst first."""
        below = [(find_measure(code), level) for code, level in self.levels.items()
                 if level < target]
        return sorted([(m, l) for m, l in below if m], key=lambda kv: kv[1])

    def describe(self) -> str:
        lines = [f"Overall maturity {self.overall:.2f} of 3 "
                 f"({LEVEL_NAMES[round(self.overall)]})"]
        for category, score in sorted(self.by_category().items()):
            lines.append(f"  {CATEGORY_NAMES.get(category, category):28s} {score:.2f}")
        lines.append(f"  {'supply-chain measures only':28s} "
                     f"{self.supply_chain_score():.2f}")
        return "\n".join(lines)


def assess_maturity(levels: dict[str, int]) -> MaturityProfile:
    """Build a profile from directly assessed levels.

    Measures not mentioned are recorded as level 0. Omitting them would let a
    port raise its score by assessing only what it does well.
    """
    unknown = set(levels) - {m.code for m in MEASURES}
    if unknown:
        raise ValueError(f"unknown measure codes: {sorted(unknown)}")
    for code, level in levels.items():
        if level not in (0, 1, 2, 3):
            raise ValueError(f"{code}: level {level} outside 0-3")
    return MaturityProfile({m.code: levels.get(m.code, 0) for m in MEASURES})


def maturity_from_controls(control_ids: list[str] | tuple[str, ...]) -> MaturityProfile:
    """Maturity implied by a set of implemented controls.

    Each control carries its measures to a ceiling; the level reached is the
    highest ceiling among the controls implemented. Ceilings are deliberately
    conservative, and most controls cap at 1 or 2.

    ENISA is explicit that maturity cannot be achieved through a checklist
    mentality, and this mapping respects that: level 3 requires oversight,
    testing and continuous improvement, which buying a control does not confer.
    Treat the result as the maturity a portfolio *makes possible*, and the
    directly assessed profile as what the port has actually achieved.
    """
    implemented = set(control_ids)
    levels = {}
    for measure in MEASURES:
        reached = [ceiling for control, ceiling in measure.control_ceiling.items()
                   if control in implemented]
        levels[measure.code] = max(reached) if reached else 0
    return MaturityProfile(levels)
