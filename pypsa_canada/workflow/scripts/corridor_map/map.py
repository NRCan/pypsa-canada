"""Folium corridor map assembly and summary export."""

import logging
import os
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import folium
import numpy as np
import pandas as pd

from .charts import build_popup_html, build_util_plot_html
from .flows import _bus_index_key, resolve_corridor_flow
from .geometry import (
    approx_distance_m,
    canonical_pair,
    line_voltage_kv,
    make_curve,
    parallel_offsets,
    voltage_mix_label,
)
from .settings import (
    _NEW_LINE_BADGE,
    CURVE_OFFSET_M,
    LINE_COLOR_NO_DATA,
    LINE_COLOR_WITH_DATA,
    PARALLEL_STEP_M,
    POPUP_HEIGHT,
    POPUP_WIDTH,
    SELF_LOOP_RADIUS_M,
    SELF_LOOP_STEP_M,
    SUMMARY_COLUMNS,
)

# --- Data structures ----------------------------------------------------------


class TilesType(Enum):
    """Enumeration of available map tile types."""

    STADIA_DARK = "stadia_dark"  # Needs API key
    ARCGIS = "arcgis"
    OPENSTREETMAP = "openstreetmap"  # Needs API key
    CARTODB_DARK = "carto_db_dark"  # Needs API key
    CARTODB = "carto_db"  # Needs API key


@dataclass
class MapContext:
    """Context for building the corridor map."""

    corridors: dict
    bus_ll: dict
    bus_to_province: dict
    nodal_index: dict
    link_flows_ts: Any
    link_flows_df: pd.DataFrame | None
    map_label: str
    last_year: Any
    out_html: str
    out_csv: str
    province_pair_capacity: dict = field(init=False)
    fmap: folium.Map = field(init=False)
    flow_layer: folium.FeatureGroup = field(init=False)
    no_flow_layer: folium.FeatureGroup = field(init=False)


@dataclass
class CorridorData:
    """Data for a single corridor."""

    bus_a: str
    bus_b: str
    rows: list
    corridor_capacity_mw: float
    base_capacity_mw: float
    added_capacity_mw: float
    kv_label: str
    sorted_lines: list
    lines_html: str
    prov_a: str = ""
    prov_b: str = ""
    is_interprovincial: bool = False
    using_provincial_flow: bool = False
    bus0: Any = None
    bus1: Any = None
    timestamps: Any = None
    flow_mw: Any = None
    final_capacity_mw: float = 0.0
    missing_flow: bool = False
    lat1: float = 0.0
    lon1: float = 0.0
    lat2: float = 0.0
    lon2: float = 0.0
    line_offsets: list = field(default_factory=list)


@dataclass
class MapStats:
    """Statistics for the corridor map."""

    summary: list
    skipped_coords: int = 0
    skipped_flow: int = 0
    drawn_lines: int = 0
    drawn_no_data: int = 0


# --- Map tiles ----------------------------------------------------------------


def _map_tiles_selector(type: TilesType) -> tuple[str, str | None]:
    match type:
        case TilesType.STADIA_DARK:
            return (
                "https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png",
                '"&copy; <a href="https://www.stadiamaps.com/" target="_blank">Stadia Maps</a> &copy; <a href="https://openmaptiles.org/" target="_blank">OpenMapTiles</a> &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors"',
            )
        case TilesType.ARCGIS:
            return (
                "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
                "Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ",
            )
        case TilesType.OPENSTREETMAP:
            return ("OpenStreetMap", None)
        case TilesType.CARTODB_DARK:
            return (
                "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
            )
        case TilesType.CARTODB:
            return ("CartoDB", None)
        case _:
            raise ValueError(f"Unknown map tile type: {type}")


# --- Corridor preparation and flow resolution ---------------------------------


def _province_pair_capacities(corridors, bus_ll, bus_to_province):
    """Sum capacities for interprovincial corridor pairs."""
    province_pair_capacity = defaultdict(float)
    for (bus_a, bus_b), rows in corridors.items():
        if bus_a not in bus_ll or bus_b not in bus_ll:
            continue

        prov_a = bus_to_province.get(bus_a, bus_a)
        prov_b = bus_to_province.get(bus_b, bus_b)
        if prov_a != prov_b:
            pair = canonical_pair(prov_a, prov_b)
            province_pair_capacity[pair] += sum(float(row["s_nom"]) for row in rows)
    return province_pair_capacity


