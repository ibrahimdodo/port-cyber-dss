"""Live vulnerability intelligence: EPSS, CISA KEV, OpenSSF Scorecard.

Until this module existed the vendor signals were hand-typed constants labelled
`source="illustrative"`, while the README described them as fused public
signals. The logic was real; the data was invented. This closes that gap.

Three free, unauthenticated sources:

* **EPSS** (FIRST) -- daily probability that a given CVE will be exploited in
  the next 30 days. Answers "is this one of the few vulnerabilities that
  actually gets used?", which CVSS severity does not.
* **CISA KEV** -- the catalogue of vulnerabilities observed being exploited.
  Presence is strong evidence; absence is weak, because most software never
  receives the scrutiny that would put it there. Also carries a
  known-ransomware-campaign flag, which bears directly on the MSP scenario.
* **OpenSSF Scorecard** -- automated supply-chain hygiene score for an
  open-source repository. The only assessment available for the brief's
  "freeware?" case, where there is no vendor to send a questionnaire to.

Two design commitments:

**Failure is visible, never silent.** If a feed is unreachable the result says
so. A missing signal must never be indistinguishable from a clean one, because
the whole point of the asymmetric weighting in `likelihood.py` is that absence
of evidence is not evidence of absence.

**Results are cached on disk with a TTL.** EPSS and KEV change daily at most,
and re-fetching a 1.5 MB catalogue on every dashboard rerun would be rude to
CISA and slow for the user.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from .vendor.likelihood import Vendor, VendorSignals

__all__ = ["FeedResult", "SignalCache", "fetch_epss", "fetch_kev",
           "fetch_scorecard", "enrich_vendor", "enrich_all"]

EPSS_API = "https://api.first.org/data/v1/epss"
KEV_FEED = ("https://www.cisa.gov/sites/default/files/feeds/"
            "known_exploited_vulnerabilities.json")
SCORECARD_API = "https://api.securityscorecards.dev/projects"

#: EPSS republishes daily; KEV changes a few times a week. A day is generous
#: enough to be polite to the upstreams and short enough to stay current.
DEFAULT_TTL_SECONDS = 24 * 60 * 60

#: A Scorecard result older than this is reported as stale. Repository hygiene
#: drifts, and the API returns whatever its last crawl found -- some popular
#: projects were last scanned years ago.
SCORECARD_STALE_DAYS = 180


def _cache_dir() -> Path:
    """Where to cache feed responses.

    Honours PORTSCRA_CACHE if set, then the XDG cache location, then a temp
    directory. The fallback matters for deployment: a hosted app may have no
    writable home directory, and an unwritable cache should degrade to
    re-fetching rather than crash the page.
    """
    override = os.environ.get("PORTSCRA_CACHE")
    if override:
        return Path(override)
    home = Path.home()
    try:
        target = home / ".cache" / "portscra"
        target.mkdir(parents=True, exist_ok=True)
        return target
    except OSError:
        return Path(tempfile.gettempdir()) / "portscra-cache"


@dataclass
class FeedResult:
    """Outcome of a feed lookup, including how it went.

    Carried through rather than reduced to the data alone so callers can tell
    "the feed said nothing was wrong" apart from "the feed was unreachable".
    """

    ok: bool
    data: dict = field(default_factory=dict)
    source: str = ""
    fetched_at: float = 0.0
    from_cache: bool = False
    error: str = ""

    @property
    def age_hours(self) -> float:
        return (time.time() - self.fetched_at) / 3600 if self.fetched_at else float("inf")

    def describe(self) -> str:
        if not self.ok:
            return f"unavailable ({self.error})"
        origin = "cache" if self.from_cache else "live"
        return f"{origin}, {self.age_hours:.1f} h old"


class SignalCache:
    """Disk cache with a TTL, tolerant of an unwritable cache directory."""

    def __init__(self, directory: Path | None = None,
                 ttl_seconds: int = DEFAULT_TTL_SECONDS):
        self.directory = Path(directory) if directory else _cache_dir()
        self.ttl_seconds = ttl_seconds

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return self.directory / f"{safe}.json"

    def get(self, key: str) -> tuple[dict, float] | None:
        path = self._path(key)
        try:
            if not path.exists():
                return None
            payload = json.loads(path.read_text())
            stamp = payload.get("_fetched_at", 0)
            if time.time() - stamp > self.ttl_seconds:
                return None
            return payload.get("data", {}), stamp
        except (OSError, json.JSONDecodeError):
            return None

    def put(self, key: str, data: dict) -> float:
        stamp = time.time()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            self._path(key).write_text(
                json.dumps({"_fetched_at": stamp, "data": data}))
        except OSError:
            pass  # An unwritable cache is a slowdown, not a failure.
        return stamp


def fetch_epss(
    cve_ids: list[str] | tuple[str, ...],
    *,
    cache: SignalCache | None = None,
    timeout: int = 20,
    session: requests.Session | None = None,
) -> FeedResult:
    """Exploit probabilities for specific CVEs, from FIRST's EPSS API.

    Returns a mapping of CVE id to {"epss": float, "percentile": float}. CVEs
    the API does not know are simply absent -- EPSS only covers published CVEs,
    and a missing entry means "not scored", not "not exploitable".
    """
    if not cve_ids:
        return FeedResult(ok=True, data={}, source="EPSS (no CVEs supplied)")

    cache = cache or SignalCache()
    key = "epss-" + "-".join(sorted(cve_ids))[:120]
    cached = cache.get(key)
    if cached:
        return FeedResult(ok=True, data=cached[0], source=EPSS_API,
                          fetched_at=cached[1], from_cache=True)

    try:
        getter = session.get if session else requests.get
        response = getter(EPSS_API, params={"cve": ",".join(cve_ids)},
                          timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        data = {
            row["cve"]: {"epss": float(row["epss"]),
                         "percentile": float(row["percentile"])}
            for row in payload.get("data", [])
        }
        return FeedResult(ok=True, data=data, source=EPSS_API,
                          fetched_at=cache.put(key, data))
    except Exception as exc:  # network, JSON, schema -- all degrade the same way
        return FeedResult(ok=False, source=EPSS_API, error=f"{type(exc).__name__}: {exc}")


def fetch_kev(
    *, cache: SignalCache | None = None, timeout: int = 30,
    session: requests.Session | None = None,
) -> FeedResult:
    """CISA's Known Exploited Vulnerabilities catalogue.

    Returns {cve_id: {"vendor", "product", "ransomware": bool, "dateAdded"}}.
    The ransomware flag is worth carrying: it maps directly onto the MSP
    compromise scenario rather than being generic severity information.
    """
    cache = cache or SignalCache()
    cached = cache.get("kev-catalogue")
    if cached:
        return FeedResult(ok=True, data=cached[0], source=KEV_FEED,
                          fetched_at=cached[1], from_cache=True)

    try:
        getter = session.get if session else requests.get
        response = getter(KEV_FEED, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        data = {
            entry["cveID"]: {
                "vendor": entry.get("vendorProject", ""),
                "product": entry.get("product", ""),
                "ransomware": entry.get("knownRansomwareCampaignUse", "")
                              .strip().lower() == "known",
                "date_added": entry.get("dateAdded", ""),
            }
            for entry in payload.get("vulnerabilities", [])
        }
        return FeedResult(ok=True, data=data, source=KEV_FEED,
                          fetched_at=cache.put("kev-catalogue", data))
    except Exception as exc:
        return FeedResult(ok=False, source=KEV_FEED, error=f"{type(exc).__name__}: {exc}")


def fetch_scorecard(
    repository: str, *, cache: SignalCache | None = None, timeout: int = 20,
    session: requests.Session | None = None,
) -> FeedResult:
    """OpenSSF Scorecard for a repository, e.g. "github.com/curl/curl".

    The returned `stale` flag matters. The API serves whatever its last crawl
    produced, and some widely used projects were last scanned years ago; a
    four-year-old hygiene score is weak evidence about today's repository.
    """
    repository = repository.strip().removeprefix("https://").removeprefix("http://")
    if not repository:
        return FeedResult(ok=False, source=SCORECARD_API, error="empty repository")

    cache = cache or SignalCache()
    key = f"scorecard-{repository}"
    cached = cache.get(key)
    if cached:
        return FeedResult(ok=True, data=cached[0], source=SCORECARD_API,
                          fetched_at=cached[1], from_cache=True)

    try:
        getter = session.get if session else requests.get
        response = getter(f"{SCORECARD_API}/{repository}", timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        scanned = str(payload.get("date", ""))[:10]
        stale = True
        if scanned:
            try:
                import datetime as _dt
                age = (_dt.date.today() - _dt.date.fromisoformat(scanned)).days
                stale = age > SCORECARD_STALE_DAYS
            except ValueError:
                stale = True
        data = {
            "score": float(payload.get("score", 0.0)),
            "scanned": scanned,
            "stale": stale,
            "checks": {c["name"]: c.get("score") for c in payload.get("checks", [])},
        }
        return FeedResult(ok=True, data=data, source=SCORECARD_API,
                          fetched_at=cache.put(key, data))
    except Exception as exc:
        return FeedResult(ok=False, source=SCORECARD_API,
                          error=f"{type(exc).__name__}: {exc}")


def enrich_vendor(
    vendor: Vendor,
    *,
    kev: FeedResult | None = None,
    cache: SignalCache | None = None,
    session: requests.Session | None = None,
) -> tuple[VendorSignals, list[str]]:
    """Replace a vendor's hand-entered signals with live feed data.

    Returns the new signals and a list of human-readable notes explaining what
    was looked up and what happened -- including failures, which the caller
    should surface rather than swallow.

    Pass a pre-fetched `kev` when enriching several vendors: the catalogue is
    1.5 MB and identical for all of them.
    """
    cache = cache or SignalCache()
    notes: list[str] = []
    cve_ids = tuple(vendor.cve_ids)

    max_epss: float | None = None
    if cve_ids:
        epss = fetch_epss(cve_ids, cache=cache, session=session)
        if epss.ok and epss.data:
            max_epss = max(v["epss"] for v in epss.data.values())
            worst = max(epss.data.items(), key=lambda kv: kv[1]["epss"])[0]
            notes.append(f"EPSS {max_epss:.1%} (worst: {worst}) [{epss.describe()}]")
        elif epss.ok:
            notes.append(f"EPSS: none of {len(cve_ids)} CVE(s) scored")
        else:
            notes.append(f"EPSS {epss.describe()}")

    kev_count = 0
    ransomware = False
    if cve_ids:
        kev = kev or fetch_kev(cache=cache, session=session)
        if kev.ok:
            hits = [c for c in cve_ids if c in kev.data]
            kev_count = len(hits)
            ransomware = any(kev.data[c]["ransomware"] for c in hits)
            if hits:
                notes.append(
                    f"KEV: {kev_count} of {len(cve_ids)} CVE(s) known exploited"
                    + (", linked to ransomware campaigns" if ransomware else "")
                    + f" [{kev.describe()}]")
            else:
                notes.append(f"KEV: no listed CVEs [{kev.describe()}]")
        else:
            notes.append(f"KEV {kev.describe()}")

    scorecard: float | None = None
    if vendor.repository:
        result = fetch_scorecard(vendor.repository, cache=cache, session=session)
        if result.ok:
            scorecard = result.data["score"]
            stale = " STALE" if result.data.get("stale") else ""
            notes.append(f"OpenSSF Scorecard {scorecard:.1f}/10 "
                         f"(scanned {result.data.get('scanned', '?')}{stale})")
            if result.data.get("stale"):
                notes.append("  scorecard is old; treat as weak evidence")
        else:
            notes.append(f"Scorecard {result.describe()}")

    if not cve_ids and not vendor.repository:
        notes.append("no CVE ids or repository recorded — nothing to look up")

    source = "; ".join(notes) if notes else "no live signals available"
    return (
        VendorSignals(
            max_epss=max_epss,
            kev_count=kev_count,
            openssf_scorecard=scorecard,
            # Preserve a hand-recorded breach: no public feed reports "this
            # supplier told us they were breached", and dropping it during
            # enrichment would lose information rather than refresh it.
            recent_breach=vendor.signals.recent_breach or ransomware,
            source=source,
        ),
        notes,
    )


def enrich_all(
    vendors: list[Vendor], *, cache: SignalCache | None = None,
    session: requests.Session | None = None,
) -> tuple[list[Vendor], dict[str, list[str]]]:
    """Enrich every vendor, fetching the KEV catalogue only once.

    Returns new Vendor objects (the originals are left untouched) and the notes
    per vendor key.
    """
    import dataclasses

    cache = cache or SignalCache()
    kev = fetch_kev(cache=cache, session=session)
    enriched, all_notes = [], {}
    for vendor in vendors:
        signals, notes = enrich_vendor(vendor, kev=kev, cache=cache, session=session)
        enriched.append(dataclasses.replace(vendor, signals=signals))
        all_notes[vendor.key] = notes
    return enriched, all_notes
