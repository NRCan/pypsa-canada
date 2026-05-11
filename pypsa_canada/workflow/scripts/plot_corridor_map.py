"""
Plot corridor utilization on an interactive Folium map.

Snakemake script: reads the planning solved network (buses, lines/links) and the
post-processing output (hourly energy-balance CSVs) to draw every transmission
corridor as a curved PolyLine coloured by flow availability. Corridors that have
flow data show a Plotly utilization chart in the popup; corridors without flow
data (e.g. intra-provincial lines in provincial post-processing mode) are drawn
in grey with a lightweight metadata popup.

Post-processing CSVs are keyed by province code (or by bus name when no
``province`` column is present).  Bus-to-province mapping from ``buses.csv``
is applied uniformly; there is no separate nodal vs provincial code path.
"""

import logging
import math
import os
import re
import sys
import traceback
from collections import defaultdict
from glob import glob

import folium
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from helpers import setup_script_logging

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/plot_corridor_map.log"

setup_script_logging(LOG_PATH)

# ---------------------------------------------------------------------------
# Geometry / layout constants (tune in the rule params if needed)
# ---------------------------------------------------------------------------

# popup
POPUP_WIDTH = 760
POPUP_HEIGHT = 520

# if you know exact timestamp column name in nodal csv, set it
FORCE_TIME_COL = None  # e.g. "snapshot"

# curve geometry (meters)
CURVE_OFFSET_M = 3500.0
PARALLEL_STEP_M = 1800.0  # spacing between parallel physical lines inside ONE corridor
SELF_LOOP_RADIUS_M = 2500.0
SELF_LOOP_STEP_M = 900.0  # spacing for multiple self-loops at same bus

# IMPORTANT: jitter buses that share identical coords (so A315/A735 don't overlap)
BUS_JITTER_M = 900.0  # meters (tune 400-1500)
BUS_JITTER_MODE = "suffix_voltage"  # "suffix_voltage" | "v_nom" | "name_only"

POST_PROCESS_FILE_GLOB = "**/*_hourly*.csv"  # e.g., AB_hourly.csv

LINE_COLOR_WITH_DATA = "#3388ff"  # Blue for existing lines with flow data
LINE_COLOR_NO_DATA = "#888888"  # Grey for existing lines without flow data
LINE_COLOR_NEW = "#22bb44"  # Green for newly built lines with flow data
LINE_COLOR_NEW_NO_DATA = "#99bb88"  # Muted green-grey for new lines without flow data


# =============================================================================
# HELPERS
# =============================================================================
def read_csv_flex(path: str) -> pd.DataFrame:
    """
    Read a CSV file with UTF-8-BOM tolerance and strip column-name whitespace.

    Parameters
    ----------
    path : str
        Path to the CSV file.

    Returns
    -------
    pd.DataFrame
    """
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    return df


def detect_time_index(df: pd.DataFrame) -> pd.DatetimeIndex:
    """
    Infer a DatetimeIndex from a DataFrame.

    Looks for a time column by name (``snapshot``, ``time``, ``timestamp``,
    ``datetime``, ``date``, or the value of ``FORCE_TIME_COL``), then falls
    back to the first column, and finally synthesises a 1-hour index starting
    at 2021-01-01 if nothing parseable is found.

    Parameters
    ----------
    df : pd.DataFrame

    Returns
    -------
    pd.DatetimeIndex
    """
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
    """
    Build a ``{key: filepath}`` index of hourly CSV files.

    The key is derived from the filename stem before ``_hourly``, which is
    either a bus name (nodal mode) or a province code (provincial mode).

    Parameters
    ----------
    nodal_dir : str
        Root directory to search recursively.
    pattern : str
        Glob pattern relative to *nodal_dir*, e.g. ``**/*_hourly*.csv``.

    Returns
    -------
    dict
        ``{stem: absolute_path}`` mapping.  Empty dict if no files are found.
    """
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


_hourly_cache: dict = {}


