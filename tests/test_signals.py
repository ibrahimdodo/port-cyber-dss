"""Tests for live vulnerability-intelligence fetching.

No network. Every test injects a fake session, so the suite stays fast,
deterministic and runnable offline — and so the failure paths can be exercised
deliberately rather than by waiting for a real outage.

The behaviours that matter: parsing is correct, caching works, and failure is
*visible*. A feed that cannot be reached must never produce a result that looks
like a clean bill of health.
"""

import json
import tempfile
import time
import unittest
from pathlib import Path

from portscra.signals import (
    SCORECARD_STALE_DAYS,
    FeedResult,
    SignalCache,
    enrich_all,
    enrich_vendor,
    fetch_epss,
    fetch_kev,
    fetch_scorecard,
)
from portscra.vendor.likelihood import Vendor, VendorSignals


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Records calls and returns canned payloads; can be told to fail."""

    def __init__(self, payload=None, fail=False, status=200):
        self.payload = payload or {}
        self.fail = fail
        self.status = status
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        if self.fail:
            raise ConnectionError("simulated network failure")
        payload = self.payload
        # Mirror the real EPSS API, which returns only the CVEs asked for.
        # A canned payload that ignores the query makes every enrichment test
        # silently assert against whichever CVE happens to score highest.
        if params and "cve" in params and "data" in payload:
            wanted = set(params["cve"].split(","))
            payload = {**payload,
                       "data": [r for r in payload["data"] if r["cve"] in wanted]}
        return FakeResponse(payload, self.status)


def temp_cache(ttl=3600) -> SignalCache:
    return SignalCache(Path(tempfile.mkdtemp()), ttl_seconds=ttl)


EPSS_PAYLOAD = {"data": [
    {"cve": "CVE-2024-3094", "epss": "0.859740000", "percentile": "0.997090000"},
    {"cve": "CVE-2021-44228", "epss": "0.999990000", "percentile": "1.000000000"},
]}

KEV_PAYLOAD = {"vulnerabilities": [
    {"cveID": "CVE-2021-44228", "vendorProject": "Apache", "product": "Log4j2",
     "knownRansomwareCampaignUse": "Known", "dateAdded": "2021-12-10"},
    {"cveID": "CVE-2023-1234", "vendorProject": "Acme", "product": "Widget",
     "knownRansomwareCampaignUse": "Unknown", "dateAdded": "2023-03-01"},
]}


class TestEPSS(unittest.TestCase):
    def test_parses_scores(self):
        session = FakeSession(EPSS_PAYLOAD)
        r = fetch_epss(["CVE-2024-3094"], cache=temp_cache(), session=session)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.data["CVE-2024-3094"]["epss"], 0.85974)

    def test_empty_input_makes_no_request(self):
        session = FakeSession(EPSS_PAYLOAD)
        r = fetch_epss([], cache=temp_cache(), session=session)
        self.assertTrue(r.ok)
        self.assertEqual(session.calls, [])

    def test_network_failure_is_visible(self):
        """The critical property. A failed fetch must not look like a clean
        result, or absence of evidence silently becomes evidence of absence."""
        r = fetch_epss(["CVE-1"], cache=temp_cache(), session=FakeSession(fail=True))
        self.assertFalse(r.ok)
        self.assertIn("ConnectionError", r.error)
        self.assertEqual(r.data, {})
        self.assertIn("unavailable", r.describe())

    def test_http_error_is_caught(self):
        session = FakeSession(EPSS_PAYLOAD, status=503)
        self.assertFalse(fetch_epss(["CVE-1"], cache=temp_cache(), session=session).ok)

    def test_second_call_is_served_from_cache(self):
        cache = temp_cache()
        session = FakeSession(EPSS_PAYLOAD)
        fetch_epss(["CVE-2024-3094"], cache=cache, session=session)
        second = fetch_epss(["CVE-2024-3094"], cache=cache, session=session)
        self.assertEqual(len(session.calls), 1, "cache did not prevent a refetch")
        self.assertTrue(second.from_cache)

    def test_expired_cache_refetches(self):
        cache = temp_cache(ttl=0)
        session = FakeSession(EPSS_PAYLOAD)
        fetch_epss(["CVE-2024-3094"], cache=cache, session=session)
        fetch_epss(["CVE-2024-3094"], cache=cache, session=session)
        self.assertEqual(len(session.calls), 2)


class TestKEV(unittest.TestCase):
    def test_parses_catalogue_and_ransomware_flag(self):
        r = fetch_kev(cache=temp_cache(), session=FakeSession(KEV_PAYLOAD))
        self.assertTrue(r.ok)
        self.assertTrue(r.data["CVE-2021-44228"]["ransomware"])
        self.assertFalse(r.data["CVE-2023-1234"]["ransomware"])

    def test_failure_is_visible(self):
        r = fetch_kev(cache=temp_cache(), session=FakeSession(fail=True))
        self.assertFalse(r.ok)
        self.assertEqual(r.data, {})


class TestScorecard(unittest.TestCase):
    def _payload(self, score=7.5, date="2026-07-01"):
        return {"score": score, "date": date,
                "checks": [{"name": "Code-Review", "score": 8}]}

    def test_parses_score(self):
        r = fetch_scorecard("github.com/a/b", cache=temp_cache(),
                            session=FakeSession(self._payload()))
        self.assertTrue(r.ok)
        self.assertEqual(r.data["score"], 7.5)
        self.assertFalse(r.data["stale"])

    def test_old_scan_is_flagged_stale(self):
        """The API serves whatever its last crawl found. Some widely used
        projects were last scanned years ago, and that is weak evidence about
        today's repository."""
        r = fetch_scorecard("github.com/a/b", cache=temp_cache(),
                            session=FakeSession(self._payload(date="2019-01-01")))
        self.assertTrue(r.data["stale"])

    def test_strips_url_scheme(self):
        session = FakeSession(self._payload())
        fetch_scorecard("https://github.com/a/b", cache=temp_cache(), session=session)
        self.assertNotIn("https://", session.calls[0][0].split("/projects/")[1])

    def test_empty_repository_rejected(self):
        r = fetch_scorecard("  ", cache=temp_cache(), session=FakeSession())
        self.assertFalse(r.ok)