def _resolve_map_flow(corridor: CorridorData, context: MapContext) -> None:
    """Resolve flow data and the capacity used to calculate utilization."""
    corridor.bus0, corridor.bus1, corridor.timestamps, corridor.flow_mw = (
        resolve_corridor_flow(
            corridor.rows, context.nodal_index, context.bus_to_province
        )
    )
    corridor.prov_a = context.bus_to_province.get(corridor.bus_a, corridor.bus_a)
    corridor.prov_b = context.bus_to_province.get(corridor.bus_b, corridor.bus_b)
    corridor.is_interprovincial = corridor.prov_a != corridor.prov_b
    corridor.using_provincial_flow = (
        corridor.timestamps is not None
        and corridor.bus0 is not None
        and _bus_index_key(corridor.bus0, context.bus_to_province, context.nodal_index)
        in context.nodal_index
    )

    if corridor.is_interprovincial and corridor.using_provincial_flow:
        corridor.final_capacity_mw = context.province_pair_capacity[
            canonical_pair(corridor.prov_a, corridor.prov_b)
        ]
    else:
        corridor.final_capacity_mw = corridor.corridor_capacity_mw

    if corridor.timestamps is None and context.link_flows_df is not None:
        link_names = [str(row["name"]) for row in corridor.sorted_lines]
        available = [
            name for name in link_names if name in context.link_flows_df.columns
        ]
        if available:
            corridor.flow_mw = (
                context.link_flows_df[available]
                .apply(pd.to_numeric, errors="coerce")
                .fillna(0.0)
                .sum(axis=1)
                .to_numpy()
            )
            corridor.timestamps = context.link_flows_ts
            corridor.bus0, corridor.bus1 = corridor.bus_a, corridor.bus_b
            corridor.using_provincial_flow = False
            corridor.final_capacity_mw = corridor.corridor_capacity_mw


def _prepare_corridor(
    bus_a: str, bus_b: str, rows: list, context: MapContext
) -> CorridorData:
    """Collect capacities, labels, flow data, and geometry for one corridor."""

    corridor_capacity_mw = sum(float(row["s_nom"]) for row in rows)
    base_capacity_mw = sum(
        float(row["s_nom"]) for row in rows if not row.get("is_new", False)
    )
    added_capacity_mw = sum(
        float(row["s_nom"]) for row in rows if row.get("is_new", False)
    )
    sorted_lines = sorted(rows, key=lambda line: str(line["name"]))
    corridor = CorridorData(
        bus_a=bus_a,
        bus_b=bus_b,
        rows=rows,
        corridor_capacity_mw=corridor_capacity_mw,
        base_capacity_mw=base_capacity_mw,
        added_capacity_mw=added_capacity_mw,
        kv_label=voltage_mix_label([line_voltage_kv(row["name"]) for row in rows]),
        sorted_lines=sorted_lines,
        lines_html="<br>".join(
            f"&bull; {_NEW_LINE_BADGE if line.get('is_new') else ''}"
            f"{line['name']} : s_nom={float(line['s_nom']):.1f}"
            for line in sorted_lines
        ),
        lat1=context.bus_ll[bus_a][0],
        lon1=context.bus_ll[bus_a][1],
        lat2=context.bus_ll[bus_b][0],
        lon2=context.bus_ll[bus_b][1],
    )

    _resolve_map_flow(corridor, context)
    corridor.missing_flow = corridor.timestamps is None

    distance_m = approx_distance_m(
        corridor.lat1, corridor.lon1, corridor.lat2, corridor.lon2
    )
    density_factor = (
        min(3.0, max(1.3, 15000 / max(2000, distance_m))) if distance_m < 15000 else 1.0
    )
    corridor.line_offsets = parallel_offsets(
        len(corridor.sorted_lines),
        base_offset_m=CURVE_OFFSET_M,
        step_m=PARALLEL_STEP_M * density_factor,
    )
    return corridor


# --- Popups and utilization summaries -----------------------------------------