def _get_cached_hourly_df(bus: str, nodal_index: dict) -> pd.DataFrame | None:
    """
    Load and cache the hourly DataFrame for *bus* from *nodal_index*.

    Parameters
    ----------
    bus : str
        Key into *nodal_index* (bus name or province code).
    nodal_index : dict
        ``{key: filepath}`` mapping produced by :func:`index_nodal_files`.

    Returns
    -------
    pd.DataFrame or None
        ``None`` if the key is absent or the file does not exist.
    """
    if bus in _hourly_cache:
        return _hourly_cache[bus]
    filepath = nodal_index.get(bus)
    if not filepath or not os.path.exists(filepath):
        _hourly_cache[bus] = None
        return None
    df = read_csv_flex(filepath)
    _hourly_cache[bus] = df
    return df

def _dispatch_topology_folder(dispatch_folder: str) -> str:
    """
    Return the subfolder containing the dispatch network topology files.

    The dispatch solved network stores each investment-period year in a
    separate subfolder (``2021/``, ``2025/``, …).  The last (chronologically
    latest) year contains the most complete set of built lines and is used as
    the topology reference.  If no year subfolders exist the dispatch folder
    itself is returned.

    Parameters
    ----------
    dispatch_folder : str

    Returns
    -------
    str
    """
    year_dirs = sorted(
        os.path.join(dispatch_folder, e)
        for e in os.listdir(dispatch_folder)
        if os.path.isdir(os.path.join(dispatch_folder, e)) and e.isdigit()
    )
    return year_dirs[-1] if year_dirs else dispatch_folder




def canonical_pair(a: str, b: str):
    """
    Return a sorted 2-tuple of bus names for use as a corridor dict key.
    """
    return tuple(sorted([str(a).strip(), str(b).strip()]))


def line_voltage_kv(name: str):
    """
    Extract a trailing kV integer from a line name (e.g. ``line_1_2_315`` -> 315).

    Returns ``None`` if no 2-to-4 digit suffix is found.
    """
    m = re.search(r"_(\d{2,4})\s*$", str(name).strip())
    return int(m.group(1)) if m else None


def voltage_mix_label(kvs):
    """
    Format a human-readable voltage label from a collection of kV values.

    Parameters
    ----------
    kvs : iterable
        Integer kV values; ``None`` entries are ignored.

    Returns
    -------
    str
        E.g. ``"315 kV"``, ``"315+735 kV"``, or ``"mixed kV"``.
    """
    kvs = sorted({k for k in kvs if k is not None})
    if not kvs:
        return "mixed kV"
    if len(kvs) == 1:
        return f"{kvs[0]} kV"
    return f"{'+'.join(map(str, kvs))} kV"


def bus_voltage_kv(bus_name: str):
    """
    Extract a trailing voltage integer from a bus name (e.g. ``A315`` -> 315).

    Returns ``None`` if no 2-to-4 digit suffix is found.
    """
    m = re.search(r"(\d{2,4})\s*$", str(bus_name).strip())
    return int(m.group(1)) if m else None


def jitter_bus(lat, lon, position, group_size, jitter_m):
    """
    Spread buses around a circle deterministically so co-located buses do not overlap.

    Parameters
    ----------
    lat : float
    lon : float
    position : int
        Index of this bus in the co-located group.
    group_size : int
        Total number of buses sharing this coordinate.
    jitter_m : float
        Radius of the jitter circle in metres.

    Returns
    -------
    tuple[float, float]
        Jittered ``(lat, lon)``.
    """
    if group_size <= 1:
        return lat, lon
    angle = 2 * math.pi * (position / group_size)
    dlat = (jitter_m / 111320.0) * math.cos(angle)
    dlon = (jitter_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))) * math.sin(
        angle
    )
    return lat + dlat, lon + dlon


