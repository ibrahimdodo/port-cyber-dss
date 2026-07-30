"""Port asset taxonomy, taken from the ENISA port asset taxonomy.

Source: ENISA, "Port Cybersecurity -- Good practices for cybersecurity in the
maritime sector" (November 2019), section 3 "Port Asset Taxonomy", Figure 5 and
Table 2. The ten top-level categories are ENISA's; the sub-categories and their
descriptions follow ENISA's Table 2. A local copy of the report is in `refs/`.

Two fields are ours rather than ENISA's, and they are the reason this module
exists at all:

``typical_vendor_dependency``
    How a small port normally obtains this asset class. Supply-chain risk is a
    function of *who supplies the thing*, so the taxonomy has to carry that.

``supply_chain_relevance``
    How much this category matters for the vendor-compromise question. Not
    every port asset is in scope: breakwaters and floating barriers are real
    port assets with no software vendor behind them, and pretending otherwise
    would pad the model with rows that can never carry risk.

ENISA is explicit that the taxonomy "should not be considered as comprehensive"
and does not reflect the diversity of individual ports, so this is a starting
frame to be pruned per port, not a checklist to be completed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = ["Relevance", "AssetCategory", "AssetSubCategory", "ASSET_TAXONOMY",
           "supply_chain_assets", "find_asset"]


class Relevance(str, Enum):
    """How much an asset class bears on vendor/supply-chain risk."""

    HIGH = "high"      # Vendor compromise directly threatens port operations.
    MEDIUM = "medium"  # Vendor-supplied, but failure is degraded service not stoppage.
    LOW = "low"        # Vendor involvement marginal or maintenance-only.
    NONE = "none"      # Physical asset with no meaningful software supply chain.


@dataclass(frozen=True)
class AssetSubCategory:
    key: str
    name: str
    description: str
    typical_vendor_dependency: str
    supply_chain_relevance: Relevance


@dataclass(frozen=True)
class AssetCategory:
    key: str
    name: str
    subcategories: tuple[AssetSubCategory, ...]


def _sub(key, name, description, vendor, relevance):
    return AssetSubCategory(key, name, description, vendor, relevance)


ASSET_TAXONOMY: tuple[AssetCategory, ...] = (
    AssetCategory(
        "fixed_infrastructure",
        "Fixed infrastructure",
        (
            _sub("seaside_connectivity", "Seaside connectivity",
                 "Navigation between seaside and port area: breakwaters, sea locks, buoys, "
                 "light beacons, waterway marking, tide/wind/current monitoring, waterway radar.",
                 "Navigation aid and monitoring equipment vendors; often a single specialist supplier.",
                 Relevance.MEDIUM),
            _sub("portuary_infrastructure", "Portuary infrastructure",
                 "Mooring (docks, quays, jetties, piers), lighting, access control (gates, "
                 "plate reading, detectors), internal transport (roads, rail, waterways).",
                 "Gate/ANPR and access-control system integrators.",
                 Relevance.HIGH),
            _sub("buildings", "Buildings",
                 "Offices for port services (harbour master, customs) and the data centres "
                 "hosting IT and OT systems.",
                 "Building management system vendors; colocation or hosting providers.",
                 Relevance.MEDIUM),
            _sub("energy", "Energy",
                 "Energy supply for the port ecosystem: electricity network, fresh water "
                 "bunkering, pipelines, fuel and petrol delivery stations.",
                 "Utility SCADA vendors; shore-power system suppliers.",
                 Relevance.MEDIUM),
            _sub("waste_treatment", "Waste treatment systems",
                 "Handling of port and vessel waste, solid and liquid.",
                 "Waste contractor with scheduling software.",
                 Relevance.LOW),
            _sub("hinterland_connectivity", "Hinterland connectivity",
                 "Rail stations and rolling stock loading, road infrastructure, intermodal "
                 "stations, inland waterway connections.",
                 "Rail and intermodal logistics platform providers.",
                 Relevance.MEDIUM),
            _sub("safety_security_infra", "Safety and security infrastructure",
                 "Control tower, operations room, security centre, first response facilities.",
                 "Control-room system integrators.",
                 Relevance.MEDIUM),
        ),
    ),
    AssetCategory(
        "mobile_infrastructure",
        "Mobile infrastructure",
        (
            _sub("port_service_ships", "Port service ships",
                 "Pilot boats, tugboats, mooring assistance, supply, safety, inspection vessels.",
                 "Onboard navigation and comms equipment vendors.",
                 Relevance.LOW),
            _sub("special_vehicles", "Special vehicles",
                 "Firefighting, ambulance, mobile cargo control units.",
                 "Fleet telematics providers.",
                 Relevance.LOW),
            _sub("floating_barriers", "Physical floating barriers",
                 "Barriers protecting critical vessels and port areas, and containing pollution.",
                 "None -- physical equipment.",
                 Relevance.NONE),
        ),
    ),
    AssetCategory(
        "ot_systems",
        "OT systems and networks",
        (
            _sub("ics", "Industrial control systems (ICS)",
                 "Control of port access and berthing (bridges, locks, gates), infrastructure "
                 "and terminal operations (cranes, storage). PLCs, RTUs, historians, SCADA/DCS, "
                 "HMI and engineering workstations, maintenance and safety instrumented systems.",
                 "OEM plus a maintenance contractor holding remote access -- the classic "
                 "small-port single point of failure.",
                 Relevance.HIGH),
            _sub("ics_networks", "ICS communication networks and components",
                 "Networks and components connecting industrial control systems.",
                 "Industrial network equipment vendors; integrator-managed.",
                 Relevance.HIGH),
        ),
    ),
    AssetCategory(
        "ot_end_devices",
        "OT end-devices",
        (
            _sub("loading_unloading", "Vessel loading and unloading",
                 "Cranes, passenger ramps, pipelines, belts and conveyors; freight tracking "
                 "(barcodes, liquid meters, RFID, seals, scales); badge and ticket scanners; "
                 "plate reading; fault detectors in automated loading systems.",
                 "Crane and handling-equipment OEMs with remote diagnostics.",
                 Relevance.HIGH),
            _sub("temporary_storage", "Temporary storage",
                 "Internal transport (straddle carriers, yard trucks, chassis), storage "
                 "equipment, cooled and uncooled stores, silos, tanks, switches for pipes and "
                 "conveyors, wireless access points for smart seals.",
                 "Yard equipment vendors; IoT sensor suppliers.",
                 Relevance.MEDIUM),
            _sub("hinterland_devices", "Hinterland connectivity devices",
                 "Control and inspection systems (scanners, X-ray), rail stations, marshalling "
                 "yards, multimodal hubs, port gate control equipment.",
                 "Scanner and gate equipment vendors.",
                 Relevance.HIGH),
        ),
    ),
    AssetCategory(
        "it_systems",
        "IT systems",
        (
            _sub("pcs", "Port Community System (PCS)",
                 "Single-window system sharing vessel-related port operations information "
                 "between all port stakeholders: arrival and departure, crew lists, dangerous "
                 "goods declarations, bookings of vessel services.",
                 "National or regional PCS operator -- shared across many ports, so one "
                 "compromise reaches all of them.",
                 Relevance.HIGH),
            _sub("ccs", "Cargo Community System (CCS)",
                 "Shares cargo and container information between stakeholders: cargo content, "
                 "container location, transfer times, customs declarations.",
                 "Private terminal-operator software vendor.",
                 Relevance.HIGH),
            _sub("fims", "Fisheries Information Management System (FIMS)",
                 "Manages fisheries operations, catch traceability and catch certification "
                 "for ports hosting fishing activity.",
                 "Fisheries authority platform.",
                 Relevance.LOW),
            _sub("corporate_systems", "Port corporate systems",
                 "Finance, HR, communications, email, ERP, sales and marketing -- the ordinary "
                 "business applications every organisation runs.",
                 "SaaS providers (Microsoft 365, ERP vendors, payroll).",
                 Relevance.HIGH),
            _sub("tos", "Terminal Operating System (TOS)",
                 "Terminal operations management, owned and maintained by terminal operators. "
                 "Plans and directs the movement of every box and vehicle.",
                 "TOS vendor plus its update channel -- the SolarWinds-shaped risk.",
                 Relevance.HIGH),
        ),
    ),
    AssetCategory(
        "it_end_devices",
        "IT end-devices",
        (
            _sub("workstations", "Workstations and mobile devices",
                 "Office and operational endpoints used by port staff.",
                 "OS and endpoint software vendors; managed service provider.",
                 Relevance.HIGH),
        ),
    ),
    AssetCategory(
        "networks",
        "Networks and communication components",
        (
            _sub("radio", "Radio",
                 "RFID, VHF and other radio used for ship communication, safety and security "
                 "operations and logistics management.",
                 "Radio equipment vendors.",
                 Relevance.MEDIUM),
            _sub("protocols", "Protocols",
                 "Information exchange protocols: EDI, APIs, authentication protocols.",
                 "Implicit in supplied software.",
                 Relevance.MEDIUM),
            _sub("servers", "Servers",
                 "Web, application, proxy, mail, virtual servers and printers.",
                 "Hardware OEM, hypervisor vendor, MSP.",
                 Relevance.HIGH),
            _sub("networks", "Networks",
                 "VHF radio, internet, WiMAX/WiFi, satellite, ad-hoc networks, VLAN/LAN, "
                 "possibly managed by different stakeholders at different levels.",
                 "ISP and managed network provider.",
                 Relevance.HIGH),
            _sub("switching", "Switches, routers, hubs",
                 "Components forwarding packets between networks.",
                 "Network equipment vendors and their firmware channel.",
                 Relevance.HIGH),
            _sub("network_security", "Network security",
                 "Firewalls, IPS/IDS, PKI/MFA, antivirus, SIEM and other security solutions.",
                 "Security vendors -- note that a compromised security tool has privileged "
                 "reach by design.",
                 Relevance.HIGH),
            _sub("cloud", "Cloud",
                 "Cloud solutions hosting port data, for example email and shared folders.",
                 "Cloud and SaaS providers.",
                 Relevance.HIGH),
        ),
    ),
    AssetCategory(
        "safety_security_systems",
        "Safety and security systems",
        (
            _sub("detection", "Detection systems",
                 "CCTV, incident management, first response centre systems, intrusion "
                 "detection, abnormal behaviour detection.",
                 "CCTV and physical security system vendors -- frequently the least patched "
                 "estate in the port.",
                 Relevance.HIGH),
            _sub("access_control", "Access control systems",
                 "Automatic gates, smart fencing, badging, access monitoring and counting.",
                 "Access control vendors.",
                 Relevance.HIGH),
            _sub("traffic_monitoring", "Traffic monitoring systems",
                 "Radar and electro-optic monitoring, train and truck traffic monitoring.",
                 "VTS and monitoring vendors.",
                 Relevance.MEDIUM),
            _sub("identification", "Identification and authentication systems",
                 "Face recognition, biometrics, portable ID control terminals.",
                 "Biometric system vendors.",
                 Relevance.MEDIUM),
        ),
    ),
    AssetCategory(
        "information_data",
        "Information and data",
        (
            _sub("mandatory_declarations", "Mandatory declarations",
                 "Declarations required for a ship to enter the port area under international, "
                 "European, national and local regulation (FAL Convention: passenger and crew, "
                 "vessel, cargo, border control, waste, security, health).",
                 "Held in PCS and national single window.",
                 Relevance.HIGH),
            _sub("commercial_financial", "Commercial and financial data",
                 "Service delivery and procurement data: money transfers, invoicing.",
                 "ERP and banking interfaces -- the target of invoice fraud.",
                 Relevance.HIGH),
            _sub("navigation_data", "Navigation data",
                 "Satellite and navigation data shared with the port: AIS, SafeSeaNet, GPS "
                 "position, maritime route information.",
                 "AIS and VTS feeds -- unauthenticated by design.",
                 Relevance.HIGH),
            _sub("control_authorisation", "Control and authorisation",
                 "Authorisations for vessel and cargo movement issued by port and national "
                 "authorities.",
                 "Authority systems.",
                 Relevance.MEDIUM),
            _sub("operational_data", "Operational data",
                 "Data shared between port stakeholders to plan and manage services.",
                 "Spread across PCS, CCS and TOS.",
                 Relevance.HIGH),
        ),
    ),
    AssetCategory(
        "people",
        "People",
        (
            _sub("it_ot_staff", "IT and OT staff",
                 "Staff operating and maintaining systems, employed by the port authority and "
                 "private companies (CISO, CIO, administrators).",
                 "Often a single administrator, or an outsourced function entirely.",
                 Relevance.HIGH),
            _sub("external_staff", "External staff",
                 "Port facility external staff, third-party service staff, temporarily "
                 "authorised staff such as contractors and drivers.",
                 "Contractor access is itself the supply-chain surface.",
                 Relevance.HIGH),
            _sub("ship_crews", "Ship crews",
                 "Crew members and captains using port facilities.",
                 "Not vendor-supplied.",
                 Relevance.LOW),
            _sub("passengers", "Passengers",
                 "Passengers passing through port areas to cruise ships and ferries.",
                 "Booking and check-in SaaS holds their data.",
                 Relevance.MEDIUM),
            _sub("general_public", "General public",
                 "Public access to open port areas for tourism and research.",
                 "Not vendor-supplied.",
                 Relevance.NONE),
        ),
    ),
)


def find_asset(key: str) -> AssetSubCategory | None:
    """Look up a sub-category by key across all categories."""
    for category in ASSET_TAXONOMY:
        for sub in category.subcategories:
            if sub.key == key:
                return sub
    return None


def supply_chain_assets(
    minimum: Relevance = Relevance.HIGH,
) -> list[tuple[AssetCategory, AssetSubCategory]]:
    """Asset classes worth modelling for vendor risk, at or above `minimum`.

    Used to keep the port inventory focused: a 100-person port that tries to
    assess all 40-odd sub-categories will abandon the exercise, whereas the
    HIGH-relevance subset is a morning's work and carries most of the risk.
    """
    order = {Relevance.NONE: 0, Relevance.LOW: 1, Relevance.MEDIUM: 2, Relevance.HIGH: 3}
    threshold = order[minimum]
    return [
        (category, sub)
        for category in ASSET_TAXONOMY
        for sub in category.subcategories
        if order[sub.supply_chain_relevance] >= threshold
    ]