def _build_missing_flow_popup(corridor: CorridorData):
    """Build the popup shown when a corridor has no flow data."""
    capacity_note = ""
    if (
        corridor.is_interprovincial
        and corridor.corridor_capacity_mw != corridor.final_capacity_mw
    ):
        capacity_note = f"""
            <div style="margin-top:6px; color:#0066cc;"><i>Note: Corridor capacity ({corridor.corridor_capacity_mw:.1f} MW) differs from displayed total ({corridor.final_capacity_mw:.1f} MW) which aggregates all {corridor.prov_a}-{corridor.prov_b} connections for provincial flow comparison.</i></div>
            """
    info_html = f"""
            <div><b>Corridor:</b> {corridor.bus_a} &hArr; {corridor.bus_b}</div>
            <div><b>Provinces:</b> {corridor.prov_a} &hArr; {corridor.prov_b}</div>
            <div><b>Voltage mix:</b> {corridor.kv_label}</div>
            <div><b>Base capacity (existing lines):</b> {corridor.base_capacity_mw:.1f} MW</div>
            <div><b>Added capacity (new lines from planning):</b> {corridor.added_capacity_mw:.1f} MW</div>
            <div><b>Corridor total:</b> {corridor.corridor_capacity_mw:.1f} MW</div>
            {capacity_note}
            <div style="margin-top:6px; color:#888;"><i>No flow data available for this corridor.</i></div>
            <div style="margin-top:6px;"><b>Included lines:</b><br>{corridor.lines_html}</div>
            """
    return folium.Popup(
        folium.IFrame(html=info_html, width="420", height="240"),
        max_width=500,
    )


def _build_utilization_popup(corridor: CorridorData, context: MapContext):
    """Build the utilization popup and summary row for a corridor."""
    corridor_title = (
        f"{corridor.bus_a} <-> {corridor.bus_b} "
        f"({corridor.kv_label}) | {context.map_label}"
    )
    provincial_aggregation_used = (
        corridor.is_interprovincial
        and corridor.using_provincial_flow
        and corridor.corridor_capacity_mw != corridor.final_capacity_mw
    )
    capacity_mode = (
        f"provincial aggregate ({corridor.prov_a}↔{corridor.prov_b})"
        if provincial_aggregation_used
        else "corridor-specific"
    )
    subtitle = (
        f"Capacity: {corridor.final_capacity_mw:.1f} MW ({capacity_mode}) | "
        f"flow: {corridor.bus0} -> {corridor.bus1}"
    )
    plot_html, metrics = build_util_plot_html(
        corridor.timestamps,
        corridor.flow_mw,
        corridor.final_capacity_mw,
        corridor_title,
        subtitle,
    )

    if provincial_aggregation_used:
        capacity_explanation = f"""
            <div style="margin-top:6px;"><b>Capacity calculation (provincial mode):</b></div>
            <div><b>This corridor:</b> {corridor.corridor_capacity_mw:.1f} MW (existing: {corridor.base_capacity_mw:.1f} + new: {corridor.added_capacity_mw:.1f})</div>
            <div><b>Total {corridor.prov_a}↔{corridor.prov_b}:</b> {corridor.final_capacity_mw:.1f} MW (aggregates all inter-provincial corridors)</div>
            <div style="margin-top:4px; color:#0066cc; font-size:12px;"><i>Note: Provincial flow data aggregates across all {corridor.prov_a}-{corridor.prov_b} connections, so utilization is calculated using the total provincial capacity.</i></div>
            """
    else:
        capacity_explanation = f"""
            <div style="margin-top:6px;"><b>Capacity calculation:</b></div>
            <div>Existing lines (base s_nom) = {corridor.base_capacity_mw:.1f} MW</div>
            <div>New lines from planning (s_nom_opt) = {corridor.added_capacity_mw:.1f} MW</div>
            <div><b>Total corridor capacity = {corridor.final_capacity_mw:.1f} MW</b></div>
            """

    info_html = f"""
            <div><b>Case:</b> {context.map_label}</div>
            <div><b>Corridor:</b> {corridor.bus_a} &hArr; {corridor.bus_b}</div>
            <div><b>Provinces:</b> {corridor.prov_a} &hArr; {corridor.prov_b}</div>
            <div><b>Voltage mix:</b> {corridor.kv_label}</div>
            <div><b>Final planning year:</b> {context.last_year}</div>
            <div><b>Flow orientation:</b> {corridor.bus0} -> {corridor.bus1}</div>
            {capacity_explanation}
            <div style="margin-top:6px;"><b>Utilization:</b> |flow| / {corridor.final_capacity_mw:.1f} MW</div>
            <div><b>Max utilization:</b> {metrics["max_utilization"]:.3f} p.u.</div>
            <div><b>Avg utilization:</b> {metrics["avg_utilization"]:.3f} p.u.</div>
            <div><b>Hours ≥ 0.8 p.u.:</b> {metrics["hours_ge_0_8"]}</div>
            <div><b>Hours ≥ 1.0 p.u.:</b> {metrics["hours_ge_1_0"]}</div>
            <div style="margin-top:6px;"><b>Physical lines:</b><br>{corridor.lines_html}</div>
            """
    popup = folium.Popup(
        folium.IFrame(
            html=build_popup_html(info_html, plot_html),
            width=str(POPUP_WIDTH),
            height=str(POPUP_HEIGHT),
        ),
        max_width=POPUP_WIDTH + 80,
    )

    a_sorted, b_sorted = sorted([corridor.bus_a, corridor.bus_b])
    prov_a_sorted, prov_b_sorted = sorted([corridor.prov_a, corridor.prov_b])
    summary_row = {
        "case": context.map_label,
        "corridor": f"{a_sorted}__to__{b_sorted}",
        "busA": a_sorted,
        "busB": b_sorted,
        "provinceA": prov_a_sorted,
        "provinceB": prov_b_sorted,
        "corridor_capacity_mw": corridor.corridor_capacity_mw,
        "capacity_for_utilization_mw": corridor.final_capacity_mw,
        "existing_lines_capacity_mw": corridor.base_capacity_mw,
        "new_lines_capacity_mw": corridor.added_capacity_mw,
        "provincial_aggregation_used": provincial_aggregation_used,
        "max_utilization": metrics["max_utilization"],
        "avg_utilization": metrics["avg_utilization"],
        "hours_ge_0_8": metrics["hours_ge_0_8"],
        "hours_ge_1_0": metrics["hours_ge_1_0"],
        "flow_orientation": f"{corridor.bus0} -> {corridor.bus1}",
    }
    return popup, summary_row


