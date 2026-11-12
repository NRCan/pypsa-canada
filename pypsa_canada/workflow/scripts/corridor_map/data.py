"""CSV loading and transmission topology preparation."""

import os
from collections import defaultdict

import pandas as pd

from .geometry import bus_voltage_kv, canonical_pair, jitter_bus
from .settings import BUS_JITTER_M, BUS_JITTER_MODE


def read_csv_flex(path: str) -> pd.DataFrame:
    """Read a UTF-8-BOM-tolerant CSV and strip column-name whitespace."""
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
    except Exception as e:
        raise ValueError(f"Error reading CSV file {path}: {e}")

    return df


def load_buses(buses_csv: str) -> tuple[dict, dict, dict]:
    """Load jittered coordinates, nominal voltages, and province codes."""
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
        name: (float(y), float(x))
        for name, x, y in zip(buses["name"], buses["x"], buses["y"])
    }

    bus_v_nom = {}
    if "v_nom" in buses.columns:
        v_nom_series = pd.to_numeric(buses["v_nom"], errors="coerce")
        bus_v_nom = {
            name: (float(v) if pd.notna(v) else None)
            for name, v in zip(buses["name"], v_nom_series)
        }

    bus_to_province: dict = {}
    if "province" in buses.columns:
        mask = buses["province"].notna()
        bus_to_province = dict(
            zip(buses.loc[mask, "name"], buses.loc[mask, "province"].str.strip())
        )

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
    """Load positive-capacity lines, falling back to links and optimized capacity."""
    lines_csv = os.path.join(res_folder, "lines.csv")
    links_csv = os.path.join(res_folder, "links.csv")

    # Read lines.csv if it exists, otherwise fall back to links.csv
    if os.path.exists(lines_csv):
        lines = read_csv_flex(lines_csv)
        cap_col = "s_nom"
    elif os.path.exists(links_csv):
        lines = read_csv_flex(links_csv)
        cap_col = "p_nom"
    else:
        raise FileNotFoundError(
            f"Neither lines.csv nor links.csv found in {res_folder}"
        )

    lines["name"] = lines["name"].astype(str).str.strip()
    lines["bus0"] = lines["bus0"].astype(str).str.strip()
    lines["bus1"] = lines["bus1"].astype(str).str.strip()
    lines["s_nom"] = pd.to_numeric(lines[cap_col], errors="coerce").fillna(0.0)
    s_nom_base = lines["s_nom"].copy()

    opt_col = cap_col.replace("s_nom", "s_nom_opt").replace("p_nom", "p_nom_opt")
    if opt_col in lines.columns:
        s_nom_opt = pd.to_numeric(lines[opt_col], errors="coerce").fillna(0.0)
        lines["s_nom"] = lines["s_nom"].where(lines["s_nom"] > 0, s_nom_opt)

    lines["is_new"] = (s_nom_base == 0) & (lines["s_nom"] > 0)
    lines = lines[lines["s_nom"] > 0].copy()

    return lines, cap_col


def load_context(res_folder: str) -> tuple[dict, dict, dict]:
    """Load topology and group physical lines by canonical bus pair."""
    bus_ll, _, bus_to_province = load_buses(os.path.join(res_folder, "buses.csv"))
    lines, _ = load_lines(res_folder)
    corridors: dict = defaultdict(list)

    for _, row in lines.iterrows():
        corridors[canonical_pair(row["bus0"], row["bus1"])].append(row)

    return bus_ll, bus_to_province, corridors
