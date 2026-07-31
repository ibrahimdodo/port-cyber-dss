#!/usr/bin/env python3
"""Refresh vendor signals from live feeds, and show what changes.

Fetches EPSS, CISA KEV and OpenSSF Scorecard for every supplier that has a CVE
or repository recorded, then re-runs the assessment so the effect on each
vendor's compromise probability is visible.

Until this existed the signals were hand-typed constants labelled
"illustrative" while the README described them as fused public feeds. This is
what closes that gap.

Usage
-----
    python scripts/refresh_signals.py
    python scripts/refresh_signals.py --offline   # show graceful degradation
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("portscra") is None:  # not pip-installed; run in place
    sys.path.insert(0, str(REPO / "src"))

from portscra.examples import EXAMPLE_VENDORS  # noqa: E402
from portscra.signals import SignalCache, enrich_all, fetch_kev  # noqa: E402
from portscra.vendor import LikelihoodModel  # noqa: E402


class OfflineSession:
    """Simulates every feed being unreachable, to show the failure path."""

    def get(self, *args, **kwargs):
        raise ConnectionError("offline mode")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true",
                        help="Simulate unreachable feeds.")
    parser.add_argument("--cache-dir", type=Path, default=None)
    args = parser.parse_args()

    session = OfflineSession() if args.offline else None
    cache = SignalCache(args.cache_dir) if args.cache_dir else SignalCache()
    model = LikelihoodModel()

    print("\n=== Live vulnerability intelligence ===")
    print(f"cache: {cache.directory}")

    kev = fetch_kev(cache=cache, session=session)
    print(f"CISA KEV: {kev.describe()}"
          + (f" — {len(kev.data):,} known-exploited CVEs" if kev.ok else ""))
    if kev.ok:
        ransomware = sum(1 for v in kev.data.values() if v["ransomware"])
        print(f"  of which {ransomware:,} are linked to ransomware campaigns")

    have_ids = [v for v in EXAMPLE_VENDORS if v.cve_ids or v.repository]
    print(f"\n{len(have_ids)} of {len(EXAMPLE_VENDORS)} suppliers have a CVE or "
          f"repository recorded and can be enriched.")
    print("The rest rest on questionnaire evidence alone — which is the normal")
    print("case for a crane OEM or a local integrator, and why the questionnaire")
    print("cannot be replaced by scanning.\n")

    enriched, notes = enrich_all(EXAMPLE_VENDORS, cache=cache, session=session)
    before = {v.key: model.assess(v) for v in EXAMPLE_VENDORS}
    after = {v.key: model.assess(v) for v in enriched}

    header = (f"{'supplier':44s} {'signals before':>15s} {'after':>8s} "
              f"{'P(compromise) before':>21s} {'after':>9s}")
    print(header)
    print("-" * len(header))
    for vendor in EXAMPLE_VENDORS:
        b, a = before[vendor.key], after[vendor.key]
        moved = "" if abs(a.signal_multiplier - b.signal_multiplier) < 0.005 else "  <-"
        print(f"{vendor.name[:42]:44s} {b.signal_multiplier:14.2f}x "
              f"{a.signal_multiplier:7.2f}x "
              f"{b.annual_probability.most_likely:20.1%} "
              f"{a.annual_probability.most_likely:8.1%}{moved}")

    print("\n--- what each lookup found ---")
    for vendor in EXAMPLE_VENDORS:
        entries = notes.get(vendor.key, [])
        if entries and "nothing to look up" not in entries[0]:
            print(f"\n  {vendor.name}")
            for note in entries:
                print(f"    {note}")

    if not args.offline and kev.ok:
        print("\n--- a result worth reading carefully ---")
        oss = next((v for v in enriched if v.category == "freeware"), None)
        if oss and oss.signals.max_epss is not None:
            in_kev = oss.signals.kev_count > 0
            print(f"  The open-source component scores "
                  f"{oss.signals.max_epss:.0%} on EPSS but is "
                  f"{'listed in' if in_kev else 'NOT listed in'} CISA KEV.")
            if not in_kev:
                print("  The xz-utils backdoor was caught before it was exploited")
                print("  in the wild, so it never entered the KEV catalogue despite")
                print("  being among the most serious supply-chain compromises yet")
                print("  found. This is exactly why the model treats KEV presence as")
                print("  strong evidence and KEV absence as weak: most software never")
                print("  receives the scrutiny that would put it there, and some that")
                print("  does is caught too early to qualify.")

    print("\n--- honesty check ---")
    identified = [v for v in enriched if v.cve_ids or v.repository]
    resolved = [v for v in identified if v.signals.has_any]
    unresolved = [v for v in identified if not v.signals.has_any]

    if args.offline:
        if resolved:
            print(f"  Feeds unreachable, but {len(resolved)} supplier(s) still "
                  f"resolved from the local cache.")
            print("  That is the cache earning its place: a port assessing risk on")
            print("  a bad connection gets yesterday's intelligence rather than")
            print("  nothing. The age of each value is printed beside it above, so")
            print("  stale data is never mistaken for fresh.")
        if unresolved:
            print(f"  {len(unresolved)} supplier(s) had no cached data and are now")
            print("  unset rather than defaulted to a clean value. An unreachable")
            print("  feed must never look like a good result.")
        if not identified:
            print("  No supplier carries identifiers, so nothing was looked up.")
    elif unresolved:
        print(f"  {len(unresolved)} of {len(identified)} supplier(s) had identifiers "
              f"but returned no signal — see the notes above for why.")
    else:
        print(f"  All {len(identified)} recorded identifier(s) resolved against "
              f"live feeds.")
    print(f"  {len(EXAMPLE_VENDORS) - len(identified)} supplier(s) carry no CVE or "
          f"repository and rest on questionnaire evidence alone.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