class TestEnrichment(unittest.TestCase):
    def test_enrichment_replaces_hand_entered_signals(self):
        vendor = Vendor("v", "V", "sw", cve_ids=("CVE-2024-3094",),
                        signals=VendorSignals(max_epss=0.01, source="guess"))
        signals, notes = enrich_vendor(
            vendor,
            kev=FeedResult(ok=True, data={}, fetched_at=time.time()),
            cache=temp_cache(), session=FakeSession(EPSS_PAYLOAD))
        self.assertAlmostEqual(signals.max_epss, 0.85974)
        self.assertNotIn("guess", signals.source)
        self.assertTrue(any("EPSS" in n for n in notes))

    def test_kev_hit_is_counted_and_ransomware_propagates(self):
        vendor = Vendor("v", "V", "sw", cve_ids=("CVE-2021-44228",))
        kev = fetch_kev(cache=temp_cache(), session=FakeSession(KEV_PAYLOAD))
        signals, notes = enrich_vendor(vendor, kev=kev, cache=temp_cache(),
                                       session=FakeSession(EPSS_PAYLOAD))
        self.assertEqual(signals.kev_count, 1)
        self.assertTrue(signals.recent_breach, "ransomware flag should raise risk")

    def test_a_disclosed_breach_survives_enrichment(self):
        """No public feed reports 'this supplier told us they were breached'.
        Enrichment must refresh what it can without discarding what it cannot."""
        vendor = Vendor("v", "V", "sw", cve_ids=("CVE-2024-3094",),
                        signals=VendorSignals(recent_breach=True))
        signals, _ = enrich_vendor(
            vendor, kev=FeedResult(ok=True, data={}, fetched_at=time.time()),
            cache=temp_cache(), session=FakeSession(EPSS_PAYLOAD))
        self.assertTrue(signals.recent_breach)

    def test_vendor_with_no_identifiers_says_so(self):
        vendor = Vendor("v", "V", "sw")
        signals, notes = enrich_vendor(vendor, cache=temp_cache(),
                                       session=FakeSession())
        self.assertIn("nothing to look up", " ".join(notes))
        self.assertIsNone(signals.max_epss)

    def test_failed_feed_leaves_signal_unset_and_notes_it(self):
        vendor = Vendor("v", "V", "sw", cve_ids=("CVE-1",))
        signals, notes = enrich_vendor(vendor, cache=temp_cache(),
                                       session=FakeSession(fail=True))
        self.assertIsNone(signals.max_epss)
        self.assertEqual(signals.kev_count, 0)
        self.assertTrue(any("unavailable" in n for n in notes))

    def test_enrich_all_fetches_kev_once(self):
        """The catalogue is 1.5 MB and identical for every vendor."""
        vendors = [Vendor(f"v{i}", "V", "sw", cve_ids=("CVE-2021-44228",))
                   for i in range(4)]
        session = FakeSession(KEV_PAYLOAD)
        enrich_all(vendors, cache=temp_cache(), session=session)
        kev_calls = [c for c in session.calls if "known_exploited" in c[0]]
        self.assertEqual(len(kev_calls), 1)

    def test_enrich_all_does_not_mutate_the_originals(self):
        vendors = [Vendor("v", "V", "sw", cve_ids=("CVE-2024-3094",))]
        before = vendors[0].signals
        enriched, _ = enrich_all(vendors, cache=temp_cache(),
                                 session=FakeSession(EPSS_PAYLOAD))
        self.assertIs(vendors[0].signals, before)
        self.assertIsNot(enriched[0].signals, before)


class TestCache(unittest.TestCase):
    def test_unwritable_cache_degrades_rather_than_crashing(self):
        """A hosted deployment may have no writable home directory. An
        unwritable cache should mean re-fetching, not a broken page."""
        cache = SignalCache(Path("/proc/nonexistent/portscra"))
        cache.put("k", {"a": 1})           # must not raise
        self.assertIsNone(cache.get("k"))

    def test_corrupt_cache_entry_is_ignored(self):
        cache = temp_cache()
        cache.directory.mkdir(parents=True, exist_ok=True)
        (cache.directory / "broken.json").write_text("{not json")
        self.assertIsNone(cache.get("broken"))

    def test_roundtrip(self):
        cache = temp_cache()
        cache.put("key", {"x": 2})
        got = cache.get("key")
        self.assertIsNotNone(got)
        self.assertEqual(got[0], {"x": 2})


if __name__ == "__main__":
    unittest.main()
