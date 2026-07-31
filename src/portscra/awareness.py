"""Awareness assessment, driven by the port's own top risks.

The brief asks for a "Cyber-Security awareness tool" and, more precisely, to
"identify cyber-security awareness level for specific vendor-related risks".
The second phrasing is the important one: not awareness in general, but
awareness *of the risks this port actually faces*.

So this module does not ship a fixed quiz. It selects vignettes for the
scenarios the risk engine ranked highest for this port, which means a port
whose largest exposure is invoice fraud gets finance vignettes rather than
generic ransomware content it will never need.

Three things make it part of the DSS rather than a bolt-on:

**It is generated from the model's output.** Change the supplier list and the
top risks change, so the training changes with them.

**The result feeds back into the model.** Measured awareness modulates the
frequency of the human-factor scenarios. A port whose finance staff reliably
spot a payment-redirection attempt genuinely suffers fewer of them, and the
risk figures should say so. This closes the loop: assess, train, re-assess,
and watch the expected loss move.

**It is scoped by role.** NIS2 Article 20(2) obliges management bodies
themselves to follow training, and Article 21(2)(g) requires basic cyber
hygiene practices and training across the organisation. Reporting a single
organisational percentage would hide the case the directive cares about most --
a board that has not done it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Role", "Option", "Vignette", "VIGNETTES", "AwarenessResult",
           "vignettes_for", "score_responses", "awareness_multiplier",
           "HUMAN_FACTOR_WEIGHT"]


class Role(str):
    """Who a vignette is aimed at. Plain strings so results serialise cleanly."""


MANAGEMENT = "management"
FINANCE = "finance"
OPERATIONS = "operations"
IT = "it"

ROLE_NAMES = {
    MANAGEMENT: "Management body (NIS2 Art. 20 duty holders)",
    FINANCE: "Finance and administration",
    OPERATIONS: "Port operations and gate staff",
    IT: "IT and OT staff",
}

#: How much of each scenario's frequency is plausibly under human control.
#: Invoice fraud turns almost entirely on whether someone notices; a trojanized
#: vendor update does not care how alert the staff are. Awareness training that
#: claimed to reduce every risk equally would be selling something.
HUMAN_FACTOR_WEIGHT: dict[str, float] = {
    "S3": 0.60,  # phishing and payment redirection -- overwhelmingly human
    "S2": 0.25,  # initial access often phished, but the MSP path is not
    "S7": 0.15,  # credential reuse after a vendor breach
    "S6": 0.10,  # someone still has to install the dependency
    "S4": 0.10,  # physical and procedural discipline around OT access
    "S5": 0.10,  # recognising implausible navigation data
    "S1": 0.05,  # a signed update from a trusted vendor defeats vigilance
}


@dataclass(frozen=True)
class Option:
    text: str
    correct: bool = False
    #: Shown after answering. The explanation is the training; the score is
    #: only the measurement.
    feedback: str = ""


@dataclass(frozen=True)
class Vignette:
    """One situation, with the plausible responses to it."""

    id: str
    scenario_id: str
    role: str
    situation: str
    question: str
    options: tuple[Option, ...]
    #: NIS2 Article 21(2) points this exercises.
    nis2: tuple[str, ...] = ()
    anchor: str = ""

    @property
    def correct_index(self) -> int:
        for i, option in enumerate(self.options):
            if option.correct:
                return i
        raise ValueError(f"{self.id} has no correct option")

    def is_correct(self, index: int) -> bool:
        if not 0 <= index < len(self.options):
            raise ValueError(
                f"{self.id}: answer {index} outside 0..{len(self.options) - 1}")
        return self.options[index].correct


VIGNETTES: tuple[Vignette, ...] = (
    # ---------------------------------------------------------------- S3
    Vignette(
        "V1", "S3", FINANCE,
        "A supplier you pay monthly emails to say their bank has changed. The "
        "message comes from the usual address, quotes a real outstanding "
        "invoice number, and the signature block is correct.",
        "What do you do before paying?",
        (
            Option("Update the bank details on file and pay as normal -- the correct "
                   "invoice number and matching signature block establish that "
                   "the request is genuine.",
                   feedback="An attacker reading the mailbox knows the invoice "
                            "numbers. Everything that looks confirming here is "
                            "available to someone already inside the thread."),
            Option("Reply to the email asking them to confirm the change.",
                   feedback="If the mailbox is compromised, the attacker answers "
                            "your confirmation. Verification has to leave the "
                            "channel that might be controlled."),
            Option("Telephone the supplier on the number you already held for "
                   "them -- not one from the email -- and confirm before paying.",
                   correct=True,
                   feedback="Out-of-band verification against a previously known "
                            "contact. This is control C14 in the catalogue: about "
                            "EUR 1,500 a year, and the highest-leverage control "
                            "available against the port's top-ranked scenario."),
            Option("Pay a small test amount first, then the balance.",
                   feedback="Confirms the account accepts money, which was never "
                            "in doubt. It does not confirm whose account it is."),
        ),
        nis2=("g", "d"),
        anchor="Business email compromise is consistently the highest-loss "
               "category by absolute euro value in FBI IC3 reporting.",
    ),
    Vignette(
        "V2", "S3", MANAGEMENT,
        "Finance asks for authority to pay an unusually large invoice today, "
        "because the supplier has warned of a late-payment penalty.",
        "Which part of this should concern you most?",
        (
            Option("The size of the invoice, which is larger than this supplier "
                   "normally submits and therefore out of pattern.",
                   feedback="Large invoices are normal. Size alone is not the signal."),
            Option("The time pressure.", correct=True,
                   feedback="Manufactured urgency is the common thread in payment "
                            "fraud: it exists to stop the verification step from "
                            "happening. A genuine supplier will wait for a phone call."),
            Option("That finance escalated for authority instead of processing the "
                   "payment under their own delegated limit.",
                   feedback="That is the control working as intended."),
            Option("Nothing in particular -- late-payment penalties are a real "
                   "contractual risk and paying promptly avoids them.",
                   feedback="They are, which is exactly why the pressure is "
                            "convincing enough to be worth faking."),
        ),
        nis2=("g",),
    ),
    # ---------------------------------------------------------------- S2
    Vignette(
        "V3", "S2", IT,
        "Your outsourced IT provider asks you to approve a new remote-access "
        "account for a technician starting today, so they can work over the "
        "weekend without waiting for Monday's approval cycle.",
        "What is the right response?",
        (
            Option("Approve it -- they hold administrative access already, so "
                   "one more account changes nothing.",
                   feedback="It changes attribution. When something goes wrong, "
                            "the question is which account did it, and a hastily "
                            "added one is the hardest to answer for."),
            Option("Approve it, but only for the weekend, and confirm the request "
                   "with your named contact at the provider by phone.",
                   correct=True,
                   feedback="Time-bounded and verified out of band. The Kaseya "
                            "pattern is a compromised provider's own tooling being "
                            "used against its clients, so a request that arrives "
                            "through the provider's channel is not self-verifying."),
            Option("Refuse the request outright and tell the provider it will be "
                   "considered through the normal approval cycle on Monday.",
                   feedback="Defensible, but a blanket refusal that blocks "
                            "legitimate work tends to be routed around next time. "
                            "A verified, time-bounded grant survives contact with "
                            "operational reality."),
            Option("Ask them to share an existing technician's login instead.",
                   feedback="Shared credentials destroy attribution entirely -- "
                            "the worst available option."),
        ),
        nis2=("i", "d", "j"),
        anchor="Kaseya VSA (2021): MSP tooling used to reach ~1,500 downstream "
               "businesses.",
    ),
    Vignette(
        "V4", "S2", MANAGEMENT,
        "Ransomware has encrypted the terminal operating system. The provider "
        "estimates two days to restore. A ransom demand offers same-day recovery.",
        "What most determines how long this outage actually lasts?",
        (
            Option("Whether the ransom is paid, since the attacker is offering "
                   "same-day recovery against a two-day rebuild.",
                   feedback="Paying does not reliably shorten recovery: decryption "
                            "is slow, partial, and you still rebuild to be sure the "
                            "attacker is gone."),
            Option("Whether backups exist and have been restored from before.",
                   correct=True,
                   feedback="Nagoya restarted in about two and a half days because "
                            "recovery was possible. Most of the difference between "
                            "a two-day and a two-week outage is preparation and "
                            "decision latency, not technology."),
            Option("How quickly the attacker is identified and the intrusion route "
                   "established by the forensic investigation.",
                   feedback="Attribution matters for the investigation, not for "
                            "getting cargo moving."),
            Option("Whether the incident is reported to the authorities.",
                   feedback="NIS2 Article 23 requires it within 24 hours, and it "
                            "is not optional -- but reporting does not restore "
                            "operations."),
        ),
        nis2=("c", "b"),
        anchor="Port of Nagoya (2023): container operations restarted after "
               "roughly two and a half days.",
    ),
    # ---------------------------------------------------------------- S4
    Vignette(
        "V5", "S4", OPERATIONS,
        "A crane maintenance engineer arrives on site and asks for the wifi "
        "password so they can connect a laptop to the crane controller.",
        "What should happen?",
        (
            Option("Give them the operational network password -- they are here "
                   "to fix our equipment.",
                   feedback="An unmanaged laptop on the OT network is exactly the "
                            "path this scenario models, and you cannot know where "
                            "else that laptop has been."),
            Option("Route the session through the monitored jump host used for "
                   "supplier maintenance, and record it.", correct=True,
                   feedback="Control C19 in the catalogue. Legitimate work "
                            "proceeds, the session is attributable, and the OT "
                            "network is never exposed to an unmanaged device."),
            Option("Give them the guest wireless network, which is separated from "
                   "the operational systems and carries no port traffic.",
                   feedback="Well intentioned, but the crane controller is not on "
                            "guest wifi, so this simply does not do the job and the "
                            "engineer will ask again."),
            Option("Let them connect their laptop directly to the crane controller "
                   "by cable, avoiding the wireless network altogether.",
                   feedback="Bypasses every network control the port has."),
        ),
        nis2=("i", "e"),
        anchor="Port of Antwerp (2011-2013): attackers manipulated container "
               "release systems over two years.",
    ),
    # ---------------------------------------------------------------- S6
    Vignette(
        "V6", "S6", IT,
        "A free utility would save your team hours each week. It is widely used "
        "and actively maintained on GitHub.",
        "What is the most useful thing to check before installing it?",
        (
            Option("The number of stars and contributors on the repository, as a "
                   "measure of how widely the project is trusted in practice.",
                   feedback="Popularity is not hygiene. The xz-utils backdoor was "
                            "placed in a component almost every Linux system runs."),
            Option("Whether an antivirus scan of the downloaded package flags "
                   "anything before it is installed on a port workstation.",
                   feedback="A deliberately planted backdoor in a legitimate "
                            "project will not be flagged."),
            Option("Its maintenance and review practices -- who can merge, "
                   "whether releases are signed, whether the project is "
                   "maintained by more than one person.", correct=True,
                   feedback="This is what OpenSSF Scorecard measures, and it is "
                            "the class of question the xz-utils compromise turned "
                            "on: a single maintainer under social pressure to hand "
                            "over commit rights."),
            Option("That the licence permits commercial use.",
                   feedback="A real question, but a legal one rather than a "
                            "security one."),
        ),
        nis2=("e", "a"),
        anchor="xz-utils backdoor, CVE-2024-3094 (2024), caught by accident "
               "before exploitation.",
    ),
    # ---------------------------------------------------------------- S7
    Vignette(
        "V7", "S7", MANAGEMENT,
        "A supplier notifies you that they were breached and that data they held "
        "for you may be affected.",
        "What is the port's first obligation?",
        (
            Option("Wait for the supplier to complete its investigation and issue a "
                   "full report, so the port acts on confirmed facts.",
                   feedback="The NIS2 clock does not pause for a supplier's "
                            "investigation."),
            Option("Assess whether this is a significant incident for the port "
                   "and, if so, submit an early warning within 24 hours.",
                   correct=True,
                   feedback="NIS2 Article 23 requires an early warning within 24 "
                            "hours and a fuller notification within 72. The "
                            "assessment is the port's to make, not the supplier's."),
            Option("Terminate the contract immediately, on the grounds that the "
                   "supplier has failed its security obligations to the port.",
                   feedback="May follow eventually, but it is not an obligation "
                            "and it does not address the exposure already created."),
            Option("Nothing -- it was their breach, not ours.",
                   feedback="The data was the port's responsibility. That is what "
                            "supply-chain security under Article 21(2)(d) means."),
        ),
        nis2=("b", "d"),
        anchor="MOVEit Transfer (2023): one file-transfer product exposed data at "
               "2,700+ organisations.",
    ),
    # ---------------------------------------------------------------- S5
    Vignette(
        "V8", "S5", OPERATIONS,
        "A vessel's AIS position places it alongside a berth, but the berth is "
        "visibly empty and the agent says the ship is still six hours out.",
        "How should this be treated?",
        (
            Option("Trust the AIS position, since it is the standard source the port "
                   "and the vessel traffic service both work from.",
                   feedback="AIS is unauthenticated by design. A position report "
                            "is a claim, not a measurement."),
            Option("Treat the AIS data as unreliable, confirm by radar and voice, "
                   "and report the discrepancy.", correct=True,
                   feedback="Baltic GNSS interference has been sustained and "
                            "widely reported since 2023. The correct response is "
                            "to fall back to independent sources and flag it."),
            Option("Assume the agent has the wrong information, since schedules "
                   "change and AIS is transmitted by the vessel itself.",
                   feedback="Possible, but the point of the exercise is not to "
                            "guess -- it is to reconcile against a second source."),
            Option("Ignore the discrepancy, since AIS reception glitches near the "
                   "quay are common and usually resolve on their own.",
                   feedback="Common, yes, and each one should still be reconciled "
                            "rather than dismissed."),
        ),
        nis2=("b",),
        anchor="Sustained GNSS jamming and spoofing in the Baltic since 2023.",
    ),
    # ---------------------------------------------------------------- S1
    Vignette(
        "V9", "S1", IT,
        "Your terminal operating system vendor pushes a signed update. It "
        "installs automatically overnight, as configured.",
        "What is the risk this configuration creates?",
        (
            Option("None of consequence -- the update carries a valid signature from "
                   "the vendor, which is what signing exists to establish.",
                   feedback="A signature proves the vendor built it. SolarWinds "
                            "was signed too: the attacker was inside the build "
                            "pipeline, so the signature was genuine."),
            Option("If the vendor's build pipeline is compromised, the malicious "
                   "code arrives trusted and reaches production before anyone "
                   "looks at it.", correct=True,
                   feedback="Control C12 -- staged testing before production -- "
                            "is the direct answer. It does not prevent the "
                            "compromise; it removes the automatic path from the "
                            "vendor's pipeline into live operations."),
            Option("The update might be incompatible with the port's hardware.",
                   feedback="A real operational risk, but not a security one."),
            Option("Overnight updates could interrupt night ferry operations.",
                   feedback="Worth planning around, but not the supply-chain "
                            "exposure being asked about."),
        ),
        nis2=("e",),
        anchor="SolarWinds Orion (2020): trojanized updates distributed to "
               "~18,000 organisations under a valid signature.",
    ),
)


def vignettes_for(
    scenario_ids: list[str] | tuple[str, ...],
    *,
    role: str | None = None,
    limit: int | None = None,
) -> list[Vignette]:
    """Vignettes for the given scenarios, in the order the scenarios were given.

    Callers pass scenario ids ranked by expected loss, so the training leads
    with what actually threatens this port. That ordering is the whole point:
    a generic course would open with whatever the vendor filmed first.
    """
    ordered: list[Vignette] = []
    for scenario_id in scenario_ids:
        for vignette in VIGNETTES:
            if vignette.scenario_id != scenario_id:
                continue
            if role and vignette.role != role:
                continue
            ordered.append(vignette)
    return ordered[:limit] if limit else ordered


@dataclass(frozen=True)
class AwarenessResult:
    """Measured awareness, broken down where the breakdown matters."""

    per_scenario: dict[str, float]
    per_role: dict[str, float]
    answered: int
    correct: int
    missed: tuple[str, ...] = ()

    @property
    def overall(self) -> float:
        return self.correct / self.answered if self.answered else 0.0

    def weakest_scenarios(self, n: int = 3) -> list[tuple[str, float]]:
        return sorted(self.per_scenario.items(), key=lambda kv: kv[1])[:n]

    def management_gap(self) -> float | None:
        """How far management trails the rest of the organisation.

        Surfaced separately because NIS2 Article 20(2) obliges the management
        body itself to undergo training. An organisational average can look
        healthy while the people carrying the legal duty are the weakest group.
        """
        if MANAGEMENT not in self.per_role:
            return None
        others = [v for k, v in self.per_role.items() if k != MANAGEMENT]
        if not others:
            return None
        return sum(others) / len(others) - self.per_role[MANAGEMENT]


def score_responses(responses: dict[str, int]) -> AwarenessResult:
    """Score answers, keyed by vignette id.

    Unanswered vignettes are excluded rather than counted wrong: this measures
    awareness among those assessed, and treating an absent respondent as
    ignorant would conflate coverage with competence. Report the count answered
    alongside the score.
    """
    by_id = {v.id: v for v in VIGNETTES}
    unknown = set(responses) - set(by_id)
    if unknown:
        raise ValueError(f"unknown vignette ids: {sorted(unknown)}")

    scenario_tally: dict[str, list[bool]] = {}
    role_tally: dict[str, list[bool]] = {}
    missed: list[str] = []
    correct = 0

    for vignette_id, answer in responses.items():
        vignette = by_id[vignette_id]
        right = vignette.is_correct(answer)
        correct += right
        if not right:
            missed.append(vignette_id)
        scenario_tally.setdefault(vignette.scenario_id, []).append(right)
        role_tally.setdefault(vignette.role, []).append(right)

    return AwarenessResult(
        per_scenario={k: sum(v) / len(v) for k, v in scenario_tally.items()},
        per_role={k: sum(v) / len(v) for k, v in role_tally.items()},
        answered=len(responses),
        correct=correct,
        missed=tuple(missed),
    )


def awareness_multiplier(
    result: AwarenessResult, scenario_id: str, *, default: float = 0.5
) -> float:
    """Factor to apply to a scenario's frequency, given measured awareness.

    Scaled by how much of the scenario is plausibly under human control, so
    training moves invoice fraud a long way and a trojanized signed update
    barely at all. A multiplier that improved every risk equally would be
    selling training rather than measuring it.

    Scored at 0.5 the multiplier is 1.0 -- average awareness leaves the
    frequency where the base rate put it, since the base rate already reflects
    organisations of average awareness. Unassessed scenarios use `default`,
    which is that same neutral point: not assessing is not an improvement.
    """
    weight = HUMAN_FACTOR_WEIGHT.get(scenario_id, 0.0)
    score = result.per_scenario.get(scenario_id, default)
    return 1.0 + weight * (1.0 - 2.0 * score)


def apply_awareness(scenarios, result: AwarenessResult):
    """Re-frequency a scenario list using measured awareness.

    Returns new Scenario objects; the inputs are untouched. This is what makes
    the module part of the decision system rather than an appendix -- train the
    staff, re-run the assessment, and the expected loss and the recommended
    portfolio both move.
    """
    import dataclasses

    adjusted = []
    for scenario in scenarios:
        factor = awareness_multiplier(result, scenario.id)
        adjusted.append(dataclasses.replace(
            scenario,
            loss_event_frequency=scenario.loss_event_frequency.scale(factor),
        ))
    return adjusted