# =============================================================================
# FLOW: sum ALL matching columns for neighbor (handles parallel flows)
# =============================================================================
def find_flow_columns(df: pd.DataFrame, neighbor_key: str) -> list[str]:
    """
    Return column names in *df* that carry flow towards *neighbor_key*.

    Columns must start with *neighbor_key* and end with ``transmission_flow``.

    Parameters
    ----------
    df : pd.DataFrame
        Hourly energy-balance DataFrame for the source province.
    neighbor_key : str
        Province code of the neighboring province.

    Returns
    -------
    list[str]
    """
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
    """
    Load the hourly flow from *source_key* towards *target_key*.

    Parameters
    ----------
    source_key : str
        Province code whose hourly file is opened.
    target_key : str
        Province code of the neighbor, used to select transmission-flow columns.
    nodal_index : dict
    negate : bool
        When ``True`` the returned flow array is sign-flipped.

    Returns
    -------
    tuple[pd.DatetimeIndex, np.ndarray] or tuple[None, None]
    """
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
    """
    Retrieve the signed hourly flow time-series from *key0* to *key1*.

    Tries *key0*'s hourly file first (columns starting with *key1*), then
    *key1*'s file with negated sign.

    Parameters
    ----------
    key0 : str
        Province code of the source side.
    key1 : str
        Province code of the destination side.
    nodal_index : dict
        ``{key: filepath}`` mapping from :func:`index_nodal_files`.

    Returns
    -------
    tuple[pd.DatetimeIndex, np.ndarray] or tuple[None, None]
        ``(timestamps, flow_mw)`` or ``(None, None)`` if no data found.
    """
    timestamps, flow_mw = _load_flow_from_side(key0, key1, nodal_index)
    if timestamps is not None:
        return timestamps, flow_mw
    return _load_flow_from_side(key1, key0, nodal_index, negate=True)


# =============================================================================
# CURVE GEOMETRY (no-overlap for parallels)
# =============================================================================
def bearing(lat1, lon1, lat2, lon2):
    dlon = math.radians(lon2 - lon1)
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(
        lat2r
    ) * math.cos(dlon)
    return math.atan2(y, x)


def offset_point(lat, lon, theta, offset_m, sign=1):
    dlat = (offset_m / 111320.0) * sign
    dlon = (offset_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))) * sign
    return lat + dlat * math.cos(theta), lon + dlon * math.sin(theta)


def offset_midpoint(lat1, lon1, lat2, lon2, offset_m=3000.0, sign=1):
    latm = (lat1 + lat2) / 2.0
    lonm = (lon1 + lon2) / 2.0
    theta = bearing(lat1, lon1, lat2, lon2) + math.pi / 2.0
    return offset_point(latm, lonm, theta, offset_m, sign=sign)


def approx_distance_m(lat1, lon1, lat2, lon2):
    # quick equirectangular approximation
    R = 6371000.0
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2.0))
    y = math.radians(lat2 - lat1)
    return R * math.sqrt(x * x + y * y)


def make_curve(
    lat1, lon1, lat2, lon2, offset_m, sign=1, self_loop_radius_m=SELF_LOOP_RADIUS_M
):
    # self-loop: draw a little loop around the bus with adjustable radius
    if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
        return [
            offset_point(lat1, lon1, ang, self_loop_radius_m)
            for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2, 0)
        ]
    latc, lonc = offset_midpoint(lat1, lon1, lat2, lon2, offset_m=offset_m, sign=sign)
    return [(lat1, lon1), (latc, lonc), (lat2, lon2)]


def parallel_offsets(n: int, base_offset_m: float, step_m: float):
    """
    Generate alternating signed offsets for drawing parallel lines in one corridor.

    Offsets follow the sequence: +base, -(base+step), +(base+step), -(base+2*step), ...
    so no two lines share the same lateral position.

    Parameters
    ----------
    n : int
        Number of parallel lines.
    base_offset_m : float
        Offset magnitude for the first line (metres).
    step_m : float
        Additional separation between successive pairs (metres).

    Returns
    -------
    list[tuple[int, float]]
        List of ``(sign, offset_m)`` pairs, length *n*.
    """
    offsets = [(+1, base_offset_m)]
    for k in range(1, n):
        sign = -1 if k % 2 == 1 else +1
        extra = ((k + 1) // 2) * step_m
        offsets.append((sign, base_offset_m + extra))
    return offsets


# =============================================================================
# PLOT: utilization-only + clean layout
# =============================================================================
def build_util_plot_html(time_index, flow_signed, cap_sum, title, subtitle):
    """
    Build a self-contained Plotly utilization chart as an HTML fragment.

    Parameters
    ----------
    time_index : pd.DatetimeIndex
    flow_signed : array-like
        Signed flow in MW.
    cap_sum : float
        Sum of ``s_nom`` for the corridor (MW).  Used as denominator.
    title : str
        Chart title (corridor label).
    subtitle : str
        Secondary title line (flow orientation, sum(s_nom)).

    Returns
    -------
    str
        HTML string (``full_html=False``, Plotly loaded via CDN).
    """
    flow_signed = np.asarray(flow_signed, dtype=float)

    if cap_sum and cap_sum > 0:
        util = np.abs(flow_signed) / cap_sum
    else:
        util = np.full_like(flow_signed, np.nan, dtype=float)

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=time_index,
            y=util,
            mode="lines",
            name="Utilization |flow|/sum(s_nom) (p.u.)",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=[time_index.min(), time_index.max()],
            y=[1.0, 1.0],
            mode="lines",
            name="1.0 p.u. (corridor rating)",
            line=dict(dash="dash"),
        )
    )
    fig.update_layout(
        title=dict(
            text=f"{title}<br><span style='font-size:12px'>{subtitle}</span>",
            x=0.01,
            xanchor="left",
        ),
        height=380,
        margin=dict(l=50, r=30, t=95, b=45),
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="left", x=0.0),
        xaxis=dict(title="Time"),
        yaxis=dict(title="Utilization (p.u.)", rangemode="tozero"),
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn")