# --- Corridor rendering -------------------------------------------------------


def _add_corridor_lines(corridor: CorridorData, context: MapContext, popup):
    """Draw physical lines and return their flow/no-flow counts."""
    drawn_lines = drawn_no_data = 0
    is_self_loop = (
        abs(corridor.lat1 - corridor.lat2) < 1e-9
        and abs(corridor.lon1 - corridor.lon2) < 1e-9
    )
    for i, (line, (sign, offset_m)) in enumerate(
        zip(corridor.sorted_lines, corridor.line_offsets), start=1
    ):
        if is_self_loop:
            loop_radius = SELF_LOOP_RADIUS_M + (i - 1) * SELF_LOOP_STEP_M
            curve = make_curve(
                corridor.lat1,
                corridor.lon1,
                corridor.lat2,
                corridor.lon2,
                offset_m=offset_m,
                sign=sign,
                self_loop_radius_m=loop_radius,
            )
        else:
            curve = make_curve(
                corridor.lat1,
                corridor.lon1,
                corridor.lat2,
                corridor.lon2,
                offset_m=offset_m,
                sign=sign,
            )

        if line.get("is_new"):
            continue
        line_color = (
            LINE_COLOR_NO_DATA if corridor.missing_flow else LINE_COLOR_WITH_DATA
        )

        target_layer = (
            context.no_flow_layer if corridor.missing_flow else context.flow_layer
        )

        # Add the corridor line to the appropriate map layer based on flow data.
        target_layer.add_child(
            folium.PolyLine(
                locations=curve,
                color=line_color,
                weight=3,
                opacity=0.9,
                tooltip=f"{corridor.bus_a} <-> {corridor.bus_b} ({corridor.kv_label}) | {line['name']} | s_nom={float(line['s_nom']):.1f}",
                popup=popup,
            )
        )
        if corridor.missing_flow:
            drawn_no_data += 1
        else:
            drawn_lines += 1
    return drawn_lines, drawn_no_data


