"""Candidate Danish anchor ports, as bounding boxes over AIS position reports.

Rønne (Bornholm) is the project's chosen anchor. The others are fallbacks kept
deliberately in the list so a single day-one ETL run evaluates all four at once
and the choice is made on observed traffic rather than on desk research.

Why Rønne: it is small enough that a 100-person port ecosystem is a credible
persona (Tallinn, by contrast, moves ~29.8 Mt and 2M+ TEU), its traffic is
genuinely mixed (ferry, cargo, cruise, offshore wind), it sits in the Baltic as
the original brief framed, and it is on an island -- so an outage severs a
supply line with no road alternative, which is exactly the harm ENISA singles
out as worse "especially for the islands".

The boxes are first approximations drawn around each harbour basin and its
immediate approach. They are meant to be tightened from the data: run
`scripts/day_one.py`, look at where the stationary points actually cluster, and
adjust. A box that is too generous picks up vessels transiting past the port; a
box that is too tight misses berths. Day one exists to tell us which we have.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PortArea", "CANDIDATE_PORTS", "RONNE", "find_port"]


@dataclass(frozen=True)
class PortArea:
    """A port's approximate footprint in AIS coordinate space.

    Attributes
    ----------
    key, name, unlocode
        Identity. UN/LOCODE is the standard port identifier and is what to use
        when joining against port statistics or annual reports.
    lat_min, lat_max, lon_min, lon_max
        Bounding box in decimal degrees (WGS84), as AIS reports positions.
    notes
        What we expect to see here, so the day-one output can be sanity-checked
        against an expectation rather than merely admired.
    """

    key: str
    name: str
    unlocode: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    notes: str = ""

    def contains(self, lat, lon):
        """Vectorised point-in-box test. Accepts scalars or numpy arrays."""
        return (
            (lat >= self.lat_min)
            & (lat <= self.lat_max)
            & (lon >= self.lon_min)
            & (lon <= self.lon_max)
        )

    @property
    def centre(self) -> tuple[float, float]:
        return (
            (self.lat_min + self.lat_max) / 2.0,
            (self.lon_min + self.lon_max) / 2.0,
        )


RONNE = PortArea(
    key="ronne",
    name="Rønne",
    unlocode="DKRNN",
    lat_min=55.080,
    # Northern edge cut at 55.100 to exclude the marina. Derived from the
    # 2026-07-25 validation run, which showed a clean spatial separation:
    # commercial traffic (ferry, cargo, tanker, tug, SAR) berths at
    # 55.0875-55.0994, while sailing and pleasure craft sit at 55.1033-55.1056.
    # Before the cut, 29 of 50 vessels seen in a July day were recreational --
    # they contribute nothing to port revenue and would badly distort a
    # euro-per-hour calibration built on vessel counts.
    lat_max=55.100,
    lon_min=14.670,
    lon_max=14.730,
    notes=(
        "Project anchor. Commercial basin only (marina excluded, see lat_max). "
        "Bornholmslinjen ferries to Ystad and Køge, general cargo and bulk, "
        "seasonal cruise, and offshore-wind project traffic. Roughly 3,000 "
        "calls and 1.4 Mt a year, ~1.5M passengers."
    ),
)

CANDIDATE_PORTS: tuple[PortArea, ...] = (
    RONNE,
    PortArea(
        key="grenaa",
        name="Grenaa",
        unlocode="DKGRE",
        lat_min=56.395,
        lat_max=56.425,
        lon_min=10.905,
        lon_max=10.950,
        notes="Fallback. Mixed ferry (Anholt), bulk, offshore wind and general cargo.",
    ),
    PortArea(
        key="kalundborg",
        name="Kalundborg",
        unlocode="DKKAL",
        lat_min=55.660,
        lat_max=55.700,
        lon_min=11.050,
        lon_max=11.120,
        notes="Fallback. Industrial and tanker traffic plus ferry to Aarhus/Samsø.",
    ),
    PortArea(
        key="koge",
        name="Køge",
        unlocode="DKKOG",
        lat_min=55.425,
        lat_max=55.465,
        lon_min=12.175,
        lon_max=12.230,
        notes="Fallback. The Zealand end of the Rønne ferry link; general cargo and bulk.",
    ),
)


def find_port(key: str) -> PortArea | None:
    return next((p for p in CANDIDATE_PORTS if p.key == key), None)


def union_bounds() -> tuple[float, float, float, float]:
    """Single bounding box enclosing every candidate port.

    Used as a cheap first-pass filter while streaming a day of AIS: one
    comparison against this box discards the ~99.9% of Danish-waters traffic
    that is nowhere near any port we care about, before the more precise
    per-port assignment runs.
    """
    return (
        min(p.lat_min for p in CANDIDATE_PORTS),
        max(p.lat_max for p in CANDIDATE_PORTS),
        min(p.lon_min for p in CANDIDATE_PORTS),
        max(p.lon_max for p in CANDIDATE_PORTS),
    )