def build_popup_html(info_html: str, plot_html: str):
    """
    Wrap corridor metadata and a Plotly chart into a single popup HTML block.

    Parameters
    ----------
    info_html : str
        Pre-formatted HTML snippet with corridor metadata.
    plot_html : str
        HTML fragment from :func:`build_util_plot_html`.

    Returns
    -------
    str
    """
    return f"""
    <div style="font-family: Arial, sans-serif; font-size: 13px; line-height: 1.25;">
      <div style="padding:8px 10px; border:1px solid #ddd; border-radius:6px; margin-bottom:10px;">
        {info_html}
      </div>
      {plot_html}
    </div>
    """


# =============================================================================
# LOAD / PROCESS
# =============================================================================
def load_buses(buses_csv: str) -> tuple[dict, dict, dict]:
    """
    Load bus coordinates and metadata from ``buses.csv``.

    Applies a circular jitter to buses that share identical coordinates so
    they do not overlap on the map.

    Parameters
    ----------
    buses_csv : str
        Path to ``buses.csv``.  Must contain ``name``, ``x``, ``y`` columns.

    Returns
    -------
    bus_ll : dict
        ``{bus_name: (lat, lon)}`` with jitter applied.
    bus_v_nom : dict
        ``{bus_name: v_nom_kV}``; empty if ``v_nom`` column absent.
    bus_to_province : dict
        ``{bus_name: province_code}``; empty if ``province`` column absent.
        Used for provincial post-processing mode.
    """
    buses = read_csv_flex(buses_csv)
    need = {"name", "x", "y"}
    if not need.issubset(buses.columns):
        raise ValueError(
            f"buses.csv must contain {need}. Found: {buses.columns.tolist()}"
        )

    buses["name"] = buses["name"].astype(str).str.strip()
    buses["x"] = pd.to_numeric(buses["x"], errors="coerce")
    buses["y"] = pd.to_numeric(buses["y"], errors="coerce")
    buses = buses.dropna(subset=["x", "y"]).copy()

    raw_coords = {
        r["name"]: (float(r["y"]), float(r["x"])) for _, r in buses.iterrows()
    }

    bus_v_nom = {}
    if "v_nom" in buses.columns:
        tmp = buses[["name", "v_nom"]].copy()
        tmp["v_nom"] = pd.to_numeric(tmp["v_nom"], errors="coerce")
        bus_v_nom = {
            str(r["name"]).strip(): (
                float(r["v_nom"]) if pd.notna(r["v_nom"]) else None
            )
            for _, r in tmp.iterrows()
        }

    # Build bus -> province mapping for provincial post-processing mode
    bus_to_province: dict = {}
    if "province" in buses.columns:
        bus_to_province = {
            str(r["name"]).strip(): str(r["province"]).strip()
            for _, r in buses.iterrows()
            if pd.notna(r["province"])
        }

    # Apply jitter so co-located buses (e.g. A315/A735) don't overlap on the map
    buses_by_coord: dict = defaultdict(list)
    for b, (lat, lon) in raw_coords.items():
        buses_by_coord[(round(lat, 6), round(lon, 6))].append(b)

    bus_ll: dict = {}
    for (lat, lon), bus_list in buses_by_coord.items():
        if BUS_JITTER_MODE == "v_nom":
            sorted_group = sorted(bus_list, key=lambda b: (bus_v_nom.get(b) or 1e9, b))
        elif BUS_JITTER_MODE == "suffix_voltage":
            sorted_group = sorted(bus_list, key=lambda b: (bus_voltage_kv(b) or 1e9, b))
        else:
            sorted_group = sorted(bus_list)

        for i, b in enumerate(sorted_group):
            bus_ll[b] = jitter_bus(
                lat, lon, i, len(sorted_group), jitter_m=BUS_JITTER_M
            )

    return bus_ll, bus_v_nom, bus_to_province


