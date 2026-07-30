"""Turn raw AIS position reports into port calls.

A day of DMA AIS is roughly 25 million rows covering all Danish waters, of
which a few thousand concern any one small port. The pipeline is therefore:
stream the file in batches, discard everything outside a coarse bounding box
before it ever reaches pandas, then reconstruct port calls from what survives.

A "port call" here means a vessel sitting still inside the port footprint long
enough to be working cargo or passengers rather than merely drifting past.
Detection is deliberately simple and inspectable -- speed under a threshold, or
a navigational status of moored/anchored, sustained for a minimum duration with
tolerance for AIS dropouts. Sophistication would be misplaced: the output feeds
a consequence model whose other inputs are three-point expert estimates, so
false precision in the traffic statistics buys nothing.

The DMA readme documents 26 columns but is ambiguous about number formatting
(it shows latitudes as "57,8794", European style, in a comma-delimited file).
`sniff_csv` resolves that from the actual file rather than trusting the readme,
because getting it wrong silently produces empty results rather than an error.
"""

from __future__ import annotations

import csv as _csv
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
from pyarrow import csv as pacsv

from .ports import PortArea, union_bounds

__all__ = [
    "sniff_csv",
    "normalise_column",
    "stream_port_points",
    "detect_port_calls",
    "summarise_calls",
    "STATIONARY_STATUSES",
]

#: Navigational statuses that mean "not under way", regardless of reported speed.
#: AIS speed occasionally reports noise for a berthed vessel, so status is a
#: useful second opinion.
STATIONARY_STATUSES = {
    "moored",
    "at anchor",
    "aground",
}

#: Columns we keep. Everything else in the 26-column schema is dropped at read
#: time -- reading fewer columns is the single biggest speed win available here.
WANTED = (
    "timestamp",
    "type_of_mobile",
    "mmsi",
    "latitude",
    "longitude",
    "navigational_status",
    "sog",
    "name",
    "ship_type",
    "cargo_type",
    "width",
    "length",
    "draught",
    "destination",
)

#: Header variants seen in DMA files mapped to canonical names. The first column
#: is written "# Timestamp" in some vintages, and the vessel dimension columns
#: appear as either "Size A" or bare "A".
_ALIASES = {
    "#_timestamp": "timestamp",
    "a": "size_a",
    "b": "size_b",
    "c": "size_c",
    "d": "size_d",
}


def normalise_column(name: str) -> str:
    """Canonicalise a DMA header: lowercase, underscores, no leading hash."""
    clean = name.strip().lstrip("#").strip().lower()
    clean = clean.replace(" ", "_").replace("/", "_").replace("-", "_")
    while "__" in clean:
        clean = clean.replace("__", "_")
    return _ALIASES.get(clean, clean)


def sniff_csv(csv_path: Path | str, sample_lines: int = 5) -> dict:
    """Inspect the first few lines to determine delimiter and decimal mark.

    Returns a dict with ``delimiter``, ``decimal``, ``columns`` (canonicalised)
    and ``raw_columns``. Determining this from the file rather than assuming it
    is the difference between a working pipeline and one that silently yields
    zero rows because every latitude parsed as text.
    """
    csv_path = Path(csv_path)
    with open(csv_path, "r", encoding="utf-8", errors="replace") as handle:
        head = [handle.readline() for _ in range(sample_lines)]
    head = [line for line in head if line.strip()]
    if not head:
        raise ValueError(f"{csv_path} appears to be empty")

    try:
        dialect = _csv.Sniffer().sniff(head[0], delimiters=",;\t")
        delimiter = dialect.delimiter
    except _csv.Error:
        delimiter = ","

    raw_columns = [c.strip() for c in head[0].rstrip("\r\n").split(delimiter)]
    columns = [normalise_column(c) for c in raw_columns]

    # If a data row splits into more fields than the header has, the file is
    # using comma decimals inside a comma-delimited file, which cannot be parsed
    # positionally -- worth failing loudly rather than guessing.
    decimal = "."
    if len(head) > 1:
        field_counts = {
            len(line.rstrip("\r\n").split(delimiter)) for line in head[1:]
        }
        if field_counts and max(field_counts) > len(raw_columns):
            raise ValueError(
                f"{csv_path.name}: data rows have more fields ({max(field_counts)}) "
                f"than the header ({len(raw_columns)}). The file may use ',' as both "
                f"delimiter and decimal mark; inspect it manually."
            )
        if delimiter == ";":
            decimal = ","

    return {
        "delimiter": delimiter,
        "decimal": decimal,
        "columns": columns,
        "raw_columns": raw_columns,
    }


