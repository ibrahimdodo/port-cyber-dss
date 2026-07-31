#!/usr/bin/env python3
"""Day-one AIS validation run.

Purpose: prove the data assumption before committing to a multi-week download.
Three questions this answers, in order of how badly a wrong answer would hurt:

1. Does the DMA feed actually cover Bornholm? Rønne is 135 km east of the rest
   of Denmark, and the whole anchor-port choice rests on there being receiver
   coverage there.
2. Do the bounding boxes capture berths rather than passing traffic?
3. Does the file parse as the readme describes -- dayfirst timestamps, and
   period rather than comma decimals?

Usage
-----
    python scripts/day_one.py                    # most recent complete day
    python scripts/day_one.py --date 2026-03-02
    python scripts/day_one.py --keep-raw         # do not delete the CSV afterwards

Downloads roughly 600 MB and expands to several GB. The raw CSV is deleted
after processing unless --keep-raw is passed; the derived port calls are kept
as parquet, which is a few kilobytes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if importlib.util.find_spec("portscra") is None:  # not pip-installed; run in place
    sys.path.insert(0, str(REPO / "src"))

from portscra.ais import (  # noqa: E402
    CANDIDATE_PORTS,
    detect_port_calls,
    download_day,
    extract_csv,
    stream_port_points,
    summarise_calls,
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        type=lambda s: dt.datetime.strptime(s, "%Y-%m-%d").date(),
        default=dt.date.today() - dt.timedelta(days=5),
        help="Day to process (YYYY-MM-DD). Defaults to five days ago, since the "
             "most recent days are sometimes still being published.",
    )
    parser.add_argument("--data-dir", type=Path, default=REPO / "data")
    parser.add_argument("--keep-raw", action="store_true",
                        help="Keep the extracted CSV instead of deleting it.")
    parser.add_argument("--min-duration", type=float, default=1.0,
                        help="Minimum dwell in hours for a stop to count as a call.")
    return parser.parse_args()


def main():
    args = parse_args()
    raw_dir = args.data_dir / "raw"
    out_dir = args.data_dir / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=== Day-one AIS validation: {args.date} ===\n")

    print("[1/5] Downloading DMA daily archive")
    zip_path = download_day(args.date, raw_dir)

    print("\n[2/5] Extracting CSV")
    csv_path = extract_csv(zip_path, raw_dir)
    size_gb = csv_path.stat().st_size / 1e9
    print(f"  {csv_path.name} ({size_gb:.2f} GB)")

    print("\n[3/5] Streaming and filtering to candidate port areas")
    points = stream_port_points(csv_path, CANDIDATE_PORTS)

    if points.empty:
        print("\n  NO POINTS FOUND INSIDE ANY PORT AREA.")
        print("  Either the bounding boxes are wrong, or this day's file is")
        print("  incomplete. Check a known-busy port before adjusting Rønne.")
        return 1

    print("\n[4/5] Detecting port calls")
    window = (
        dt.datetime.combine(args.date, dt.time.min),
        dt.datetime.combine(args.date, dt.time.max),
    )
    calls = detect_port_calls(
        points, min_duration_hours=args.min_duration, window=window
    )
    summary = summarise_calls(calls)

    print("\n[5/5] Results\n")
    if summary.empty:
        print("  Points were found but no stop lasted long enough to count as a")
        print("  call. Try --min-duration 0.5, or widen the bounding boxes.")
    else:
        for _, row in summary.iterrows():
            print(f"  {row['port']:12s} {row['calls']:4d} calls  "
                  f"{row['distinct_vessels']:3d} vessels  "
                  f"{row['complete_calls']:3d} complete  "
                  f"mean dwell {row['mean_dwell_h']:.1f} h")
            if row["ship_types"]:
                types = ", ".join(f"{k} ({v})" for k, v in row["ship_types"].items())
                print(f"               types: {types}")

    points_path = out_dir / f"points-{args.date}.parquet"
    calls_path = out_dir / f"portcalls-{args.date}.parquet"
    points.to_parquet(points_path, index=False)
    if not calls.empty:
        calls.to_parquet(calls_path, index=False)
    print(f"\n  wrote {points_path.relative_to(REPO)}")
    if not calls.empty:
        print(f"  wrote {calls_path.relative_to(REPO)}")

    if not args.keep_raw:
        csv_path.unlink(missing_ok=True)
        print(f"  removed raw CSV (kept {zip_path.name})")

    # The verdict. This is the point of the whole script.
    print("\n--- Verdict ---")
    ronne = summary[summary["port"] == "ronne"] if not summary.empty else summary
    if not ronne.empty and int(ronne.iloc[0]["calls"]) > 0:
        print(f"  Bornholm has AIS coverage: {int(ronne.iloc[0]['calls'])} calls "
              f"detected at Rønne on a single day.")
        print("  Rønne is viable as the anchor port. Next: scale to four")
        print("  representative weeks across seasons.")
    else:
        print("  No calls detected at Rønne. Before abandoning it, check whether")
        print("  the fallback ports show traffic -- if they do, the problem is the")
        print("  Rønne bounding box; if none do, the problem is the pipeline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