def load_lines(res_folder: str) -> tuple[pd.DataFrame, str]:
    """
    Load transmission lines from the planning solved network folder.

    Tries ``lines.csv`` first (``s_nom`` capacity column), then falls back
    to ``links.csv`` (``p_nom``).  Rows with zero capacity are dropped.

    Parameters
    ----------
    res_folder : str
        Path to the planning solved network directory.

    Returns
    -------
    lines : pd.DataFrame
        Filtered lines with a normalised ``s_nom`` column.
    cap_col : str
        Name of the original capacity column (``"s_nom"`` or ``"p_nom"``).

    Raises
    ------
    FileNotFoundError
        If neither ``lines.csv`` nor ``links.csv`` exists.
    ValueError
        If a required column is missing from the found file.
    """
    lines_csv = os.path.join(res_folder, "lines.csv")
    links_csv = os.path.join(res_folder, "links.csv")
    if os.path.exists(lines_csv):
        lines = read_csv_flex(lines_csv)
        cap_col = "s_nom"
    elif os.path.exists(links_csv):
        lines = read_csv_flex(links_csv)
        cap_col = "p_nom"
        logging.info("lines.csv not found -- falling back to links.csv (using p_nom)")
    else:
        raise FileNotFoundError(
            f"Neither lines.csv nor links.csv found in {res_folder}"
        )

    for c in ["name", "bus0", "bus1", cap_col]:
        if c not in lines.columns:
            raise ValueError(
                f"Lines file missing '{c}'. Found: {lines.columns.tolist()}"
            )

    lines["name"] = lines["name"].astype(str).str.strip()
    lines["bus0"] = lines["bus0"].astype(str).str.strip()
    lines["bus1"] = lines["bus1"].astype(str).str.strip()
    lines["s_nom"] = pd.to_numeric(lines[cap_col], errors="coerce").fillna(0.0)
    s_nom_base = lines["s_nom"].copy()

    # Prefer the optimised capacity (set by the solver for newly built assets).
    # For lines the optimised column is s_nom_opt; for links it is p_nom_opt.
    opt_col = cap_col.replace("s_nom", "s_nom_opt").replace("p_nom", "p_nom_opt")
    if opt_col in lines.columns:
        s_nom_opt = pd.to_numeric(lines[opt_col], errors="coerce").fillna(0.0)
        lines["s_nom"] = lines["s_nom"].where(lines["s_nom"] > 0, s_nom_opt)

    # True for lines where the original capacity was 0 but the optimiser built capacity.
    lines["is_new"] = (s_nom_base == 0) & (lines["s_nom"] > 0)
    lines = lines[lines["s_nom"] > 0].copy()
    return lines, cap_col