def stream_port_points(
    csv_path: Path | str,
    areas: tuple[PortArea, ...] | list[PortArea] | None = None,
    *,
    block_size: int = 64 * 1024 * 1024,
    verbose: bool = True,
) -> pd.DataFrame:
    """Stream a DMA daily CSV, keeping only reports inside the port areas.

    Returns a DataFrame of AIS points with a ``port`` column naming the area
    each point fell in. Memory stays flat regardless of file size: batches are
    filtered as they arrive and only survivors are retained.
    """
    from .ports import CANDIDATE_PORTS

    areas = tuple(areas) if areas else CANDIDATE_PORTS
    csv_path = Path(csv_path)
    fmt = sniff_csv(csv_path)

    lat_min, lat_max, lon_min, lon_max = union_bounds()

    available = set(fmt["columns"])
    missing = [c for c in ("timestamp", "mmsi", "latitude", "longitude") if c not in available]
    if missing:
        raise ValueError(
            f"{csv_path.name} is missing required columns {missing}. "
            f"Found: {sorted(available)}"
        )
    keep = [c for c in WANTED if c in available]

    read_options = pacsv.ReadOptions(
        block_size=block_size,
        column_names=fmt["columns"],
        skip_rows=1,  # we supply names ourselves, so drop the original header
    )
    parse_options = pacsv.ParseOptions(delimiter=fmt["delimiter"])
    convert_options = pacsv.ConvertOptions(
        include_columns=keep,
        # Timestamps are dayfirst and pyarrow will not guess that; read as
        # string and parse once, on the small filtered frame.
        column_types={"timestamp": pa.string(), "mmsi": pa.string()},
        strings_can_be_null=True,
        null_values=["", "NULL", "null", "Unknown", "unknown"],
    )

    frames: list[pd.DataFrame] = []
    rows_seen = 0
    reader = pacsv.open_csv(
        csv_path,
        read_options=read_options,
        parse_options=parse_options,
        convert_options=convert_options,
    )
    try:
        for batch in reader:
            rows_seen += batch.num_rows
            table = pa.Table.from_batches([batch])
            lat = table.column("latitude").to_numpy(zero_copy_only=False)
            lon = table.column("longitude").to_numpy(zero_copy_only=False)
            with np.errstate(invalid="ignore"):
                mask = (
                    (lat >= lat_min) & (lat <= lat_max)
                    & (lon >= lon_min) & (lon <= lon_max)
                )
            if not mask.any():
                continue
            frames.append(table.filter(pa.array(mask)).to_pandas())
    finally:
        reader.close()

    if verbose:
        print(f"  scanned {rows_seen:,} rows")

    if not frames:
        return pd.DataFrame(columns=list(keep) + ["port"])

    points = pd.concat(frames, ignore_index=True)
    points["timestamp"] = pd.to_datetime(
        points["timestamp"], format="%d/%m/%Y %H:%M:%S", errors="coerce"
    )
    bad = points["timestamp"].isna().sum()
    if bad:
        print(f"  warning: {bad:,} rows had unparseable timestamps and were dropped")
        points = points.dropna(subset=["timestamp"])

    # Assign each point to its specific port. Boxes are disjoint, so first match
    # wins and the loop is cheap.
    points["port"] = pd.NA
    lat_v = points["latitude"].to_numpy()
    lon_v = points["longitude"].to_numpy()
    for area in areas:
        inside = area.contains(lat_v, lon_v)
        points.loc[inside & points["port"].isna(), "port"] = area.key
    points = points.dropna(subset=["port"])

    if verbose:
        print(f"  kept {len(points):,} points inside port areas")
        for key, count in points["port"].value_counts().items():
            print(f"    {key}: {count:,}")

    return points.reset_index(drop=True)


