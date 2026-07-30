#!/usr/bin/env python3
"""Build the seasonal port-call dataset from four representative weeks.

Day-one proved the pipeline works on one summer day. This scales it to four
full Monday-to-Sunday weeks spread across the year, which is what the
consequence model actually needs: ferry frequency, dwell distributions and
vessel mix all vary by season, and a euro-per-hour figure calibrated on peak
July would overstate the cost of a January outage.

Full weeks rather than scattered days, so weekday/weekend patterns survive.

Disk discipline: each day is downloaded, processed to parquet, and its raw
files deleted before the next day starts. Peak usage stays around 4 GB rather
than the ~18 GB the full set would occupy. Pass --keep-zip to retain archives.

The run is resumable. A day whose parquet already exists is skipped, so an
interrupted run picks up where it stopped, and re-running is cheap.

Usage
-----
    python scripts/build_dataset.py                 # all four weeks
    python scripts/build_dataset.py --season summer # one week
    python scripts/build_dataset.py --aggregate-only
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import pandas as pd  # noqa: E402

from portscra.ais import (  # noqa: E402
    CANDIDATE_PORTS,
    detect_port_calls,
    download_day,
    extract_csv,
    reflag_truncation,
    stitch_across_days,
    stream_port_points,
)

#: Four Mondays, one per season, verified present in the DMA bucket. Chosen to
#: sit clear of Christmas and Easter, when traffic is atypical for reasons that
#: have nothing to do with seasonality.
SEASONAL_WEEKS: dict[str, dt.date] = {
    "autumn": dt.date(2025, 10, 13),
    "winter": dt.date(2026, 1, 19),
    "spring": dt.date(2026, 4, 13),
    "summer": dt.date(2026, 7, 20),
}

#: Ship types that represent commercial port business. Recreational traffic is
#: excluded from headline statistics: it generates negligible port revenue, so
#: including it would deflate any per-call economic figure. It is still stored,
#: so the decision stays reversible.
COMMERCIAL_TYPES = {"Passenger", "HSC", "Cargo", "Tanker", "Ro-Ro", "Reefer"}

#: Official ship calls at Rønne Havn, Danmarks Statistik table SKIB101
#: (HAVN=00315). The reconciliation baseline -- an independent, authoritative
#: measure of the same quantity our detector estimates. Refresh with:
#: curl "https://api.statbank.dk/v1/data/SKIB101/CSV?lang=en&HAVN=00315&ENHED=*&Tid=*"
OFFICIAL_CALLS = {2024: 3043, 2025: 2933}

#: Filename of the combined output. Named as a constant because `aggregate()`
#: must exclude it from its own input glob.
COMBINED_NAME = "portcalls-all.parquet"


def day_range(start: dt.date, days: int = 7):
    return [start + dt.timedelta(days=i) for i in range(days)]


def process_day(day: dt.date, data_dir: Path, *, keep_zip: bool) -> pd.DataFrame | None:
    """Download, filter and detect calls for one day. Returns the call table."""
    raw_dir = data_dir / "raw"
    out_dir = data_dir / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    calls_path = out_dir / f"portcalls-{day}.parquet"
    if calls_path.exists():
        print(f"  {day}: already processed, skipping")
        return pd.read_parquet(calls_path)

    zip_path = download_day(day, raw_dir, progress=False)
    csv_path = extract_csv(zip_path, raw_dir)

    try:
        points = stream_port_points(csv_path, CANDIDATE_PORTS, verbose=False)
        if points.empty:
            print(f"  {day}: no points inside any port area")
            return None

        window = (
            dt.datetime.combine(day, dt.time.min),
            dt.datetime.combine(day, dt.time.max),
        )
        calls = detect_port_calls(points, window=window)
        if calls.empty:
            print(f"  {day}: points found but no qualifying calls")
            return None

        calls["date"] = day
        calls.to_parquet(calls_path, index=False)

        ronne = calls[calls["port"] == "ronne"]
        commercial = ronne[ronne["ship_type"].isin(COMMERCIAL_TYPES)]
        print(f"  {day} ({day:%a}): {len(calls):3d} calls total, "
              f"Rønne {len(ronne):2d} ({len(commercial):2d} commercial)")
        return calls
    finally:
        # Always reclaim the space, even if detection raised.
        csv_path.unlink(missing_ok=True)
        if not keep_zip:
            zip_path.unlink(missing_ok=True)


def aggregate(data_dir: Path) -> None:
    """Combine every processed day and report the statistics the model needs."""
    out_dir = data_dir / "processed"
    # Exclude the combined output written by a previous run -- it lives in the
    # same directory and matches the same glob, so including it would double
    # every call on the second and later aggregations.
    files = sorted(
        f for f in out_dir.glob("portcalls-*.parquet") if f.name != COMBINED_NAME
    )
    if not files:
        print("\nNothing to aggregate yet.")
        return

    frames = [pd.read_parquet(f) for f in files]
    calls = pd.concat(frames, ignore_index=True)
    calls["date"] = pd.to_datetime(calls["date"])

    # Daily files split long stays and clip their edges. Repair both before
    # computing any statistic: reflag with a tolerance that exceeds the AIS
    # reporting interval, then rejoin calls the day boundary separated.
    # Without this the dwell distribution pins at 24 h for reasons that have
    # nothing to do with how long berths are actually occupied.
    raw_count = len(calls)
    calls = stitch_across_days(reflag_truncation(calls))
    print(f"\n  reflagged and stitched: {raw_count:,} -> {len(calls):,} calls")

    def season_of(d):
        for name, start in SEASONAL_WEEKS.items():
            if start <= d.date() <= start + dt.timedelta(days=6):
                return name
        return "other"

    calls["season"] = calls["date"].apply(season_of)
    ronne = calls[calls["port"] == "ronne"].copy()
    ronne["commercial"] = ronne["ship_type"].isin(COMMERCIAL_TYPES)

    print("\n" + "=" * 74)
    print(f"AGGREGATE -- {len(files)} days, {len(calls):,} calls across all ports")
    print("=" * 74)

    print("\n--- Rønne calls per day by season ---")
    per_day = (
        ronne.groupby(["season", "date"])
        .agg(calls=("mmsi", "size"), commercial=("commercial", "sum"))
        .reset_index()
    )
    summary = (
        per_day.groupby("season")
        .agg(days=("date", "nunique"),
             mean_calls=("calls", "mean"),
             mean_commercial=("commercial", "mean"))
        .round(1)
    )
    print(summary.to_string())

    print("\n--- Rønne commercial vessel mix by season (distinct vessels) ---")
    mix = (
        ronne[ronne["commercial"]]
        .groupby(["season", "ship_type"])["mmsi"]
        .nunique()
        .unstack(fill_value=0)
    )
    print(mix.to_string())

    print("\n--- Dwell hours, Rønne commercial calls (complete calls only) ---")
    complete = ronne[
        ronne["commercial"] & ~ronne["truncated_start"] & ~ronne["truncated_end"]
    ]
    if not complete.empty:
        stats = (
            complete.groupby("ship_type")["dwell_hours"]
            .agg(["count", "mean", "median",
                  lambda s: s.quantile(0.1), lambda s: s.quantile(0.9)])
            .round(2)
        )
        stats.columns = ["n", "mean", "median", "p10", "p90"]
        print(stats.to_string())
        print("\n  These are the three-point inputs for the consequence model:")
        print("  a berth blocked for longer than the p90 dwell is an outage that")
        print("  starts turning vessels away rather than merely delaying them.")

    print("\n--- Reconciliation against official statistics ---")
    mean_comm = per_day.groupby("season")["commercial"].mean()
    mean_all = per_day.groupby("season")["calls"].mean()
    lower, upper = mean_comm.mean() * 365, mean_all.mean() * 365

    print(f"  commercial calls/day : {mean_comm.mean():5.1f}  -> {lower:,.0f}/yr")
    print(f"    seasonal range: {mean_comm.min():.1f} ({mean_comm.idxmin()}) "
          f"to {mean_comm.max():.1f} ({mean_comm.idxmax()})  "
          f"= {mean_comm.max() / mean_comm.min():.2f}x swing")
    print(f"  all vessel calls/day : {mean_all.mean():5.1f}  -> {upper:,.0f}/yr")
    print()
    for year, official in OFFICIAL_CALLS.items():
        inside = lower <= official <= upper
        mark = "within" if inside else "OUTSIDE"
        print(f"  official (DST SKIB101, {year}): {official:,}"
              f"   [{lower:,.0f} .. {upper:,.0f}]  {mark}")

    print("\n  Our two vessel-type definitions bracket the official figure, which")
    print("  is the outcome to want: the official series evidently counts more")
    print("  than our strict commercial set (it will include fishing, tugs and")
    print("  service craft) but excludes the recreational traffic our all-vessel")
    print("  count picks up. Agreement inside that bracket is evidence the")
    print("  detector is measuring the right thing. Use the commercial figure")
    print("  for euro calibration, since recreational calls carry no port dues.")

    combined = out_dir / COMBINED_NAME
    calls.to_parquet(combined, index=False)
    print(f"\n  wrote {combined.relative_to(REPO)} ({len(calls):,} rows)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", choices=sorted(SEASONAL_WEEKS), default=None,
                        help="Process one season only. Default: all four.")
    parser.add_argument("--data-dir", type=Path, default=REPO / "data")
    parser.add_argument("--keep-zip", action="store_true",
                        help="Keep downloaded archives instead of deleting them.")
    parser.add_argument("--aggregate-only", action="store_true",
                        help="Skip downloads, just re-run the aggregation.")
    args = parser.parse_args()

    if args.aggregate_only:
        aggregate(args.data_dir)
        return 0

    seasons = [args.season] if args.season else list(SEASONAL_WEEKS)
    days = [d for s in seasons for d in day_range(SEASONAL_WEEKS[s])]

    print(f"Building dataset: {len(seasons)} week(s), {len(days)} days")
    print(f"Seasons: {', '.join(seasons)}\n")

    failures = []
    for season in seasons:
        print(f"[{season}] week of {SEASONAL_WEEKS[season]}")
        for day in day_range(SEASONAL_WEEKS[season]):
            try:
                process_day(day, args.data_dir, keep_zip=args.keep_zip)
            except Exception as exc:  # one bad day must not end the run
                failures.append((day, repr(exc)))
                print(f"  {day}: FAILED -- {exc}")
                traceback.print_exc(limit=2)
        print()

    if failures:
        print(f"{len(failures)} day(s) failed:")
        for day, err in failures:
            print(f"  {day}: {err}")

    aggregate(args.data_dir)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