def load_link_flows(res_folder: str) -> tuple:
    """
    Load per-component hourly flows directly from a solved network folder.

    Tries ``links-p0.csv`` first (DC links), then falls back to
    ``lines-p0.csv`` (AC lines).  Aligns rows against a ``timestep`` or
    ``snapshot`` column in ``snapshots.csv``.

    Parameters
    ----------
    res_folder : str
        Path to a solved network directory (planning or single dispatch year).

    Returns
    -------
    tuple[pd.DatetimeIndex, pd.DataFrame] or tuple[None, None]
        ``(timestamps, flows_df)`` where *flows_df* columns are component names,
        or ``(None, None)`` if neither file is present.
    """
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
    """
    Load per-component hourly flows from the dispatch solved network.

    The dispatch solved network stores each investment-period year in a
    separate subfolder.  This function iterates over those year subfolders
    in sorted order, reads ``links-p0.csv`` (or ``lines-p0.csv``) and
    ``snapshots.csv`` from each, and concatenates them into a single
    time-indexed DataFrame.

    Parameters
    ----------
    dispatch_folder : str
        Path to the dispatch solved network directory (contains year subfolders).

    Returns
    -------
    tuple[pd.DatetimeIndex, pd.DataFrame] or tuple[None, None]
        ``(timestamps, flows_df)`` or ``(None, None)`` if no data found.
    """
    year_dirs = sorted(
        d
        for d in (
            os.path.join(dispatch_folder, e)
            for e in os.listdir(dispatch_folder)
            if os.path.isdir(os.path.join(dispatch_folder, e)) and e.isdigit()
        )
    )
    if not year_dirs:
        # No year subfolders — try reading directly (flat dispatch layout)
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
    """
    Return the lookup key for *bus* in *nodal_index*.

    In Nodal mode the index is keyed by bus names, so the bus name is used
    directly.  In Provincial mode the index is keyed by province codes, so the
    province code is returned as a fallback.
    """
    if bus in nodal_index:
        return bus
    return bus_to_province.get(bus, bus)


def resolve_corridor_flow(rows, nodal_index, bus_to_province):
    """
    Find a valid flow orientation for a corridor across all its physical lines.

    Bus names are mapped to province codes via *bus_to_province* so that the
    same province-keyed hourly files are used regardless of whether multiple
    buses belong to the same province.  Duplicate province-pairs are skipped.

    Parameters
    ----------
    rows : list[dict-like]
        Line rows for the corridor (each must have ``bus0`` and ``bus1``).
    nodal_index : dict
        ``{key: filepath}`` mapping from :func:`index_nodal_files`.
    bus_to_province : dict
        ``{bus_name: province_code}`` mapping.

    Returns
    -------
    tuple[str, str, pd.DatetimeIndex, np.ndarray] or tuple[None, None, None, None]
        ``(bus0, bus1, timestamps, flow_mw)`` or four ``None``s if no data found.
    """
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


