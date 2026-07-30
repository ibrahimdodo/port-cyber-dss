"""Fetch daily AIS archives from the Danish Maritime Authority.

The DMA publishes one zip per day covering all Danish waters, free and without
registration, at http://aisdata.ais.dk (an S3 bucket behind a static index).
Recent days sit at the bucket root; older ones live in year folders, which hold
both monthly bundles and the same daily files. We only ever want dailies -- the
monthly bundles are ~17 GB for data we would immediately filter away.

Files are large (roughly 550-750 MB zipped, expanding to several GB of CSV with
around 25 million rows), so downloads are cached on disk and skipped if already
present. Nothing here parses AIS; see `portcalls.py` for that.
"""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

import requests

__all__ = ["daily_url", "download_day", "extract_csv", "BUCKET_URL"]

BUCKET_URL = "http://aisdata.ais.dk"

#: Days at or after this date are served from the bucket root; earlier days come
#: from the year folder. Verified against the live listing 2026-07-29 (root held
#: 2025-02-27 onwards). If a download 404s, this boundary is the first suspect.
ROOT_CUTOFF = dt.date(2025, 2, 27)


def daily_url(day: dt.date) -> str:
    """URL of the DMA daily archive for `day`."""
    name = f"aisdk-{day:%Y-%m-%d}.zip"
    if day >= ROOT_CUTOFF:
        return f"{BUCKET_URL}/{name}"
    return f"{BUCKET_URL}/{day.year}/{name}"


def download_day(
    day: dt.date,
    dest_dir: Path | str,
    *,
    chunk_size: int = 8 * 1024 * 1024,
    progress: bool = True,
) -> Path:
    """Download one day's AIS archive, caching by filename.

    Returns the path to the local zip. Re-running is cheap: an existing file of
    non-zero size is returned untouched. Partial downloads are written to a
    `.part` file and only renamed on success, so an interrupted run cannot leave
    a truncated archive that later looks like a valid cache hit.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    url = daily_url(day)
    target = dest_dir / f"aisdk-{day:%Y-%m-%d}.zip"

    if target.exists() and target.stat().st_size > 0:
        if progress:
            print(f"  cached: {target.name} ({target.stat().st_size / 1e6:.0f} MB)")
        return target

    partial = target.with_suffix(".zip.part")
    if progress:
        print(f"  downloading {url}")

    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length", 0))
        written = 0
        with open(partial, "wb") as handle:
            for chunk in response.iter_content(chunk_size=chunk_size):
                handle.write(chunk)
                written += len(chunk)
                if progress and total:
                    pct = 100.0 * written / total
                    print(
                        f"\r  {written / 1e6:7.0f} / {total / 1e6:.0f} MB ({pct:5.1f}%)",
                        end="",
                        flush=True,
                    )
    if progress:
        print()

    partial.rename(target)
    return target


def extract_csv(zip_path: Path | str, dest_dir: Path | str | None = None) -> Path:
    """Extract the single CSV from a DMA daily archive.

    DMA archives contain one CSV named like the archive. Returns its path,
    skipping extraction if it is already on disk.
    """
    zip_path = Path(zip_path)
    dest_dir = Path(dest_dir) if dest_dir else zip_path.parent
    dest_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".csv")]
        if not members:
            raise ValueError(f"no CSV inside {zip_path.name}: {archive.namelist()}")
        if len(members) > 1:
            raise ValueError(f"expected one CSV in {zip_path.name}, found {members}")

        member = members[0]
        target = dest_dir / Path(member).name
        if target.exists() and target.stat().st_size > 0:
            return target

        print(f"  extracting {member} ...")
        with archive.open(member) as src, open(target, "wb") as dst:
            while chunk := src.read(8 * 1024 * 1024):
                dst.write(chunk)

    return target