def _render_corridor(
    corridor: CorridorData, context: MapContext, stats: MapStats
) -> None:
    """Build corridor popups, summaries, and line features."""
    if corridor.missing_flow:
        stats.skipped_flow += 1
        popup = _build_missing_flow_popup(corridor)
    else:
        popup, summary_row = _build_utilization_popup(corridor, context)
        stats.summary.append(summary_row)

    drawn_lines, drawn_no_data = _add_corridor_lines(corridor, context, popup)
    stats.drawn_lines += drawn_lines
    stats.drawn_no_data += drawn_no_data


# --- Output export and logging ------------------------------------------------


def _save_map_outputs(context: MapContext, stats: MapStats, corridor_count: int):
    """Write map and summary files and log generation statistics."""
    context.fmap.add_child(folium.LayerControl(collapsed=False))

    for output_path in (context.out_html, context.out_csv):
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
    context.fmap.save(context.out_html)

    summary_df = pd.DataFrame(stats.summary, columns=SUMMARY_COLUMNS)
    summary_df = summary_df.sort_values(
        ["hours_ge_0_8", "max_utilization"],
        ascending=[False, False],
    )
    summary_df.to_csv(context.out_csv, index=False, encoding="utf-8-sig")

    logging.info(f"[{context.map_label}] Saved CSV: {context.out_csv}")
    logging.info(f"[{context.map_label}] Saved HTML: {context.out_html}")
    logging.info(f"[{context.map_label}] Corridors total: {corridor_count}")
    logging.info(f"[{context.map_label}] Drawn physical lines: {stats.drawn_lines}")
    logging.info(
        f"[{context.map_label}] Drawn (no flow data, grey): {stats.drawn_no_data}"
    )
    logging.info(
        f"[{context.map_label}] Skipped (missing coords): {stats.skipped_coords}"
    )
    logging.info(
        f"[{context.map_label}] Skipped (missing flow column): {stats.skipped_flow}"
    )
    logging.info(
        f"[{context.map_label}] Nodal files indexed: {len(context.nodal_index)}"
    )
    logging.info(
        f"[{context.map_label}] Direct flow fallback: "
        f"{'available' if context.link_flows_df is not None else 'unavailable'} "
        f"({0 if context.link_flows_df is None else len(context.link_flows_df.columns)} components)"
    )


# --- Public map entry point ---------------------------------------------------


def build_corridor_map(context: MapContext) -> None:
    """Build and save a corridor utilization Folium map and summary CSV."""
    map_center = (
        np.mean([ll[0] for ll in context.bus_ll.values()]),
        np.mean([ll[1] for ll in context.bus_ll.values()]),
    )

    # Select map tiles and initialize the Folium map
    tiles, attr = _map_tiles_selector(TilesType.ARCGIS)
    fmap = folium.Map(
        location=map_center,
        zoom_start=6,
        tiles=tiles,
        attr=attr,
    )

    # Create feature groups for corridors with and without flow data
    flow_layer = folium.FeatureGroup(
        name="Corridor utilization (click lines)", show=True
    )
    no_flow_layer = folium.FeatureGroup(name="No flow data (grey)", show=True)
    fmap.add_child(flow_layer)
    fmap.add_child(no_flow_layer)

    context.fmap = fmap
    context.flow_layer = flow_layer
    context.no_flow_layer = no_flow_layer
    context.province_pair_capacity = _province_pair_capacities(
        context.corridors, context.bus_ll, context.bus_to_province
    )
    stats = MapStats(summary=[])

    # Iterate over each corridor and render it on the map
    for (bus_a, bus_b), rows in context.corridors.items():
        if bus_a not in context.bus_ll or bus_b not in context.bus_ll:
            stats.skipped_coords += 1
            continue

        corridor = _prepare_corridor(bus_a, bus_b, rows, context)
        _render_corridor(corridor, context, stats)

    _save_map_outputs(context, stats, len(context.corridors))
