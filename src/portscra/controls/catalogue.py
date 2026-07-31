"""Mitigation catalogue: CIS Controls v8 safeguards, costed for a small port.

Scope discipline matters here. CIS Controls v8 has 153 safeguards; Implementation
Group 1 alone has 56. A 34-person port will not implement 56 safeguards, and a
catalogue that pretends otherwise produces an optimiser answer nobody acts on.
So this catalogue holds ~20 *implementable projects* -- each one a thing a port
could actually put in a budget line -- rather than individual safeguards.

Each entry carries:

* the CIS safeguards it delivers, so the mapping to a recognised framework is
  explicit rather than asserted;
* the NIS2 Article 21(2) points it evidences, because for this user the
  regulatory argument is often what unlocks the budget;
* an annualised cost for a port of Rønne's size, including the labour to run it
  rather than just the licence;
* per-scenario effects, split into frequency reduction (the control stops the
  event happening) and magnitude reduction (the event still happens but costs
  less). Conflating those two is the most common modelling error in security
  economics -- backups do not stop ransomware, they make it survivable.

Costs and effectiveness are estimates. They are the weakest inputs in the whole
model, which is exactly why the optimiser ships with sensitivity analysis: the
question that matters is not "is 40% the right number" but "would a different
plausible number change which controls I buy".
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["ControlEffect", "Control", "CATALOGUE", "find_control",
           "catalogue_for_group", "total_cost"]


@dataclass(frozen=True)
class ControlEffect:
    """How much a control reduces one scenario's frequency and magnitude.

    Both are proportions in [0, 1]. A frequency reduction of 0.6 means the
    control prevents 60% of the events that would otherwise occur; a magnitude
    reduction of 0.5 means the events that still occur cost half as much.
    """

    frequency_reduction: float = 0.0
    magnitude_reduction: float = 0.0
    rationale: str = ""

    def __post_init__(self) -> None:
        for name, value in (("frequency_reduction", self.frequency_reduction),
                            ("magnitude_reduction", self.magnitude_reduction)):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")


@dataclass(frozen=True)
class Control:
    id: str
    name: str
    description: str
    #: Annualised cost in EUR for a ~35-FTE port, including operating labour.
    annual_cost_eur: float
    #: CIS Controls v8 safeguard numbers delivered.
    cis_safeguards: tuple[str, ...]
    #: NIS2 Article 21(2) points evidenced.
    nis2: tuple[str, ...]
    #: CIS Implementation Group. IG1 is "essential cyber hygiene" and is the
    #: right default target for a port this size.
    implementation_group: int
    #: scenario id -> effect.
    effects: dict[str, ControlEffect] = field(default_factory=dict)
    #: True where the control is a prerequisite for others to work at all.
    foundational: bool = False

    def __post_init__(self) -> None:
        if self.annual_cost_eur < 0:
            raise ValueError(f"{self.id}: cost must not be negative")
        if self.implementation_group not in (1, 2, 3):
            raise ValueError(f"{self.id}: implementation group must be 1, 2 or 3")

    def __hash__(self) -> int:
        # The dataclass is frozen, so it would otherwise derive a hash from every
        # field -- including `effects`, which is a dict and unhashable. Controls
        # are identified by id everywhere else, so hash on that. Consistent with
        # the generated __eq__: equal controls necessarily share an id.
        return hash(self.id)


def _e(freq: float = 0.0, mag: float = 0.0, why: str = "") -> ControlEffect:
    return ControlEffect(freq, mag, why)


CATALOGUE: tuple[Control, ...] = (
    Control(
        "C01", "Multi-factor authentication on all accounts",
        "MFA for staff, administrators and every vendor access path, including "
        "remote maintenance.",
        annual_cost_eur=3_000,
        cis_safeguards=("6.3", "6.4", "6.5"),
        nis2=("j", "i"),
        implementation_group=1,
        effects={
            "S3": _e(freq=0.75, why="Credential theft stops being sufficient for "
                                    "account takeover. The single highest-value "
                                    "control against this scenario."),
            "S2": _e(freq=0.25, why="Raises the bar on the MSP's own access path, "
                                    "though not if the MSP itself is compromised."),
            "S7": _e(freq=0.15, why="Limits the usefulness of credentials exposed "
                                    "in a vendor breach."),
        },
    ),
    Control(
        "C02", "Named vendor accounts with session logging",
        "Replace shared vendor logins with individually attributable accounts; "
        "log and periodically review sessions.",
        annual_cost_eur=4_000,
        cis_safeguards=("5.1", "5.4", "8.5"),
        nis2=("i", "d", "f"),
        implementation_group=1,
        effects={
            "S2": _e(freq=0.20, mag=0.30, why="Attribution shortens the time to "
                                              "identify which vendor path was used."),
            "S4": _e(freq=0.15, mag=0.25, why="Applies equally to OEM remote "
                                              "maintenance sessions."),
        },
    ),
    Control(
        "C03", "Just-in-time privileged access for vendors",
        "Vendor access granted per approved session and revoked automatically, "
        "replacing standing administrative access.",
        annual_cost_eur=12_000,
        cis_safeguards=("5.4", "6.8", "12.7"),
        nis2=("i", "d"),
        implementation_group=2,
        effects={
            "S2": _e(freq=0.55, mag=0.35, why="Directly addresses the Kaseya shape: "
                                              "a compromised MSP cannot reach the "
                                              "estate outside an approved window."),
            "S4": _e(freq=0.35, why="Same mechanism for OT maintenance access."),
        },
    ),
    Control(
        "C04", "Offline and immutable backups",
        "Backups held offline or immutably, outside the domain the attacker "
        "would compromise.",
        annual_cost_eur=8_000,
        cis_safeguards=("11.1", "11.2", "11.3", "11.4"),
        nis2=("c",),
        implementation_group=1,
        effects={
            "S2": _e(mag=0.55, why="Does not prevent ransomware; makes it "
                                   "survivable without paying or rebuilding blind."),
            "S1": _e(mag=0.35, why="Enables rollback to a pre-compromise state."),
            "S6": _e(mag=0.30, why="Same rollback path for a poisoned dependency."),
        },
    ),
    Control(
        "C05", "Tested recovery procedures",
        "Documented restoration runbooks, exercised at least annually with "
        "measured recovery times.",
        annual_cost_eur=6_000,
        cis_safeguards=("11.5",),
        nis2=("c", "f"),
        implementation_group=1,
        effects={
            "S2": _e(mag=0.35, why="The difference between Nagoya's two-and-a-half "
                                   "days and a week of improvisation."),
            "S1": _e(mag=0.25),
            "S4": _e(mag=0.20),
        },
    ),
    Control(
        "C06", "Endpoint detection and response",
        "EDR on servers and workstations with alerting to a named responder.",
        annual_cost_eur=9_000,
        cis_safeguards=("10.1", "10.6", "10.7", "13.7"),
        nis2=("b", "g"),
        implementation_group=2,
        effects={
            "S2": _e(freq=0.30, mag=0.30, why="Catches deployment before it "
                                              "completes across the estate."),
            "S1": _e(freq=0.25, mag=0.30, why="Behavioural detection is the only "
                                              "defence once a signed update is trusted."),
            "S6": _e(freq=0.30, mag=0.25),
        },
    ),
    Control(
        "C07", "IT/OT network segmentation",
        "Separate the operational network from corporate IT, with controlled "
        "and monitored crossings.",
        annual_cost_eur=25_000,
        cis_safeguards=("12.2", "12.4", "4.4"),
        nis2=("e", "c"),
        implementation_group=2,
        effects={
            "S4": _e(freq=0.45, mag=0.50, why="Stops an IT compromise reaching "
                                              "cranes and gates, and vice versa."),
            "S2": _e(mag=0.40, why="Ransomware in the office does not stop the "
                                   "quay if the networks are genuinely separate."),
        },
    ),
    Control(
        "C08", "Patch management with defined SLAs",
        "Critical patches applied within a contractual window, tracked and "
        "reported.",
        annual_cost_eur=7_000,
        cis_safeguards=("7.3", "7.4"),
        nis2=("e",),
        implementation_group=1,
        effects={
            "S6": _e(freq=0.50, why="Most dependency compromises are exploited "
                                    "well after a fix exists."),
            "S4": _e(freq=0.30, why="The OT estate is where unpatched devices "
                                    "accumulate."),
            "S7": _e(freq=0.15),
        },
    ),
    Control(
        "C09", "Vulnerability scanning with EPSS prioritisation",
        "Regular scanning, with remediation ordered by exploitation probability "
        "rather than CVSS severity alone.",
        annual_cost_eur=5_000,
        cis_safeguards=("7.1", "7.5", "7.6", "7.7"),
        nis2=("e", "f"),
        implementation_group=2,
        effects={
            "S6": _e(freq=0.35, why="EPSS puts the few genuinely dangerous CVEs "
                                    "ahead of the many merely severe ones."),
            "S4": _e(freq=0.20),
        },
    ),
    Control(
        "C10", "Asset and software inventory",
        "Maintained inventory of hardware, software and their owners.",
        annual_cost_eur=4_000,
        cis_safeguards=("1.1", "1.2", "2.1", "2.3"),
        nis2=("a", "i"),
        implementation_group=1,
        foundational=True,
        effects={
            "S6": _e(freq=0.25, mag=0.25, why="You cannot patch or assess what you "
                                              "do not know you run. ENISA lists "
                                              "asset inventory as a phase-one activity."),
            "S1": _e(mag=0.20),
        },
    ),
    Control(
        "C11", "SBOM ingestion for supplied software",
        "Require and process a software bill of materials from suppliers, "
        "matched against vulnerability feeds.",
        annual_cost_eur=3_000,
        cis_safeguards=("2.4", "16.4"),
        nis2=("e", "d"),
        implementation_group=3,
        effects={
            "S6": _e(freq=0.30, mag=0.35, why="Turns 'are we affected by this "
                                              "library?' from a week of phone calls "
                                              "into a query. The xz-utils question."),
            "S1": _e(mag=0.20),
        },
    ),
    Control(
        "C12", "Staged testing of vendor updates",
        "Updates applied to a test environment and validated before reaching "
        "production systems.",
        annual_cost_eur=6_000,
        cis_safeguards=("7.4", "16.1"),
        nis2=("e",),
        implementation_group=2,
        effects={
            "S1": _e(freq=0.40, mag=0.30, why="The direct answer to the SolarWinds "
                                              "vector: a trusted update stops being "
                                              "applied automatically everywhere."),
        },
    ),
    Control(
        "C13", "Email authentication and anti-phishing",
        "SPF, DKIM and DMARC enforced, with inbound impersonation protection.",
        annual_cost_eur=4_000,
        cis_safeguards=("9.2", "9.6", "9.7"),
        nis2=("g", "j"),
        implementation_group=1,
        effects={
            "S3": _e(freq=0.40, why="Blocks the impersonation half of invoice "
                                    "fraud, though not a genuinely compromised "
                                    "mailbox."),
        },
    ),
    Control(
        "C14", "Out-of-band verification of payment changes",
        "Any change to supplier bank details verified by telephone to a "
        "previously known number, with dual authorisation above a threshold.",
        annual_cost_eur=1_500,
        cis_safeguards=("14.2",),
        nis2=("g", "d"),
        implementation_group=1,
        effects={
            "S3": _e(mag=0.75, why="The fraud attempt still happens; the payment "
                                   "does not. Procedural, nearly free, and the "
                                   "highest-leverage control in the catalogue "
                                   "against the top-ranked scenario."),
        },
    ),
    Control(
        "C15", "Security awareness training",
        "Role-relevant training, refreshed annually, including the port's own "
        "top scenarios rather than generic content.",
        annual_cost_eur=3_500,
        cis_safeguards=("14.1", "14.3", "14.6"),
        nis2=("g",),
        implementation_group=1,
        effects={
            "S3": _e(freq=0.25, why="Reduces successful phishing, with well-"
                                    "documented diminishing returns."),
            "S2": _e(freq=0.10),
            "S6": _e(freq=0.05),
        },
    ),
    Control(
        "C16", "Managed detection and response",
        "Outsourced 24/7 monitoring and triage -- the realistic option for a "
        "port that cannot staff a security operations centre.",
        annual_cost_eur=18_000,
        cis_safeguards=("8.1", "8.2", "8.11", "17.3"),
        nis2=("b", "f"),
        implementation_group=2,
        effects={
            "S2": _e(freq=0.25, mag=0.45, why="Detection at 03:00 on a Sunday is "
                                              "precisely what a 34-person port "
                                              "cannot otherwise provide."),
            "S1": _e(freq=0.20, mag=0.40),
            "S4": _e(mag=0.30),
            "S6": _e(freq=0.15, mag=0.30),
        },
    ),
    Control(
        "C17", "Security requirements in vendor contracts",
        "Contractual security obligations, breach notification within 24 hours, "
        "and audit rights.",
        annual_cost_eur=2_500,
        cis_safeguards=("15.4", "15.5"),
        nis2=("d", "b"),
        implementation_group=1,
        effects={
            "S7": _e(freq=0.15, mag=0.40, why="Does not prevent a vendor breach; "
                                              "materially shortens how long the "
                                              "port stays ignorant of it."),
            "S1": _e(freq=0.10, mag=0.20),
            "S2": _e(mag=0.15),
        },
    ),
    Control(
        "C18", "Vendor inventory and criticality tiering",
        "Maintained register of suppliers, what they access, and what stops if "
        "they fail.",
        annual_cost_eur=2_000,
        cis_safeguards=("15.1", "15.2", "15.3"),
        nis2=("d", "a"),
        implementation_group=1,
        foundational=True,
        effects={
            "S1": _e(mag=0.15, why="Knowing which systems a compromised vendor "
                                   "touches is the first question asked in an "
                                   "incident, and the slowest to answer without "
                                   "a register."),
            "S2": _e(mag=0.20),
            "S7": _e(freq=0.10, mag=0.25),
        },
    ),
    Control(
        "C19", "Brokered remote access for OT suppliers",
        "OEM maintenance sessions routed through a monitored jump host with "
        "recording, replacing direct connections to equipment.",
        annual_cost_eur=14_000,
        cis_safeguards=("12.7", "13.5", "6.8"),
        nis2=("i", "e"),
        implementation_group=2,
        effects={
            "S4": _e(freq=0.50, mag=0.40, why="The single control that addresses "
                                              "how OT compromise actually reaches "
                                              "a small port's equipment."),
        },
    ),
    Control(
        "C20", "Incident response plan with exercises",
        "Documented plan naming roles and decisions, exercised annually, "
        "including NIS2 24/72-hour reporting obligations.",
        annual_cost_eur=5_000,
        cis_safeguards=("17.1", "17.2", "17.4", "17.6"),
        nis2=("b", "c", "f"),
        implementation_group=1,
        effects={
            "S1": _e(mag=0.25),
            "S2": _e(mag=0.30, why="Most of the difference between a two-day and "
                                   "a two-week outage is decision latency, not "
                                   "technology."),
            "S3": _e(mag=0.15),
            "S4": _e(mag=0.20),
            "S5": _e(mag=0.25),
            "S6": _e(mag=0.20),
            "S7": _e(mag=0.30, why="Reporting deadlines are met or missed here."),
        },
    ),
)


def find_control(control_id: str) -> Control | None:
    return next((c for c in CATALOGUE if c.id == control_id), None)


def catalogue_for_group(max_group: int = 1) -> tuple[Control, ...]:
    """Controls at or below a CIS implementation group.

    IG1 is CIS's "essential cyber hygiene" baseline and the honest starting
    point for a 34-person port; IG2 adds controls that assume someone whose job
    includes security.
    """
    return tuple(c for c in CATALOGUE if c.implementation_group <= max_group)


def total_cost(controls) -> float:
    return sum(c.annual_cost_eur for c in controls)
