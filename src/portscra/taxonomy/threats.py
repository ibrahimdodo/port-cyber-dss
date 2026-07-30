"""Port threat taxonomy and impact catalogue, from ENISA.

Source: ENISA, "Port Cybersecurity" (November 2019), section 4.1 -- Figure 6
"Threat taxonomy" and Table 4 "Threat description" for the threats, Table 3
"Possible impacts for ports" for the impacts.

The impact catalogue is doing real work in this project, not decoration. It is
the bridge between a technical scenario and the euro figure the assignment asks
for: each scenario declares which ENISA impacts it produces, and the loss model
only prices impacts the scenario can actually cause. That stops the common
failure of quantitative risk work where every scenario mysteriously costs about
the same because the analyst reached for the same spreadsheet each time.

Note ENISA's own framing of operational shutdown, which is why an island port
is the sharper case study: the harm is worse "especially for the islands (food,
fuel, etc.)" where there is no road alternative.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["ThreatCategory", "Threat", "Impact", "THREAT_TAXONOMY", "IMPACTS",
           "SUPPLY_CHAIN_THREATS", "find_threat", "find_impact"]


@dataclass(frozen=True)
class Threat:
    key: str
    name: str
    description: str
    #: True where the threat can be realised *through a supplier* rather than
    #: by direct attack on the port. This flag is what narrows ENISA's general
    #: taxonomy to the supply-chain question this DSS answers.
    supply_chain_vector: bool = False


@dataclass(frozen=True)
class ThreatCategory:
    key: str
    name: str
    threats: tuple[Threat, ...]


@dataclass(frozen=True)
class Impact:
    key: str
    name: str
    description: str
    #: Which loss component this impact feeds in the Monte Carlo model.
    #: One of: "outage", "response", "secondary", "non_financial".
    loss_component: str


THREAT_TAXONOMY: tuple[ThreatCategory, ...] = (
    ThreatCategory(
        "eavesdropping",
        "Eavesdropping, interception, hijacking",
        (
            Threat("interception_emissions", "Interception of emissions",
                   "Interception of communication between the port and stakeholders "
                   "(radio, ship-to-port exchanges)."),
            Threat("interception_data", "Interception of sensitive data",
                   "Listening to communications or scanning systems to intercept sensitive "
                   "data for corporate or state espionage, or for criminal use.",
                   supply_chain_vector=True),
            Threat("mitm", "Man-in-the-middle, session hijacking",
                   "Relaying and possibly altering communication between two parties who "
                   "believe they are talking directly; or exploiting vulnerabilities to gain "
                   "a client's access rights.",
                   supply_chain_vector=True),
            Threat("recon", "Network reconnaissance and traffic manipulation",
                   "Passive scanning to find an entry point revealing internal port network "
                   "information, then using it to compromise target systems."),
        ),
    ),
    ThreatCategory(
        "nefarious_activity",
        "Nefarious activity and abuse",
        (
            Threat("dos", "Denial of service",
                   "Attacks against GPS, network, applications or IoT causing system "
                   "unavailability and production disruption, often distributed."),
            Threat("malware", "Malware",
                   "Malicious software causing unauthorised actions and damage to IT/OT "
                   "systems, infrastructure, data integrity and operations. Includes "
                   "ransomware, viruses, trojans, spyware and web application attacks.",
                   supply_chain_vector=True),
            Threat("brute_force", "Brute force",
                   "Repeated attempts to guess keys or passwords to gain unauthorised access, "
                   "especially where default or simple passwords are permitted."),
            Threat("identity_theft", "Identity theft",
                   "Deliberate use of the identity of someone in the port ecosystem, for "
                   "example through stolen credentials, for financial gain or access. "
                   "Includes 'fake president' fraud.",
                   supply_chain_vector=True),
            Threat("social_engineering", "Social engineering, phishing",
                   "Human interaction used to obtain or compromise information about port "
                   "organisation and processes, often by impersonation across several sources.",
                   supply_chain_vector=True),
            Threat("geo_spoofing", "Geo-localisation signal spoofing/jamming",
                   "Manipulation of geo-localisation and navigation systems to change a "
                   "vessel's trajectory or provoke accidents. ENISA notes GPS spoofing and "
                   "AIS tampering as demonstrated and important in the maritime context."),
        ),
    ),
    ThreatCategory(
        "physical_attacks",
        "Physical attacks",
        (
            Threat("fraud", "Fraud",
                   "Intentional deception violating civil law, for example VAT fraud through "
                   "falsified customs declarations."),
            Threat("sabotage", "Sabotage",
                   "Deliberate action to deteriorate or destroy port systems and "
                   "infrastructure, external or internal."),
            Threat("vandalism", "Vandalism",
                   "Voluntary destruction or deterioration of port assets without specific "
                   "motive."),
            Threat("theft", "Theft",
                   "Theft of mobile devices, fixed hardware, backups, printed documents or "
                   "freight."),
            Threat("unauthorised_access", "Unauthorised access",
                   "Bypassing access control to enter port areas, ships, vehicles or OT "
                   "end-devices such as cranes.",
                   supply_chain_vector=True),
            Threat("terrorism", "Terrorism",
                   "Intentional violence, generally against civilians, for political, "
                   "ideological or religious purposes."),
            Threat("hacktivism", "Hacktivism",
                   "Use of technology to promote a political agenda or social change."),
            Threat("coercion", "Coercion, extortion or corruption",
                   "Violence or threats to obtain something, or dishonest behaviour targeting "
                   "powerful people in the port ecosystem."),
            Threat("organised_crime", "Piracy, illegal crime, mafia",
                   "Illegal organisations breaking the law to maintain power and activities "
                   "such as drug trafficking and cargo theft."),
        ),
    ),
    ThreatCategory(
        "unintentional_damage",
        "Unintentional damage",
        (
            Threat("unreliable_source", "Use of unreliable source",
                   "Use of an unreliable source for port systems -- a defective update or "
                   "malicious software -- causing malfunction or spread. ENISA names NotPetya "
                   "as the exemplar. This is the supply-chain attack in ENISA's own words.",
                   supply_chain_vector=True),
            Threat("erroneous_admin", "Erroneous administration of IT/OT systems",
                   "Insufficiently trained administrators making errors that strongly impact "
                   "port systems and, where critical, port operations."),
            Threat("pentest_damage", "Resulting from penetration testing",
                   "Security testing that damages systems if not carried out properly."),
            Threat("data_deletion", "Data deletion",
                   "Unintended destruction of data."),
            Threat("vuln_exploitation", "Vulnerabilities exploitation of systems or devices",
                   "Exploitation of unpatched or unmonitored vulnerabilities in systems and "
                   "devices.",
                   supply_chain_vector=True),
            Threat("third_party_failure", "Failures/malfunctions of other stakeholders' systems",
                   "Malfunction or failure of other actors' navigation, communication and "
                   "other systems, slowing or stopping port operations; and those systems "
                   "serving as an entry point into port systems when linked.",
                   supply_chain_vector=True),
            Threat("supply_systems", "Main supply systems",
                   "Dependence on supply systems such as electricity and fuel, whose failure "
                   "slows or stops port operations."),
            Threat("provider_disruption", "Failure or disruption of service providers",
                   "The port depends on many service providers, some critical; their failure "
                   "or disruption strongly impacts port operations.",
                   supply_chain_vector=True),
        ),
    ),
    ThreatCategory(
        "outages",
        "Outages",
        (
            Threat("supply_outage", "Main supply outages",
                   "Outages on main supply: fuelling shutdown blocking ships, electricity "
                   "outage affecting IT and OT systems and refrigerated storage."),
            Threat("network_outage", "Network outage",
                   "Failures in port networks, essential for operations and communication "
                   "between actors.",
                   supply_chain_vector=True),
            Threat("absence_personnel", "Absence of personnel",
                   "Incidents occurring when port employees are not present, significant as "
                   "port processes become more automated."),
        ),
    ),
    ThreatCategory(
        "disaster",
        "Disaster",
        (
            Threat("environmental_disaster", "Environmental disaster",
                   "Fires, pollution, dust, corrosion and explosions causing physical damage "
                   "to port assets."),
            Threat("natural_disaster", "Natural disaster",
                   "Floods, lightning, powerful waves, storms, heavy winds and rain damaging "
                   "port assets."),
        ),
    ),
)


IMPACTS: tuple[Impact, ...] = (
    Impact("operations_shutdown", "Shutdown of operations, port paralysis",
           "The most feared impact. Beyond a few hours it harms commercial operations, "
           "delays delivery of essential goods -- ENISA notes this is worse for islands, "
           "where food and fuel have no road alternative -- and creates safety issues as "
           "vessels queue at the port entrance.",
           "outage"),
    Impact("human_harm", "Human injuries or death, kidnapping",
           "Ports carry high safety exposure: dangerous work such as crane operation and "
           "handling of dangerous goods, plus large and predictable passenger flows.",
           "non_financial"),
    Impact("data_theft", "Sensitive and critical data theft",
           "Theft of personal data (crew, passengers), critical commercial data (container "
           "location and content) or national security information.",
           "secondary"),
    Impact("cargo_theft", "Cargo and goods stealing",
           "Attackers browsing cargo and container lists to identify valuable goods for "
           "black markets or future piracy.",
           "secondary"),
    Impact("trafficking", "Illegal trafficking",
           "Ports used for illegal traffic in drugs, arms, prohibited goods and people.",
           "secondary"),
    Impact("financial_loss", "Financial loss and costs",
           "Money lost through stopped operations or repair budgets after damage to systems "
           "and infrastructure.",
           "outage"),
    Impact("fraud_theft", "Fraud and money steal",
           "Compromise of port financial systems to steal money; falsified customs "
           "declarations for VAT fraud.",
           "secondary"),
    Impact("systems_damage", "Systems damages or destruction",
           "Damage or destruction of complex and sometimes critical port systems, with "
           "consequences for operations, safety and security.",
           "response"),
    Impact("reputation", "Tarnished reputation, loss of competitiveness",
           "Ports compete internationally; incidents cost standing and traffic.",
           "secondary"),
    Impact("environmental", "Environmental disaster",
           "As the interface between hinterland and sea, an incident can cause oil spills, "
           "gas explosions, ocean pollution and shipwrecks affecting populations and "
           "ecosystems far away.",
           "non_financial"),
)


def find_threat(key: str) -> Threat | None:
    for category in THREAT_TAXONOMY:
        for threat in category.threats:
            if threat.key == key:
                return threat
    return None


def find_impact(key: str) -> Impact | None:
    return next((i for i in IMPACTS if i.key == key), None)


def SUPPLY_CHAIN_THREATS() -> list[tuple[ThreatCategory, Threat]]:
    """The threats reachable through a supplier.

    This is the scoping boundary of the whole DSS. ENISA's taxonomy covers
    everything a port faces including storms and vandalism; we model the subset
    an attacker can reach through a vendor relationship.
    """
    return [
        (category, threat)
        for category in THREAT_TAXONOMY
        for threat in category.threats
        if threat.supply_chain_vector
    ]
