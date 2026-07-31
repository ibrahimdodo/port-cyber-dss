"""A worked example port: the supplier list used by the demos and the dashboard.

These are ILLUSTRATIVE ROLES, not real companies, and the questionnaire answers
are plausible profiles rather than findings about anyone's actual security.
Naming real suppliers here would assert things about their posture that this
project has no evidence for, and a reader could reasonably mistake a worked
example for a published assessment.

The list lives in the package rather than in a demo script because three
different callers need it -- the pipeline demo, the dashboard, and any notebook
-- and importing data out of a script requires a `sys.path` hack that breaks the
moment the app is deployed somewhere the scripts directory is not.

Replace `EXAMPLE_VENDORS` with real questionnaire responses to assess a real
port. Nothing else in the codebase needs to change.
"""

from __future__ import annotations

from .vendor.likelihood import Vendor, VendorSignals

__all__ = ["EXAMPLE_VENDORS", "answers"]


def answers(**kwargs: int) -> dict[str, int]:
    """Shorthand for questionnaire responses: answers(Q1=0, Q2=3)."""
    return dict(kwargs)


#: A plausible supplier list for a port of Rønne's size and traffic mix.
EXAMPLE_VENDORS: list[Vendor] = [
    Vendor(
        "msp", "Managed service provider (outsourced IT)", "MSP",
        supplies=("workstations", "servers", "networks", "corporate_systems"),
        answers=answers(Q1=0, Q2=1, Q3=1, Q4=1, Q5=1, Q6=3, Q7=1, Q8=1, Q9=1,
                        Q10=1, Q11=1, Q12=1, Q13=0, Q14=1, Q15=3, Q16=2, Q17=1,
                        Q18=2, Q19=1, Q20=1),
        notes="Holds standing administrative access to the whole estate. For a "
              "port with no in-house security function this is the single "
              "largest concentration of risk -- the Kaseya shape.",
    ),
    Vendor(
        "tos", "Terminal operating system vendor", "software",
        supplies=("tos",),
        answers=answers(Q1=1, Q2=2, Q3=2, Q4=0, Q5=0, Q6=2, Q7=3, Q8=2, Q9=2,
                        Q10=2, Q11=1, Q12=1, Q13=1, Q14=2, Q15=3, Q16=2, Q17=1,
                        Q18=2, Q19=0, Q20=0),
        signals=VendorSignals(max_epss=0.12, source="illustrative"),
        notes="Operations stop without it and replacement would take years. "
              "The SolarWinds vector runs through its update channel.",
    ),
    Vendor(
        "cloud_office", "Cloud productivity and email suite", "SaaS",
        supplies=("cloud", "corporate_systems", "commercial_financial"),
        answers=answers(Q1=2, Q2=3, Q3=3, Q4=2, Q5=2, Q6=3, Q7=3, Q8=3, Q9=3,
                        Q10=2, Q11=3, Q12=1, Q13=2, Q14=3, Q15=2, Q16=3, Q17=0,
                        Q18=2, Q19=2, Q20=2),
        notes="Strong posture, but holds the mailboxes through which invoices "
              "are agreed -- the business email compromise path.",
    ),
    Vendor(
        "crane_oem", "Crane and handling equipment OEM", "OT",
        supplies=("loading_unloading", "ics"),
        answers=answers(Q1=1, Q2=0, Q3=0, Q4=1, Q5=1, Q6=0, Q7=1, Q8=0, Q9=0,
                        Q10=1, Q11=0, Q12=0, Q13=0, Q14=0, Q15=3, Q16=0, Q17=2,
                        Q18=0, Q19=0, Q20=0),
        notes="Remote diagnostics into safety-relevant equipment, minimal "
              "security programme. Typical of OT suppliers to small ports.",
    ),
    Vendor(
        "gate_cctv", "Gate, ANPR and CCTV integrator", "OT",
        supplies=("access_control", "detection", "portuary_infrastructure"),
        answers=answers(Q1=1, Q2=1, Q3=1, Q4=1, Q5=1, Q6=1, Q7=0, Q8=0, Q9=0,
                        Q10=1, Q11=0, Q12=0, Q13=0, Q14=0, Q15=1, Q16=1, Q17=1,
                        Q18=1, Q19=2, Q20=2),
        signals=VendorSignals(kev_count=1, max_epss=0.35, source="illustrative"),
        notes="The least-patched estate in most ports; the Antwerp "
              "container-release manipulation ran through this class of system.",
    ),
    Vendor(
        "pcs", "Port community system operator", "platform",
        supplies=("pcs", "mandatory_declarations", "operational_data"),
        answers=answers(Q1=2, Q2=2, Q3=2, Q4=1, Q5=1, Q6=3, Q7=2, Q8=2, Q9=2,
                        Q10=2, Q11=2, Q12=2, Q13=1, Q14=2, Q15=3, Q16=2, Q17=0,
                        Q18=2, Q19=0, Q20=1),
        notes="Shared across many ports, so one compromise reaches all of them. "
              "Holds crew and passenger declarations.",
    ),
    Vendor(
        "booking", "Ferry booking and check-in platform", "SaaS",
        supplies=("corporate_systems", "commercial_financial"),
        answers=answers(Q1=2, Q2=2, Q3=2, Q4=1, Q5=1, Q6=3, Q7=2, Q8=1, Q9=1,
                        Q10=1, Q11=1, Q12=2, Q13=1, Q14=1, Q15=1, Q16=2, Q17=0,
                        Q18=2, Q19=1, Q20=1),
        signals=VendorSignals(recent_breach=True, source="illustrative"),
        notes="Holds passenger personal data at volume -- GDPR and NIS2 exposure.",
    ),
    Vendor(
        "oss_lib", "Open-source component in supplied software", "freeware",
        supplies=("servers", "workstations"),
        # No questionnaire is possible: there is no vendor to send it to. This
        # is the brief's "freeware?" case, and the reason external signals are
        # not optional.
        signals=VendorSignals(openssf_scorecard=3.2, max_epss=0.08,
                              source="illustrative OpenSSF Scorecard"),
        notes="Nobody to send a questionnaire to. Assessed entirely on public "
              "signals; the xz-utils backdoor was this shape.",
    ),
]
