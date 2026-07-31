"""Supply-chain risk scenarios for a small port.

Each scenario is built from three independent frames so that nothing is
invented and every entry can be traced:

* **ENISA threat taxonomy** -- the domain skeleton (see `threats.py`).
* **MITRE ATT&CK** -- concrete technique identifiers, so the scenario names a
  real observed behaviour rather than a vibe, and so mitigations can later be
  mapped through ATT&CK's own control mappings.
* **STRIDE** -- used only as a completeness audit. If a letter never appears
  across the catalogue for a given asset class, something is missing. STRIDE is
  not the primary frame: it assumes a data-flow diagram of a system you own,
  which is precisely what you do not have for a third party.

Every scenario carries an `incident_anchor`: a real, documented event of the
same shape. Anchors are what keep the frequency and magnitude estimates from
being arbitrary, and they give the validation phase something to replay -- if
the model's P10-P90 band does not contain the real incident, the model is
wrong.

The default estimates below are deliberately *ranges*, sourced and wide. They
are starting priors for a 100-person mixed port, to be replaced by
questionnaire evidence and live signals (EPSS, KEV, OpenSSF) per vendor. Wide
honest ranges beat narrow invented ones: the sensitivity analysis will show
which of them actually deserve more research.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..risk.distributions import PERT
from ..risk.montecarlo import LossMagnitude, Scenario

__all__ = ["ScenarioTemplate", "SCENARIO_TEMPLATES", "build_scenarios", "stride_coverage"]


@dataclass(frozen=True)
class ScenarioTemplate:
    """Narrative and framework mappings for one scenario.

    Separated from the numeric `Scenario` so the catalogue can be read,
    reviewed and cited without touching the risk model, and so the same
    narrative can be instantiated with different numbers per port persona.
    """

    id: str
    name: str
    description: str
    enisa_threats: tuple[str, ...]
    attack_techniques: tuple[str, ...]
    stride: tuple[str, ...]
    enisa_impacts: tuple[str, ...]
    incident_anchor: str
    target_assets: tuple[str, ...]


SCENARIO_TEMPLATES: tuple[ScenarioTemplate, ...] = (
    ScenarioTemplate(
        id="S1",
        name="Trojanized update to terminal or port community software",
        description=(
            "An attacker compromises the build or update channel of the port's TOS or PCS "
            "vendor and ships signed malicious code to every customer. The port installs it "
            "through normal patching. Detection is slow because the software is trusted and "
            "the delivery path is legitimate."
        ),
        enisa_threats=("unreliable_source", "malware"),
        attack_techniques=("T1195.002", "T1071"),
        stride=("Tampering", "Elevation of Privilege"),
        enisa_impacts=("operations_shutdown", "data_theft", "systems_damage"),
        incident_anchor=(
            "SolarWinds Orion (2020): trojanized updates distributed to ~18,000 "
            "organisations; dwell time measured in months."
        ),
        target_assets=("tos", "pcs"),
    ),
    ScenarioTemplate(
        id="S2",
        name="Managed service provider compromise leading to ransomware",
        description=(
            "The port outsources IT to an MSP holding privileged remote access to servers "
            "and workstations. The MSP is compromised and its management tooling is used to "
            "push ransomware to every client simultaneously. For a small port with no "
            "in-house security function this is the single largest concentration of risk."
        ),
        enisa_threats=("provider_disruption", "malware", "unauthorised_access"),
        attack_techniques=("T1199", "T1486", "T1078"),
        stride=("Elevation of Privilege", "Denial of Service"),
        enisa_impacts=("operations_shutdown", "financial_loss", "systems_damage"),
        incident_anchor=(
            "Kaseya VSA (2021): MSP tooling used to reach ~1,500 downstream businesses. "
            "Port of Nagoya (2023): LockBit halted container operations ~2.5 days. "
            "DP World Australia (2023): ~3 days, ~30,000 containers stranded."
        ),
        target_assets=("workstations", "servers", "tos", "networks"),
    ),
    ScenarioTemplate(
        id="S3",
        name="SaaS account takeover leading to invoice fraud",
        description=(
            "Credentials for the port's cloud email or ERP tenant are phished or reused from "
            "a prior breach. The attacker monitors mail traffic, then redirects payment for a "
            "genuine invoice. Operations continue normally throughout, which is why this "
            "scenario is under-weighted by operations-focused risk assessments."
        ),
        enisa_threats=("identity_theft", "social_engineering", "interception_data"),
        attack_techniques=("T1078", "T1114", "T1566"),
        stride=("Spoofing", "Information Disclosure"),
        enisa_impacts=("fraud_theft", "data_theft", "reputation"),
        incident_anchor=(
            "Business email compromise against maritime agents and bunker suppliers; "
            "FBI IC3 reports BEC as the highest-loss category in absolute euro terms."
        ),
        target_assets=("cloud", "corporate_systems", "commercial_financial"),
    ),
    ScenarioTemplate(
        id="S4",
        name="OT and IoT compromise of gates, cranes or CCTV",
        description=(
            "Equipment supplied and remotely maintained by an OEM -- gate ANPR, crane "
            "controls, CCTV -- is reached through the vendor's maintenance channel or an "
            "unpatched device. Consequences run from data manipulation to physical safety "
            "risk, and this estate is typically the least patched in the port."
        ),
        enisa_threats=("vuln_exploitation", "unauthorised_access", "third_party_failure"),
        attack_techniques=("T0862", "T0886", "T1200"),
        stride=("Tampering", "Elevation of Privilege", "Repudiation"),
        enisa_impacts=("operations_shutdown", "cargo_theft", "trafficking", "human_harm"),
        incident_anchor=(
            "Port of Antwerp (2011-2013): attackers manipulated container release systems "
            "over two years to extract narcotics containers."
        ),
        target_assets=("ics", "loading_unloading", "detection", "access_control"),
    ),
    ScenarioTemplate(
        id="S5",
        name="AIS and GNSS spoofing or jamming",
        description=(
            "Navigation and traffic data reaching the port is falsified or denied. AIS is "
            "unauthenticated by design, so spoofed positions are accepted as genuine. The "
            "port's picture of what is arriving becomes unreliable, degrading berth planning "
            "and, at the extreme, creating collision or grounding risk."
        ),
        enisa_threats=("geo_spoofing", "interception_emissions"),
        attack_techniques=("T0856", "T0842"),
        stride=("Spoofing", "Tampering"),
        enisa_impacts=("operations_shutdown", "human_harm", "environmental"),
        incident_anchor=(
            "Sustained GNSS jamming and spoofing in the Baltic since 2023, widely reported "
            "by aviation and maritime authorities in the region."
        ),
        target_assets=("navigation_data", "traffic_monitoring", "radio"),
    ),
    ScenarioTemplate(
        id="S6",
        name="Compromised freeware or open-source dependency",
        description=(
            "Software obtained free of charge -- a utility, a library inside a supplied "
            "application -- carries a backdoor or an unpatched critical vulnerability. The "
            "brief names this case directly ('freeware?'), and it is the hardest to assess "
            "because there is no vendor to send a questionnaire to."
        ),
        enisa_threats=("unreliable_source", "vuln_exploitation"),
        attack_techniques=("T1195.001", "T1505"),
        stride=("Tampering", "Elevation of Privilege"),
        enisa_impacts=("data_theft", "systems_damage", "operations_shutdown"),
        incident_anchor=(
            "xz-utils backdoor, CVE-2024-3094 (2024): a multi-year social engineering "
            "campaign placed a backdoor in a core compression library, caught by accident."
        ),
        target_assets=("servers", "workstations", "corporate_systems"),
    ),
    ScenarioTemplate(
        id="S7",
        name="Vendor data breach exposing port data and credentials",
        description=(
            "A supplier holding port data -- crew and passenger lists, manifests, "
            "credentials -- is breached. The port's operations are untouched but its data is "
            "in the open, triggering NIS2 and GDPR obligations and giving attackers material "
            "for the next intrusion."
        ),
        enisa_threats=("interception_data", "third_party_failure"),
        attack_techniques=("T1190", "T1213"),
        stride=("Information Disclosure",),
        enisa_impacts=("data_theft", "reputation", "trafficking"),
        incident_anchor=(
            "MOVEit Transfer (2023): a single file-transfer product breached data at "
            "2,700+ organisations including logistics and government bodies."
        ),
        target_assets=("cloud", "mandatory_declarations", "operational_data"),
    ),
)


def build_scenarios(
    cost_per_hour: PERT,
    *,
    scale: float = 1.0,
) -> list[Scenario]:
    """Instantiate the catalogue with default priors for a 100-person mixed port.

    Parameters
    ----------
    cost_per_hour
        Euro cost of one hour of port service outage, derived from AIS traffic
        and published port accounts. Supplied by the caller because it is the
        one input that is genuinely port-specific.
    scale
        Multiplier on response and secondary costs for smaller personas. A
        10-person port has a smaller estate to rebuild and a lower regulatory
        ceiling than a 100-person one.

    Every frequency and duration below carries its provenance in the PERT
    `source` field. These are priors, not findings: the whole point of the
    vendor questionnaire and the live signal feeds is to replace them with
    evidence, and the tornado analysis will say which ones matter enough to
    bother.
    """
    def eur(lo, mode, hi, source):
        return PERT(lo * scale, mode * scale, hi * scale, source=source)

    templates = {t.id: t for t in SCENARIO_TEMPLATES}

    def make(sid, lef, hours, response, secondary, secondary_p, disruption_p=1.0):
        t = templates[sid]
        return Scenario(
            id=sid,
            name=t.name,
            loss_event_frequency=lef,
            loss_magnitude=LossMagnitude(
                downtime_hours=hours,
                cost_per_hour=cost_per_hour,
                response_cost=response,
                secondary_loss=secondary,
                secondary_probability=secondary_p,
                disruption_probability=disruption_p,
            ),
            enisa_threat=", ".join(t.enisa_threats),
            attack_techniques=t.attack_techniques,
            stride=t.stride,
            notes=t.incident_anchor,
        )

    return [
        make(
            "S1",
            PERT(0.005, 0.02, 0.08,
                 source="Rare but non-zero; SolarWinds/3CX class events affect a given "
                        "vendor's customer base roughly once per decade."),
            PERT(8, 48, 240,
                 source="Detection-to-recovery for trojanized software; long tail because "
                        "trust in the vendor delays detection."),
            eur(20_000, 80_000, 400_000, "IR retainer, forensics, rebuild of affected systems."),
            eur(10_000, 50_000, 250_000, "NIS2 penalty exposure and notification costs."),
            0.30,
            # Receiving a trojanized update is not the same as being operationally
            # disrupted by it: of the ~18,000 organisations that installed the
            # SolarWinds backdoor, only a small minority were actively exploited,
            # and the harm to those was mostly espionage rather than outage.
            disruption_p=0.50,
        ),
        make(
            "S2",
            PERT(0.02, 0.08, 0.25,
                 source="MSP-borne ransomware; small orgs without in-house security are "
                        "over-represented. Base rate informed by Verizon DBIR third-party "
                        "involvement trend (~30% of breaches)."),
            PERT(24, 60, 336,
                 source="Anchored on Nagoya (~60h to full restart) and DP World (~72h); "
                        "tail reflects Maersk-class rebuilds."),
            eur(30_000, 120_000, 600_000, "Recovery, overtime, hardware replacement, ransom advice."),
            eur(15_000, 60_000, 300_000, "Regulatory penalty, customer compensation, liner switching."),
            0.35,
            # Set from held-out incident replay, which caught the model asserting
            # that ransomware always stops the quay. Of six documented port
            # ransomware incidents, four disrupted operations (Nagoya, DP World,
            # COSCO, Transnet) and two did not (Barcelona and San Diego, both
            # 2018, where IT was hit while vessel operations continued). 4/6.
            disruption_p=0.67,
        ),
        make(
            "S3",
            PERT(0.10, 0.30, 0.80,
                 source="Credential-based SaaS compromise is the highest-frequency scenario "
                        "for small organisations; most attempts fail, some succeed."),
            PERT(0, 2, 12,
                 source="Operations largely unaffected; downtime is limited to account "
                        "lockout and mail migration."),
            eur(5_000, 20_000, 80_000, "Investigation, credential reset, mail security uplift."),
            eur(20_000, 90_000, 500_000, "Fraudulent payment losses; recovery of transferred funds is rare."),
            0.45,
        ),
        make(
            "S4",
            PERT(0.01, 0.05, 0.20,
                 source="OT/IoT compromise via vendor maintenance channel; lower frequency, "
                        "higher consequence, poor detection coverage."),
            PERT(4, 24, 120,
                 source="Gate/crane outage forces manual operation rather than full stoppage "
                        "in most cases; upper tail is a safety-driven shutdown."),
            eur(15_000, 60_000, 350_000, "OEM callout, device replacement, manual operations cost."),
            eur(10_000, 40_000, 400_000, "Cargo loss, investigation by authorities, safety findings."),
            0.25,
        ),
        make(
            "S5",
            PERT(0.05, 0.20, 0.60,
                 source="Baltic GNSS interference is persistent and regionally elevated; "
                        "most events degrade rather than stop operations."),
            PERT(1, 6, 48,
                 source="Berth planning disruption while falling back to manual "
                        "coordination and radar."),
            eur(2_000, 10_000, 60_000, "Manual coordination overhead, delay handling."),
            eur(5_000, 25_000, 200_000, "Delay penalties, incident investigation if a near-miss occurs."),
            0.15,
        ),
        make(
            "S6",
            PERT(0.02, 0.10, 0.35,
                 source="Dependency-borne compromise; frequency rises with unmanaged "
                        "freeware. Refine per port using OpenSSF Scorecard and EPSS."),
            PERT(2, 16, 96,
                 source="Depends entirely on where the component sits; wide by design "
                        "until the software inventory is known."),
            eur(8_000, 35_000, 200_000, "Investigation, dependency replacement, patching sprint."),
            eur(5_000, 25_000, 150_000, "Data exposure consequences."),
            0.20,
        ),
        make(
            "S7",
            PERT(0.05, 0.15, 0.45,
                 source="Vendor breaches disclosed to customers; MOVEit-class events show "
                        "one product can expose thousands of downstream organisations."),
            PERT(0, 1, 8,
                 source="Operations unaffected; downtime only from precautionary credential "
                        "rotation."),
            eur(5_000, 25_000, 120_000, "Notification, legal review, credential rotation."),
            eur(20_000, 80_000, 400_000, "GDPR and NIS2 exposure, reputational cost with liners."),
            0.50,
        ),
    ]


def stride_coverage() -> dict[str, list[str]]:
    """Which scenarios cover each STRIDE category.

    The completeness audit described in the module docstring. An empty list for
    a category is a prompt to ask what is missing -- not proof of a gap, since
    not every category applies to every port, but a question worth answering in
    writing.
    """
    categories = [
        "Spoofing", "Tampering", "Repudiation",
        "Information Disclosure", "Denial of Service", "Elevation of Privilege",
    ]
    coverage: dict[str, list[str]] = {c: [] for c in categories}
    for template in SCENARIO_TEMPLATES:
        for letter in template.stride:
            coverage.setdefault(letter, []).append(template.id)
    return coverage
