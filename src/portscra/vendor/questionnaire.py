"""Vendor security questionnaire, mapped to NIS2 Article 21.

Small ports do not have the leverage to send a 300-question Shared Assessments
SIG to their crane OEM and expect an answer. This questionnaire is deliberately
short enough that a supplier will actually complete it, while covering the
measure areas Article 21(2) names -- so a port that runs it is simultaneously
producing evidence of the supply-chain diligence the directive requires.

Every question maps to at least one Article 21(2) point, and the mapping is
carried in the data so the app can show a NIS2 coverage view rather than
asserting compliance.

The seven criteria are the things that actually move a vendor's risk for a
port, rather than the things a generic questionnaire asks about:

* **access** -- what the vendor can reach in our estate, which is what turns
  their breach into ours (the Kaseya and MSP path)
* **asset_criticality** -- what stops if they stop
* **posture** -- their own security maturity
* **update_channel** -- integrity of how their code reaches us (SolarWinds)
* **incident_history** -- track record and, more tellingly, transparency
* **data_exposure** -- what of ours they hold (MOVEit)
* **substitutability** -- how fast we could replace them
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Criterion", "Question", "CRITERIA", "QUESTIONS", "DEFAULT_WEIGHTS",
           "questions_for", "nis2_coverage"]


@dataclass(frozen=True)
class Criterion:
    key: str
    name: str
    description: str
    #: Why this drives risk for a port specifically, not organisations in general.
    port_rationale: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "access", "Access and privilege",
        "Level of access the vendor holds into port systems and networks.",
        "The single largest concentration of risk for a port with no in-house IT: "
        "an MSP with domain admin turns one supplier breach into a total outage.",
    ),
    Criterion(
        "asset_criticality", "Criticality of the supplied asset",
        "How central the supplied system is to port operations.",
        "A compromised TOS stops cargo moving; a compromised HR portal does not. "
        "Weighting these equally is the classic error of generic TPRM tools.",
    ),
    Criterion(
        "posture", "Vendor security posture",
        "The vendor's own security maturity: certification, testing, disclosure.",
        "The only criterion a questionnaire can address directly, and the one "
        "most prone to flattering self-report -- hence the external signals.",
    ),
    Criterion(
        "update_channel", "Update and maintenance channel integrity",
        "How code and configuration changes reach port systems.",
        "The SolarWinds vector. Signed updates from a trusted vendor bypass "
        "every perimeter control the port has.",
    ),
    Criterion(
        "incident_history", "Incident history and transparency",
        "Past breaches and, more informatively, how they were disclosed.",
        "A vendor that disclosed promptly is a better bet than one with no "
        "public incidents and no disclosure policy.",
    ),
    Criterion(
        "data_exposure", "Port data held by the vendor",
        "Volume and sensitivity of port data in the vendor's custody.",
        "Crew and passenger manifests carry GDPR exposure; cargo data carries "
        "theft and trafficking risk, as Antwerp showed.",
    ),
    Criterion(
        "substitutability", "Substitutability",
        "How quickly the port could switch to an alternative supplier.",
        "Determines whether a vendor failure is an inconvenience or an "
        "existential dependency. Small ports are usually locked in.",
    ),
)


@dataclass(frozen=True)
class Question:
    id: str
    criterion: str
    text: str
    #: Answer options, worst-first. Index 0 scores 1.0 (highest risk), the last
    #: option scores 0.0. Ordering them worst-first makes the scoring direction
    #: obvious when reading the catalogue.
    options: tuple[str, ...]
    #: NIS2 Article 21(2) points this question provides evidence for.
    nis2: tuple[str, ...]
    #: Relative weight within its criterion.
    weight: float = 1.0

    def score(self, answer_index: int) -> float:
        """Risk score in [0, 1], where 1 is worst. Raises on an invalid index."""
        if not 0 <= answer_index < len(self.options):
            raise ValueError(
                f"{self.id}: answer index {answer_index} outside 0..{len(self.options) - 1}"
            )
        if len(self.options) == 1:
            return 0.0
        return 1.0 - answer_index / (len(self.options) - 1)


QUESTIONS: tuple[Question, ...] = (
    # --- access ---
    Question(
        "Q1", "access",
        "What level of access does the vendor hold to port systems?",
        ("Standing administrative or domain-level remote access",
         "Standing remote access, limited privileges",
         "On-request remote access, approved per session",
         "No remote access; on-site attendance only"),
        ("d", "i"), weight=1.5,
    ),
    Question(
        "Q2", "access",
        "Is vendor access individually attributable and logged?",
        ("Shared account, no logging",
         "Shared account, logged",
         "Named accounts, logged",
         "Named accounts, logged, with session recording and review"),
        ("i", "f"),
    ),
    Question(
        "Q3", "access",
        "Is multi-factor authentication enforced on all vendor access paths?",
        ("No MFA", "MFA on some paths", "MFA everywhere",
         "MFA everywhere plus network-level restriction"),
        ("j",), weight=1.2,
    ),
    # --- asset_criticality ---
    Question(
        "Q4", "asset_criticality",
        "If this vendor's system were unavailable, what happens to port operations?",
        ("Operations stop entirely",
         "Operations continue manually at reduced capacity",
         "Minor administrative disruption only",
         "No operational effect"),
        ("c",), weight=1.5,
    ),
    Question(
        "Q5", "asset_criticality",
        "How long could the port operate without this system before material loss?",
        ("Under 4 hours", "4-24 hours", "1-7 days", "More than a week"),
        ("c",),
    ),
    Question(
        "Q6", "asset_criticality",
        "Does the system touch OT or safety-related functions?",
        ("Yes, controls physical equipment or safety systems",
         "Yes, monitors physical equipment",
         "Interfaces with OT but does not control it",
         "IT only"),
        ("e",), weight=1.3,
    ),
    # --- posture ---
    Question(
        "Q7", "posture",
        "Does the vendor hold a recognised security certification?",
        ("None", "Self-attestation only", "ISO 27001 or SOC 2 in progress",
         "ISO 27001, SOC 2 or IEC 62443 certified and current"),
        ("a", "f"),
    ),
    Question(
        "Q8", "posture",
        "Does the vendor conduct independent penetration testing?",
        ("Never or unknown", "Ad hoc", "Annually", "Annually, with results shared"),
        ("f", "e"),
    ),
    Question(
        "Q9", "posture",
        "Does the vendor operate a vulnerability disclosure process?",
        ("None", "Informal contact only", "Published policy",
         "Published policy with defined remediation timelines"),
        ("e", "b"),
    ),
    Question(
        "Q10", "posture",
        "Does the vendor's contract include security obligations and audit rights?",
        ("No security terms", "Generic confidentiality only",
         "Security requirements stated", "Security requirements plus audit and breach-notification terms"),
        ("d",), weight=1.2,
    ),
    Question(
        "Q11", "posture",
        "Does the vendor assess its own suppliers?",
        ("Unknown", "No formal process", "Assesses critical suppliers",
         "Assesses all suppliers with documented criteria"),
        ("d",),
    ),
    # --- update_channel ---
    Question(
        "Q12", "update_channel",
        "How are software updates delivered and validated?",
        ("Automatic push, no validation by the port",
         "Automatic push, port notified",
         "Port-initiated, tested in advance",
         "Port-initiated, tested, with signature and integrity verification"),
        ("e", "d"), weight=1.5,
    ),
    Question(
        "Q13", "update_channel",
        "Does the vendor provide a software bill of materials (SBOM)?",
        ("No", "On request, informally", "Yes, on request",
         "Yes, published with each release"),
        ("e",),
    ),
    Question(
        "Q14", "update_channel",
        "How quickly does the vendor patch critical vulnerabilities?",
        ("No commitment or unknown", "Best effort", "Within 30 days", "Within 7 days, contractually"),
        ("e", "b"), weight=1.2,
    ),
    # --- incident_history ---
    Question(
        "Q15", "incident_history",
        "Has the vendor experienced a publicly known security incident?",
        ("Yes, and disclosure was late or incomplete",
         "Yes, within the last 3 years",
         "Yes, more than 3 years ago, well handled",
         "No known incidents"),
        ("b",),
    ),
    Question(
        "Q16", "incident_history",
        "Is the vendor contractually required to notify the port of incidents?",
        ("No requirement", "Informal expectation", "Contractual, no deadline",
         "Contractual, within 24 hours"),
        ("b", "d"), weight=1.3,
    ),
    # --- data_exposure ---
    Question(
        "Q17", "data_exposure",
        "What port data does the vendor hold or process?",
        ("Personal data (crew, passengers) plus operational data",
         "Operational and commercial data",
         "Limited operational data",
         "No port data"),
        ("h", "i"), weight=1.2,
    ),
    Question(
        "Q18", "data_exposure",
        "Is port data encrypted at rest and in transit by the vendor?",
        ("Neither or unknown", "In transit only", "Both, vendor-managed keys",
         "Both, with port-controlled keys"),
        ("h",),
    ),
    # --- substitutability ---
    Question(
        "Q19", "substitutability",
        "How long would replacing this vendor take?",
        ("More than a year, or no viable alternative",
         "6-12 months", "1-6 months", "Under a month"),
        ("c", "d"), weight=1.3,
    ),
    Question(
        "Q20", "substitutability",
        "Could the port operate this system if the vendor ceased trading?",
        ("No, entirely vendor-dependent",
         "Partially, with significant degradation",
         "Yes, with escrowed source or documentation",
         "Yes, the port operates it independently"),
        ("c",),
    ),
)


#: Literature-derived starting weights for users who skip the pairwise exercise.
#: Access dominates because the supply-chain incidents that actually harmed
#: small organisations -- Kaseya above all -- ran through vendor access rather
#: than through vendor software defects.
DEFAULT_WEIGHTS: dict[str, float] = {
    "access": 0.24,
    "asset_criticality": 0.21,
    "update_channel": 0.17,
    "posture": 0.14,
    "substitutability": 0.10,
    "data_exposure": 0.08,
    "incident_history": 0.06,
}


def questions_for(criterion: str) -> tuple[Question, ...]:
    return tuple(q for q in QUESTIONS if q.criterion == criterion)


def nis2_coverage() -> dict[str, list[str]]:
    """Which questions provide evidence for each NIS2 Article 21(2) point.

    Lets the app show a port where its supply-chain diligence is thin in the
    directive's own terms, which is more actionable than a single score and is
    what a supervisory authority would ask about.
    """
    points = {
        "a": "risk analysis and information system security policies",
        "b": "incident handling",
        "c": "business continuity and crisis management",
        "d": "supply chain security",
        "e": "security in acquisition, development and maintenance",
        "f": "policies to assess effectiveness of risk management measures",
        "g": "basic cyber hygiene and security training",
        "h": "cryptography and encryption",
        "i": "human resources security, access control, asset management",
        "j": "multi-factor authentication and secured communications",
    }
    coverage: dict[str, list[str]] = {f"21(2)({k}) {v}": [] for k, v in points.items()}
    lookup = {k: f"21(2)({k}) {v}" for k, v in points.items()}
    for question in QUESTIONS:
        for point in question.nis2:
            if point in lookup:
                coverage[lookup[point]].append(question.id)
    return coverage
