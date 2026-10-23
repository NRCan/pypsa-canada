"""Hourly flow indexing, caching, and corridor flow resolution."""

import logging
import os
from glob import glob

import numpy as np
import pandas as pd

from .data import read_csv_flex
from .geometry import canonical_pair
from .settings import FORCE_TIME_COL

_hourly_cache: dict = {}


def detect_time_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """Infer timestamps, falling back to an hourly index starting in 2021."""
    if FORCE_TIME_COL and FORCE_TIME_COL in df.columns:
        t = pd.to_datetime(df[FORCE_TIME_COL], errors="coerce", utc=False)
        if t.notna().any():
            return pd.DatetimeIndex(t)

    for c in df.columns:
        if c.lower() in {"snapshot", "time", "timestamp", "datetime", "date"}:
            t = pd.to_datetime(df[c], errors="coerce", utc=False)
            if t.notna().any():
                return pd.DatetimeIndex(t)

    first_col = df.columns[0]
    t = pd.to_datetime(df[first_col], errors="coerce", utc=False)
    if t.notna().any():
        return pd.DatetimeIndex(t)

    return pd.date_range("2021-01-01 00:00:00", periods=len(df), freq="h")


def index_nodal_files(nodal_dir: str, pattern: str) -> dict:
    """Index hourly CSVs by the bus or province prefix before _hourly."""
    filepaths = glob(os.path.join(nodal_dir, pattern), recursive=True)
    if not filepaths:
        logging.warning(
            f"No nodal files found in {nodal_dir} with pattern {pattern}. Flow data will be unavailable."
        )
        return {}

    file_index = {}
    for filepath in filepaths:
        filename = os.path.basename(filepath)
        if "_hourly" in filename:
            stem = filename.split("_hourly")[0].strip()
            file_index[stem] = filepath
    return file_index


def _get_cached_hourly_df(bus: str, nodal_index: dict) -> pd.DataFrame | None:
    """Load and cache a bus or province hourly file, returning None if absent."""
    if bus in _hourly_cache:
        return _hourly_cache[bus]
    filepath = nodal_index.get(bus)
    if not filepath or not os.path.exists(filepath):
        _hourly_cache[bus] = None
        return None
    df = read_csv_flex(filepath)
    _hourly_cache[bus] = df
    return df


def find_flow_columns(df: pd.DataFrame, neighbor_key: str) -> list[str]:
    """Find transmission-flow columns starting with the neighbor key."""
    neighbor_key = str(neighbor_key).strip()
    return [
        c
        for c in df.columns
        if c.startswith(neighbor_key) and c.endswith("transmission_flow")
    ]


def _load_flow_from_side(
    source_key: str,
    target_key: str,
    nodal_index: dict,
    negate: bool = False,
):
    """Load and optionally negate the summed flow towards a neighbor."""
    df = _get_cached_hourly_df(source_key, nodal_index)
    if df is None:
        return None, None
    cols = find_flow_columns(df, target_key)
    if not cols:
        return None, None
    timestamps = detect_time_index(df)
    flow_mw = (
        df[cols]
        .apply(pd.to_numeric, errors="coerce")
        .fillna(0.0)
        .sum(axis=1)
        .to_numpy()
    )
    return timestamps, (-flow_mw if negate else flow_mw)


def get_corridor_flow(key0: str, key1: str, nodal_index: dict):
    """Load signed corridor flow, trying the opposite side with negated sign."""
    timestamps, flow_mw = _load_flow_from_side(key0, key1, nodal_index)
    if timestamps is not None:
        return timestamps, flow_mw
    return _load_flow_from_side(key1, key0, nodal_index, negate=True)


def load_link_flows(res_folder: str) -> tuple:
    """Load direct link or line flows aligned with network snapshots."""
    snap_path = os.path.join(res_folder, "snapshots.csv")
    links_p0 = os.path.join(res_folder, "links-p0.csv")
    lines_p0 = os.path.join(res_folder, "lines-p0.csv")
    if os.path.exists(links_p0):
        p0_path = links_p0
    elif os.path.exists(lines_p0):
        p0_path = lines_p0
    else:
        logging.info(
            "Neither links-p0.csv nor lines-p0.csv found; direct flow fallback unavailable."
        )
        return None, None

    flows = pd.read_csv(p0_path, index_col=0, encoding="utf-8-sig")
    flows.columns = [c.strip() for c in flows.columns]

    timestamps = None
    if os.path.exists(snap_path):
        snaps = read_csv_flex(snap_path)
        for col in ("timestep", "snapshot"):
            if col in snaps.columns:
                parsed = pd.to_datetime(snaps[col], errors="coerce")
                if parsed.notna().any():
                    timestamps = pd.DatetimeIndex(parsed)
                    break
    if timestamps is None or len(timestamps) != len(flows):
        timestamps = pd.date_range("2021-01-01 00:00:00", periods=len(flows), freq="h")

    flows.index = timestamps
    return timestamps, flows


def load_dispatch_link_flows(dispatch_folder: str) -> tuple:
    """Concatenate direct flows from dispatch year folders, or a flat layout."""
    year_dirs = sorted(
        os.path.join(dispatch_folder, e)
        for e in os.listdir(dispatch_folder)
        if e.isdigit() and os.path.isdir(os.path.join(dispatch_folder, e))
    )
    if not year_dirs:
        return load_link_flows(dispatch_folder)

    frames = []
    for ydir in year_dirs:
        _, yflows = load_link_flows(ydir)
        if yflows is not None:
            frames.append(yflows)

    if not frames:
        return None, None

    combined = pd.concat(frames)
    return pd.DatetimeIndex(combined.index), combined


def _bus_index_key(bus: str, bus_to_province: dict, nodal_index: dict) -> str:
    """Use the bus key in nodal mode, falling back to its province."""
    if bus in nodal_index:
        return bus
    return bus_to_province.get(bus, bus)


def resolve_corridor_flow(rows, nodal_index, bus_to_province):
    """Find corridor flow across physical lines, skipping duplicate region pairs."""
    seen = set()
    for line in rows:
        key0 = _bus_index_key(line["bus0"], bus_to_province, nodal_index)
        key1 = _bus_index_key(line["bus1"], bus_to_province, nodal_index)
        pair = canonical_pair(key0, key1)
        if pair in seen:
            continue
        seen.add(pair)
        timestamps, flow_mw = get_corridor_flow(key0, key1, nodal_index)
        if timestamps is not None:
            return line["bus0"], line["bus1"], timestamps, flow_mw
    return None, None, None, None