def detect_port_calls(
    points: pd.DataFrame,
    *,
    speed_threshold: float = 0.5,
    min_duration_hours: float = 1.0,
    max_gap_minutes: float = 30.0,
    window: tuple[dt.datetime, dt.datetime] | None = None,
) -> pd.DataFrame:
    """Reconstruct port calls from filtered AIS points.

    A call is a maximal run of stationary reports from one vessel in one port,
    where consecutive reports are no more than `max_gap_minutes` apart, lasting
    at least `min_duration_hours`.

    Parameters
    ----------
    speed_threshold
        Speed over ground, in knots, below which a vessel counts as stopped.
        0.5 kn tolerates GPS jitter at a berth without admitting slow manoeuvres.
    min_duration_hours
        Minimum dwell for a run to count as a call. One hour excludes vessels
        pausing to await a berth or a bridge.
    max_gap_minutes
        Tolerated silence within a call. AIS reception drops out, especially
        behind quay structures; without this a single missed report would split
        one call into two.
    window
        The observation period the data covers, as (start, end). Calls touching
        either edge are flagged as truncated. Pass the actual file boundary --
        for a DMA daily extract, midnight to midnight. Defaults to the observed
        min and max timestamp, which is right for a full day but wrong for a
        sparse extract, where the last vessel present would otherwise always
        appear clipped simply for being last.

    Returns
    -------
    DataFrame with one row per call, including ``truncated_start`` and
    ``truncated_end`` flags. Those matter when processing a single day: a ferry
    berthed at midnight produces a call clipped by the file boundary, and dwell
    statistics computed over clipped calls are biased short.
    """
    required = {"timestamp", "mmsi", "port"}
    if not required.issubset(points.columns):
        raise ValueError(f"points is missing columns: {required - set(points.columns)}")

    if points.empty:
        return pd.DataFrame(
            columns=[
                "port", "mmsi", "name", "ship_type", "cargo_type",
                "arrival", "departure", "dwell_hours", "n_messages",
                "length", "width", "draught", "destination",
                "truncated_start", "truncated_end",
            ]
        )

    df = points.copy()

    status = df.get("navigational_status", pd.Series("", index=df.index))
    status = status.fillna("").astype(str).str.strip().str.lower()
    sog = pd.to_numeric(df.get("sog", np.nan), errors="coerce")

    df["stationary"] = (sog < speed_threshold) | status.isin(STATIONARY_STATUSES)
    stopped = df[df["stationary"]].sort_values(["port", "mmsi", "timestamp"])
    if stopped.empty:
        return detect_port_calls(points.iloc[0:0])

    # A new run starts whenever the vessel or port changes, or the silence since
    # the previous report exceeds the tolerated gap.
    key_changed = (
        stopped["mmsi"].ne(stopped["mmsi"].shift())
        | stopped["port"].ne(stopped["port"].shift())
    )
    gap = stopped["timestamp"].diff().dt.total_seconds().div(60.0)
    run_id = (key_changed | (gap > max_gap_minutes)).cumsum()

    if window is not None:
        day_start, day_end = window
    else:
        day_start = points["timestamp"].min()
        day_end = points["timestamp"].max()

    def _first_valid(series: pd.Series):
        cleaned = series.dropna()
        return cleaned.iloc[-1] if len(cleaned) else pd.NA

    records = []
    for _, run in stopped.groupby(run_id, sort=False):
        arrival = run["timestamp"].iloc[0]
        departure = run["timestamp"].iloc[-1]
        dwell = (departure - arrival).total_seconds() / 3600.0
        if dwell < min_duration_hours:
            continue

        records.append(
            {
                "port": run["port"].iloc[0],
                "mmsi": run["mmsi"].iloc[0],
                "name": _first_valid(run["name"]) if "name" in run else pd.NA,
                "ship_type": _first_valid(run["ship_type"]) if "ship_type" in run else pd.NA,
                "cargo_type": _first_valid(run["cargo_type"]) if "cargo_type" in run else pd.NA,
                "arrival": arrival,
                "departure": departure,
                "dwell_hours": dwell,
                "n_messages": len(run),
                "length": _first_valid(run["length"]) if "length" in run else pd.NA,
                "width": _first_valid(run["width"]) if "width" in run else pd.NA,
                "draught": _first_valid(run["draught"]) if "draught" in run else pd.NA,
                "destination": _first_valid(run["destination"]) if "destination" in run else pd.NA,
                # Within one minute of the file boundary the call is very likely
                # clipped rather than genuinely starting or ending there.
                "truncated_start": (arrival - day_start).total_seconds() < 60,
                "truncated_end": (day_end - departure).total_seconds() < 60,
            }
        )

    calls = pd.DataFrame.from_records(records)
    if not calls.empty:
        calls = calls.sort_values(["port", "arrival"]).reset_index(drop=True)
    return calls


def summarise_calls(calls: pd.DataFrame) -> pd.DataFrame:
    """Per-port summary of a set of detected calls.

    Dwell statistics deliberately exclude truncated calls. On a single day most
    long calls are clipped by the file boundary, so including them would drag
    the mean down and understate how long an outage would need to last before
    it began turning vessels away.
    """
    if calls.empty:
        return pd.DataFrame(
            columns=["port", "calls", "distinct_vessels", "complete_calls",
                     "mean_dwell_h", "median_dwell_h", "ship_types"]
        )

    rows = []
    for port, group in calls.groupby("port"):
        complete = group[~group["truncated_start"] & ~group["truncated_end"]]
        types = (
            group["ship_type"].dropna().astype(str).value_counts().head(5).to_dict()
            if "ship_type" in group
            else {}
        )
        rows.append(
            {
                "port": port,
                "calls": len(group),
                "distinct_vessels": group["mmsi"].nunique(),
                "complete_calls": len(complete),
                "mean_dwell_h": round(float(complete["dwell_hours"].mean()), 2)
                if len(complete)
                else float("nan"),
                "median_dwell_h": round(float(complete["dwell_hours"].median()), 2)
                if len(complete)
                else float("nan"),
                "ship_types": types,
            }
        )
    return pd.DataFrame(rows).sort_values("calls", ascending=False).reset_index(drop=True)
