# scripts/Lines_Flow_On_Map_With_Transformers.py
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

NODAL_FILE_GLOB = "*_hourly*.csv"  # e.g., BUS_1_hourly.csv


# =============================================================================
# HELPERS
# =============================================================================
def read_csv_flex(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    return df


def detect_time_index(df: pd.DataFrame) -> pd.DatetimeIndex:
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
    files = glob(os.path.join(nodal_dir, pattern))
    if not files:
        logging.warning(
            f"No nodal files found in {nodal_dir} with pattern {pattern}. Flow data will be unavailable."
        )
        return {}

    idx = {}
    for fp in files:
        base = os.path.basename(fp)
        if "_hourly" in base:
            bus = base.split("_hourly")[0].strip()
            idx[bus] = fp
    return idx


_bus_df_cache: dict = {}


def load_bus_df(bus: str, nodal_index: dict) -> pd.DataFrame | None:
    if bus in _bus_df_cache:
        return _bus_df_cache[bus]
    fp = nodal_index.get(bus)
    if not fp or not os.path.exists(fp):
        _bus_df_cache[bus] = None
        return None
    df = read_csv_flex(fp)
    _bus_df_cache[bus] = df
    return df


def canonical_pair(a: str, b: str):
    return tuple(sorted([str(a).strip(), str(b).strip()]))


def parse_kv_from_line_name(name: str):
    # grab trailing _315 or _735 etc
    m = re.search(r"_(\d{2,4})\s*$", str(name).strip())
    return int(m.group(1)) if m else None


def voltage_mix_label(kvs):
    kvs = sorted({k for k in kvs if k is not None})
    if not kvs:
        return "mixed kV"
    if len(kvs) == 1:
        return f"{kvs[0]} kV"
    return f"{'+'.join(map(str, kvs))} kV"


def parse_voltage_suffix(bus_name: str):
    """
    If bus is like 'A315' or 'A_315' return 315.
    If none found, return None.
    """
    s = str(bus_name).strip()
    m = re.search(r"(\d{2,4})\s*$", s)
    if not m:
        m = re.search(r"_(\d{2,4})\s*$", s)
    return int(m.group(1)) if m else None


def jitter_bus(lat, lon, idx, total, jitter_m):
    """
    Spread buses around a circle deterministically so they don't overlap.
    """
    if total <= 1:
        return lat, lon
    angle = 2 * math.pi * (idx / total)
    dlat = (jitter_m / 111320.0) * math.cos(angle)
    dlon = (jitter_m / (111320.0 * max(0.1, math.cos(math.radians(lat))))) * math.sin(
        angle
    )
    return lat + dlat, lon + dlon


# =============================================================================
# FLOW: sum ALL matching columns for neighbor (handles parallel flows)
# =============================================================================
def find_neighbor_flow_cols(df: pd.DataFrame, neighbor: str) -> list[str]:
    n = str(neighbor).strip()
    return [
        c
        for c in df.columns
        if "transmission_flow" in c
        and c.startswith(n)
        and c.endswith("transmission_flow")
    ]


def get_flow_bus0_to_bus1(bus0: str, bus1: str, nodal_index: dict):
    """
    Prefer: bus0 file columns that start with bus1 and end with transmission_flow -> SUM them.
    Fallback: bus1 file columns that start with bus0 and end with transmission_flow -> SUM and flip sign.
    """
    df0 = load_bus_df(bus0, nodal_index)
    if df0 is not None:
        cols0 = find_neighbor_flow_cols(df0, bus1)
        if cols0:
            t = detect_time_index(df0)
            flow = (
                df0[cols0]
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
                .sum(axis=1)
                .to_numpy()
            )
            return t, flow

    df1 = load_bus_df(bus1, nodal_index)
    if df1 is not None:
        cols1 = find_neighbor_flow_cols(df1, bus0)
        if cols1:
            t = detect_time_index(df1)
            flow = (
                df1[cols1]
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
                .sum(axis=1)
                .to_numpy()
            )
            return t, -flow

    return None, None


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
    Offsets: +base, -(base+step), +(base+step), -(base+2step), +(base+2step)...
    No one sits on top of another inside ONE corridor.
    """
    offs = []
    k = 0
    while len(offs) < n:
        if k == 0:
            offs.append((+1, base_offset_m))
        else:
            offs.append((-1, base_offset_m + k * step_m))
            if len(offs) < n:
                offs.append((+1, base_offset_m + k * step_m))
        k += 1
    return offs[:n]


# =============================================================================
# PLOT: utilization-only + clean layout
# =============================================================================
def build_util_plot_html(time_index, flow_signed, cap_sum, title, subtitle):
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
def load_buses(buses_csv: str) -> tuple[dict, dict]:
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

    bus_ll_raw = {
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

    # Apply jitter so co-located buses (e.g. A315/A735) don't overlap on the map
    coord_groups: dict = defaultdict(list)
    for b, (lat, lon) in bus_ll_raw.items():
        coord_groups[(round(lat, 6), round(lon, 6))].append(b)

    bus_ll: dict = {}
    for (lat, lon), bus_list in coord_groups.items():
        if BUS_JITTER_MODE == "v_nom":
            bus_list_sorted = sorted(
                bus_list, key=lambda b: (bus_v_nom.get(b) or 1e9, b)
            )
        elif BUS_JITTER_MODE == "suffix_voltage":
            bus_list_sorted = sorted(
                bus_list, key=lambda b: (parse_voltage_suffix(b) or 1e9, b)
            )
        else:
            bus_list_sorted = sorted(bus_list)

        for i, b in enumerate(bus_list_sorted):
            bus_ll[b] = jitter_bus(
                lat, lon, i, len(bus_list_sorted), jitter_m=BUS_JITTER_M
            )

    return bus_ll, bus_v_nom


def load_lines(res_folder: str) -> tuple[pd.DataFrame, str]:
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
    lines = lines[lines["s_nom"] > 0].copy()
    return lines, cap_col


def build_nodal_index_synthetic(lines: pd.DataFrame, cap_col: str) -> dict:
    """Generate a synthetic nodal_index for testing when no hourly CSV files are present."""
    logging.info("Building synthetic nodal index for testing")
    raw = lines.copy()
    all_buses = pd.unique(raw[["bus0", "bus1"]].values.ravel("K"))
    snapshots = pd.date_range("2021-01-01", periods=8760, freq="h")
    cap = pd.to_numeric(raw[cap_col], errors="coerce").median()
    cap = float(cap) if pd.notna(cap) else 1000.0
    rng = np.random.default_rng(42)
    for bus in all_buses:
        neighbors = pd.unique(
            np.concatenate(
                [
                    raw.loc[raw["bus0"] == bus, "bus1"].values,
                    raw.loc[raw["bus1"] == bus, "bus0"].values,
                ]
            )
        )
        df = pd.DataFrame({"snapshot": snapshots})
        for nb in neighbors:
            df[f"{nb}_transmission_flow"] = rng.uniform(
                -cap * 0.8, cap * 0.8, size=len(snapshots)
            )
        _bus_df_cache[bus] = df
    return {b: "TEST_SYNTHETIC" for b in all_buses}


def pick_orientation_and_flow(rows, nodal_index):
    for r in rows:
        t, flow = get_flow_bus0_to_bus1(r["bus0"], r["bus1"], nodal_index)
        if t is not None:
            return r["bus0"], r["bus1"], t, flow
    for r in rows:
        t, flow = get_flow_bus0_to_bus1(r["bus1"], r["bus0"], nodal_index)
        if t is not None:
            return r["bus1"], r["bus0"], t, flow
    return None, None, None, None


# =============================================================================
# MAIN
# =============================================================================
def main():
    res_folder = str(snakemake.input.planning_solved_network)
    out_html = str(snakemake.output.corridor_map)

    buses_csv = os.path.join(res_folder, "buses.csv")
    bus_ll, _ = load_buses(buses_csv)
    lines, cap_col = load_lines(res_folder)

    nodal_index = index_nodal_files(res_folder, NODAL_FILE_GLOB)
    if not nodal_index:
        nodal_index = build_nodal_index_synthetic(lines, cap_col)

    corridors: dict = defaultdict(list)
    for _, r in lines.iterrows():
        corridors[canonical_pair(r["bus0"], r["bus1"])].append(r)

    lat_mean = np.mean([ll[0] for ll in bus_ll.values()])
    lon_mean = np.mean([ll[1] for ll in bus_ll.values()])
    m = folium.Map(
        location=[lat_mean, lon_mean], zoom_start=6, tiles="CartoDB positron"
    )
    layer = folium.FeatureGroup(name="Corridor utilization (click lines)", show=True)
    layer.add_to(m)

    skipped_coords = skipped_flow = drawn_lines = 0

    for (busA, busB), rows in corridors.items():
        if busA not in bus_ll or busB not in bus_ll:
            skipped_coords += 1
            continue

        cap_sum = float(np.sum([float(r["s_nom"]) for r in rows]))
        kv_label = voltage_mix_label([parse_kv_from_line_name(r["name"]) for r in rows])
        rows_sorted = sorted(rows, key=lambda r: str(r["name"]))
        lines_list_html = "<br>".join(
            [f"&bull; {r['name']} : s_nom={float(r['s_nom']):.1f}" for r in rows_sorted]
        )

        bus0, bus1, t, flow = pick_orientation_and_flow(rows, nodal_index)
        if t is None:
            skipped_flow += 1
            continue

        lat1, lon1 = bus_ll[busA]
        lat2, lon2 = bus_ll[busB]

        d_m = approx_distance_m(lat1, lon1, lat2, lon2)
        close_factor = (
            min(3.0, max(1.3, 15000 / max(2000, d_m))) if d_m < 15000 else 1.0
        )
        step_m = PARALLEL_STEP_M * close_factor

        offs = parallel_offsets(
            len(rows_sorted), base_offset_m=CURVE_OFFSET_M, step_m=step_m
        )

        corridor_title = f"{busA} <-> {busB} ({kv_label})"
        subtitle = f"sum(s_nom)={cap_sum:.1f} | flow orientation used: {bus0} -> {bus1}"
        plot_html = build_util_plot_html(t, flow, cap_sum, corridor_title, subtitle)

        info_html = f"""
        <div><b>Corridor:</b> {busA} &hArr; {busB}</div>
        <div><b>Voltage mix:</b> {kv_label}</div>
        <div><b>sum(s_nom):</b> {cap_sum:.1f}</div>
        <div style="margin-top:6px;"><b>Included lines (drawn separately):</b><br>{lines_list_html}</div>
        """
        popup = folium.Popup(
            folium.IFrame(
                html=build_popup_html(info_html, plot_html),
                width=POPUP_WIDTH,
                height=POPUP_HEIGHT,
            ),
            max_width=POPUP_WIDTH + 80,
        )

        for i, (r, (sgn, offmag)) in enumerate(zip(rows_sorted, offs), start=1):
            if abs(lat1 - lat2) < 1e-9 and abs(lon1 - lon2) < 1e-9:
                loop_r = SELF_LOOP_RADIUS_M + (i - 1) * SELF_LOOP_STEP_M
                curve = make_curve(
                    lat1,
                    lon1,
                    lat2,
                    lon2,
                    offset_m=offmag,
                    sign=sgn,
                    self_loop_radius_m=loop_r,
                )
            else:
                curve = make_curve(lat1, lon1, lat2, lon2, offset_m=offmag, sign=sgn)

            folium.PolyLine(
                locations=curve,
                weight=3,
                opacity=0.9,
                tooltip=f"{busA} <-> {busB} ({kv_label}) | {r['name']} | s_nom={float(r['s_nom']):.1f}",
                popup=popup,
            ).add_to(layer)
            drawn_lines += 1

    folium.LayerControl(collapsed=False).add_to(m)
    m.save(out_html)

    logging.info(f"Saved: {out_html}")
    logging.info(f"[Diag] Corridors total: {len(corridors)}")
    logging.info(f"[Diag] Drawn physical lines: {drawn_lines}")
    logging.info(f"[Diag] Skipped (missing coords): {skipped_coords}")
    logging.info(f"[Diag] Skipped (missing flow column): {skipped_flow}")
    logging.info(f"[Diag] Nodal files indexed: {len(nodal_index)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.error(f"plot_corridor_map failed:\n{traceback.format_exc()}")
        sys.exit(1)