# =============================================================================
# MAP BUILDER
# =============================================================================
def build_corridor_map(
    corridors,
    bus_ll,
    bus_to_province,
    nodal_index,
    link_flows_ts,
    link_flows_df,
    out_html,
    map_label,
):
    """
    Build and save a corridor utilization Folium map.

    Parameters
    ----------
    corridors : dict
        ``{(bus_a, bus_b): [row, ...]}`` from ``lines``/``links``.
    bus_ll : dict
        ``{bus_name: (lat, lon)}``.
    bus_to_province : dict
        ``{bus_name: province_code}``.
    nodal_index : dict
        ``{key: filepath}`` for hourly energy-balance CSVs.
    link_flows_ts : pd.DatetimeIndex or None
        Time index for the direct link/line flow fallback.
    link_flows_df : pd.DataFrame or None
        Hourly flow DataFrame keyed by component name.
    out_html : str
        Output HTML path.
    map_label : str
        Label shown in the chart trace name (e.g. ``"Planning"`` or
        ``"Dispatch"``).
    """
    map_center = (
        np.mean([ll[0] for ll in bus_ll.values()]),
        np.mean([ll[1] for ll in bus_ll.values()]),
    )
    fmap = folium.Map(location=map_center, zoom_start=6, tiles="CartoDB positron")
    flow_layer = folium.FeatureGroup(
        name="Existing lines (click for utilization)", show=True
    )
    flow_layer.add_to(fmap)
    new_flow_layer = folium.FeatureGroup(
        name="Newly built lines (click for utilization)", show=True
    )
    new_flow_layer.add_to(fmap)
    no_data_layer = folium.FeatureGroup(name="Existing lines — no flow data", show=True)
    no_data_layer.add_to(fmap)
    new_no_data_layer = folium.FeatureGroup(
        name="Newly built lines — no flow data", show=True
    )
    new_no_data_layer.add_to(fmap)

    skipped_coords = skipped_flow = drawn_lines = drawn_no_data = 0

    for (bus_a, bus_b), rows in corridors.items():
        if bus_a not in bus_ll or bus_b not in bus_ll:
            skipped_coords += 1
            continue

        capacity_mw = float(np.sum([float(r["s_nom"]) for r in rows]))
        kv_label = voltage_mix_label([line_voltage_kv(r["name"]) for r in rows])
        sorted_lines = sorted(rows, key=lambda line: str(line["name"]))
        lines_html = "<br>".join(
            f"&bull; {'<span style="color:#22bb44"><b>[NEW]</b></span> ' if bool(line.get('is_new', False)) else ''}"
            f"{line['name']} : s_nom={float(line['s_nom']):.1f}"
            for line in sorted_lines
        )

        bus0, bus1, timestamps, flow_mw = resolve_corridor_flow(
            rows, nodal_index, bus_to_province
        )
        # Fallback to direct link/line flow (covers intra-provincial corridors).
        if timestamps is None and link_flows_df is not None:
            link_names = [str(r["name"]) for r in sorted_lines]
            avail = [n for n in link_names if n in link_flows_df.columns]
            if avail:
                flow_mw = (
                    link_flows_df[avail]
                    .apply(pd.to_numeric, errors="coerce")
                    .fillna(0.0)
                    .sum(axis=1)
                    .to_numpy()
                )
                timestamps = link_flows_ts
                bus0, bus1 = bus_a, bus_b

        missing_flow = timestamps is None
        if missing_flow:
            skipped_flow += 1

        lat1, lon1 = bus_ll[bus_a]
        lat2, lon2 = bus_ll[bus_b]

        distance_m = approx_distance_m(lat1, lon1, lat2, lon2)
        density_factor = (
            min(3.0, max(1.3, 15000 / max(2000, distance_m)))
            if distance_m < 15000
            else 1.0
        )
        adj_step_m = PARALLEL_STEP_M * density_factor

        line_offsets = parallel_offsets(
            len(sorted_lines), base_offset_m=CURVE_OFFSET_M, step_m=adj_step_m
        )

        if missing_flow:
            info_html = f"""
            <div><b>Corridor:</b> {bus_a} &hArr; {bus_b}</div>
            <div><b>Voltage mix:</b> {kv_label}</div>
            <div><b>sum(s_nom):</b> {capacity_mw:.1f}</div>
            <div style="margin-top:6px; color:#888;"><i>No flow data available for this corridor.</i></div>
            <div style="margin-top:6px;"><b>Included lines:</b><br>{lines_html}</div>
            """
            popup = folium.Popup(
                folium.IFrame(html=info_html, width=420, height=200),
                max_width=500,
            )
        else:
            corridor_title = f"{bus_a} <-> {bus_b} ({kv_label})"
            subtitle = (
                f"{map_label} | sum(s_nom)={capacity_mw:.1f} | flow: {bus0} -> {bus1}"
            )
            plot_html = build_util_plot_html(
                timestamps, flow_mw, capacity_mw, corridor_title, subtitle
            )
            info_html = f"""
            <div><b>Corridor:</b> {bus_a} &hArr; {bus_b}</div>
            <div><b>Voltage mix:</b> {kv_label}</div>
            <div><b>sum(s_nom):</b> {capacity_mw:.1f}</div>
            <div style="margin-top:6px;"><b>Included lines (drawn separately):</b><br>{lines_html}</div>
            """
            popup = folium.Popup(
                folium.IFrame(
                    html=build_popup_html(info_html, plot_html),
                    width=POPUP_WIDTH,
                    height=POPUP_HEIGHT,
                ),
                max_width=POPUP_WIDTH + 80,
            )

        is_self_loop = abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9
        for i, (line, (sign, offset_m)) in enumerate(
            zip(sorted_lines, line_offsets), start=1
        ):
            if is_self_loop:
                loop_radius = SELF_LOOP_RADIUS_M + (i - 1) * SELF_LOOP_STEP_M
                curve = make_curve(
                    lat1,
                    lon1,
                    lat2,
                    lon2,
                    offset_m=offset_m,
                    sign=sign,
                    self_loop_radius_m=loop_radius,
                )
            else:
                curve = make_curve(lat1, lon1, lat2, lon2, offset_m=offset_m, sign=sign)

            is_line_new = bool(line.get("is_new", False))
            if missing_flow:
                line_color = (
                    LINE_COLOR_NEW_NO_DATA if is_line_new else LINE_COLOR_NO_DATA
                )
                target_layer = new_no_data_layer if is_line_new else no_data_layer
            else:
                line_color = LINE_COLOR_NEW if is_line_new else LINE_COLOR_WITH_DATA
                target_layer = new_flow_layer if is_line_new else flow_layer
            new_tag = "[NEW] " if is_line_new else ""
            folium.PolyLine(
                locations=curve,
                color=line_color,
                weight=3,
                opacity=0.9,
                tooltip=f"{new_tag}{bus_a} <-> {bus_b} ({kv_label}) | {line['name']} | s_nom={float(line['s_nom']):.1f}",
                popup=popup,
            ).add_to(target_layer)
            if missing_flow:
                drawn_no_data += 1
            else:
                drawn_lines += 1

    folium.LayerControl(collapsed=False).add_to(fmap)
    fmap.save(out_html)

    logging.info(f"[{map_label}] Saved: {out_html}")
    logging.info(f"[{map_label}] Corridors total: {len(corridors)}")
    logging.info(f"[{map_label}] Drawn physical lines: {drawn_lines}")
    logging.info(f"[{map_label}] Drawn (no flow data, grey): {drawn_no_data}")
    logging.info(f"[{map_label}] Skipped (missing coords): {skipped_coords}")
    logging.info(f"[{map_label}] Skipped (missing flow column): {skipped_flow}")
    logging.info(f"[{map_label}] Nodal files indexed: {len(nodal_index)}")
    logging.info(
        f"[{map_label}] Direct flow fallback: "
        f"{'available' if link_flows_df is not None else 'unavailable'} "
        f"({0 if link_flows_df is None else len(link_flows_df.columns)} components)"
    )


# =============================================================================
# MAIN
# =============================================================================

def main():
    planning_res_folder = str(snakemake.input.planning_solved_network)
    dispatch_res_folder = str(snakemake.input.dispatch_solved_network)
    planning_post_process_folder = str(snakemake.input.post_process_planning)
    dispatch_post_process_folder = str(snakemake.input.post_process_dispatch)
    planning_out_html = str(snakemake.output.planning_corridor_map)
    dispatch_out_html = str(snakemake.output.dispatch_corridor_map)

    # Do planning map
    bus_ll, _, bus_to_province = load_buses(
        os.path.join(planning_res_folder, "buses.csv")
    )
    lines, _ = load_lines(planning_res_folder)
    planning_nodal_index = index_nodal_files(
        planning_post_process_folder, POST_PROCESS_FILE_GLOB
    )
    link_flows_ts, link_flows_df = load_link_flows(planning_res_folder)

    corridors: dict = defaultdict(list)
    for _, row in lines.iterrows():
        corridors[canonical_pair(row["bus0"], row["bus1"])].append(row)

    build_corridor_map(
        corridors,
        bus_ll,
        bus_to_province,
        planning_nodal_index,
        link_flows_ts,
        link_flows_df,
        planning_out_html,
        "Planning",
    )

    # Resolve the dispatch topology folder (last investment-period year subfolder).
    dispatch_topo_folder = _dispatch_topology_folder(dispatch_res_folder)

    # Do dispatch map — topology from last year subfolder.
    bus_ll, _, bus_to_province = load_buses(
        os.path.join(dispatch_topo_folder, "buses.csv")
    )
    lines, _ = load_lines(dispatch_topo_folder)
    dispatch_nodal_index = index_nodal_files(
        dispatch_post_process_folder, POST_PROCESS_FILE_GLOB
    )
    dispatch_link_flows_ts, dispatch_link_flows_df = load_dispatch_link_flows(
        dispatch_res_folder
    )

    corridors: dict = defaultdict(list)
    for _, row in lines.iterrows():
        corridors[canonical_pair(row["bus0"], row["bus1"])].append(row)

    build_corridor_map(
        corridors,
        bus_ll,
        bus_to_province,
        dispatch_nodal_index,
        dispatch_link_flows_ts,
        dispatch_link_flows_df,
        dispatch_out_html,
        "Dispatch",
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.error(f"plot_corridor_map failed:\n{traceback.format_exc()}")
        sys.exit(1)
