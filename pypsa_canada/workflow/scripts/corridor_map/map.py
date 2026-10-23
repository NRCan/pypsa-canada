"""Folium corridor map assembly and summary export."""

import logging
import os
from collections import defaultdict

import folium
import numpy as np
import pandas as pd

from .charts import build_popup_html, build_util_plot_html
from .flows import _bus_index_key, _hourly_cache, resolve_corridor_flow
from .geometry import (
    approx_distance_m,
    canonical_pair,
    line_voltage_kv,
    make_curve,
    parallel_offsets,
    voltage_mix_label,
)
from .settings import (
    CURVE_OFFSET_M,
    LINE_COLOR_NO_DATA,
    LINE_COLOR_WITH_DATA,
    PARALLEL_STEP_M,
    POPUP_HEIGHT,
    POPUP_WIDTH,
    SELF_LOOP_RADIUS_M,
    SELF_LOOP_STEP_M,
    SUMMARY_COLUMNS,
    _NEW_LINE_BADGE,
)


def build_corridor_map(
    corridors,
    bus_ll,
    bus_to_province,
    nodal_index,
    link_flows_ts,
    link_flows_df,
    out_html,
    out_csv,
    map_label,
    final_added,
    last_year,
    expansion_detail,
):
    """Build and save a corridor utilization Folium map and summary CSV."""
    _hourly_cache.clear()

    map_center = (
        np.mean([ll[0] for ll in bus_ll.values()]),
        np.mean([ll[1] for ll in bus_ll.values()]),
    )
    fmap = folium.Map(location=map_center, zoom_start=6, tiles="CartoDB positron")
    flow_layer = folium.FeatureGroup(
        name="Corridor utilization (click lines)", show=True
    )
    flow_layer.add_to(fmap)
    no_data_layer = folium.FeatureGroup(name="No flow data (grey)", show=True)
    no_data_layer.add_to(fmap)

    skipped_coords = skipped_flow = drawn_lines = drawn_no_data = 0
    summary = []

    province_pair_capacity = defaultdict(float)
    for (bus_a, bus_b), rows in corridors.items():
        if bus_a not in bus_ll or bus_b not in bus_ll:
            continue
        prov_a = bus_to_province.get(bus_a, bus_a)
        prov_b = bus_to_province.get(bus_b, bus_b)
        if prov_a != prov_b:
            prov_pair = canonical_pair(prov_a, prov_b)
            corridor_capacity = sum(float(r["s_nom"]) for r in rows)
            province_pair_capacity[prov_pair] += corridor_capacity

    for (bus_a, bus_b), rows in corridors.items():
        if bus_a not in bus_ll or bus_b not in bus_ll:
            skipped_coords += 1
            continue

        corridor_capacity_mw = sum(float(r["s_nom"]) for r in rows)

        base_capacity_mw = sum(
            float(r["s_nom"]) for r in rows if not r.get("is_new", False)
        )
        added_capacity_mw = sum(
            float(r["s_nom"]) for r in rows if r.get("is_new", False)
        )

        kv_label = voltage_mix_label([line_voltage_kv(r["name"]) for r in rows])
        sorted_lines = sorted(rows, key=lambda line: str(line["name"]))
        lines_html = "<br>".join(
            f"&bull; {_NEW_LINE_BADGE if line.get('is_new') else ''}"
            f"{line['name']} : s_nom={float(line['s_nom']):.1f}"
            for line in sorted_lines
        )

        bus0, bus1, timestamps, flow_mw = resolve_corridor_flow(
            rows, nodal_index, bus_to_province
        )

        prov_a = bus_to_province.get(bus_a, bus_a)
        prov_b = bus_to_province.get(bus_b, bus_b)
        is_interprovincial = prov_a != prov_b

        using_provincial_flow = (
            timestamps is not None
            and bus0 is not None
            and _bus_index_key(bus0, bus_to_province, nodal_index) in nodal_index
        )

        if is_interprovincial and using_provincial_flow:
            prov_pair = canonical_pair(prov_a, prov_b)
            final_capacity_mw = province_pair_capacity[prov_pair]
        else:
            final_capacity_mw = corridor_capacity_mw
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
                using_provincial_flow = False
                final_capacity_mw = corridor_capacity_mw

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
            capacity_note = ""
            if is_interprovincial and corridor_capacity_mw != final_capacity_mw:
                capacity_note = f"""
            <div style="margin-top:6px; color:#0066cc;"><i>Note: Corridor capacity ({corridor_capacity_mw:.1f} MW) differs from displayed total ({final_capacity_mw:.1f} MW) which aggregates all {prov_a}-{prov_b} connections for provincial flow comparison.</i></div>
            """
            info_html = f"""
            <div><b>Corridor:</b> {bus_a} &hArr; {bus_b}</div>
            <div><b>Provinces:</b> {prov_a} &hArr; {prov_b}</div>
            <div><b>Voltage mix:</b> {kv_label}</div>
            <div><b>Base capacity (existing lines):</b> {base_capacity_mw:.1f} MW</div>
            <div><b>Added capacity (new lines from planning):</b> {added_capacity_mw:.1f} MW</div>
            <div><b>Corridor total:</b> {corridor_capacity_mw:.1f} MW</div>
            {capacity_note}
            <div style="margin-top:6px; color:#888;"><i>No flow data available for this corridor.</i></div>
            <div style="margin-top:6px;"><b>Included lines:</b><br>{lines_html}</div>
            """
            popup = folium.Popup(
                folium.IFrame(html=info_html, width=420, height=240),
                max_width=500,
            )
        else:
            corridor_title = f"{bus_a} <-> {bus_b} ({kv_label}) | {map_label}"

            capacity_mode = "corridor-specific"
            if (
                is_interprovincial
                and using_provincial_flow
                and corridor_capacity_mw != final_capacity_mw
            ):
                capacity_mode = f"provincial aggregate ({prov_a}↔{prov_b})"

            subtitle = (
                f"Capacity: {final_capacity_mw:.1f} MW ({capacity_mode}) | "
                f"flow: {bus0} -> {bus1}"
            )
            plot_html, metrics = build_util_plot_html(
                timestamps, flow_mw, final_capacity_mw, corridor_title, subtitle
            )

            if (
                is_interprovincial
                and using_provincial_flow
                and corridor_capacity_mw != final_capacity_mw
            ):
                capacity_explanation = f"""
            <div style="margin-top:6px;"><b>Capacity calculation (provincial mode):</b></div>
            <div><b>This corridor:</b> {corridor_capacity_mw:.1f} MW (existing: {base_capacity_mw:.1f} + new: {added_capacity_mw:.1f})</div>
            <div><b>Total {prov_a}↔{prov_b}:</b> {final_capacity_mw:.1f} MW (aggregates all inter-provincial corridors)</div>
            <div style="margin-top:4px; color:#0066cc; font-size:12px;"><i>Note: Provincial flow data aggregates across all {prov_a}-{prov_b} connections, so utilization is calculated using the total provincial capacity.</i></div>
            """
            else:
                capacity_explanation = f"""
            <div style="margin-top:6px;"><b>Capacity calculation:</b></div>
            <div>Existing lines (base s_nom) = {base_capacity_mw:.1f} MW</div>
            <div>New lines from planning (s_nom_opt) = {added_capacity_mw:.1f} MW</div>
            <div><b>Total corridor capacity = {final_capacity_mw:.1f} MW</b></div>
            """

            info_html = f"""
            <div><b>Case:</b> {map_label}</div>
            <div><b>Corridor:</b> {bus_a} &hArr; {bus_b}</div>
            <div><b>Provinces:</b> {prov_a} &hArr; {prov_b}</div>
            <div><b>Voltage mix:</b> {kv_label}</div>
            <div><b>Final planning year:</b> {last_year}</div>
            <div><b>Flow orientation:</b> {bus0} -> {bus1}</div>
            {capacity_explanation}
            <div style="margin-top:6px;"><b>Utilization:</b> |flow| / {final_capacity_mw:.1f} MW</div>
            <div><b>Max utilization:</b> {metrics["max_utilization"]:.3f} p.u.</div>
            <div><b>Avg utilization:</b> {metrics["avg_utilization"]:.3f} p.u.</div>
            <div><b>Hours ≥ 0.8 p.u.:</b> {metrics["hours_ge_0_8"]}</div>
            <div><b>Hours ≥ 1.0 p.u.:</b> {metrics["hours_ge_1_0"]}</div>
            <div style="margin-top:6px;"><b>Physical lines:</b><br>{lines_html}</div>
            """
            popup = folium.Popup(
                folium.IFrame(
                    html=build_popup_html(info_html, plot_html),
                    width=POPUP_WIDTH,
                    height=POPUP_HEIGHT,
                ),
                max_width=POPUP_WIDTH + 80,
            )

            a_sorted, b_sorted = sorted([bus_a, bus_b])
            prov_a_sorted, prov_b_sorted = sorted([prov_a, prov_b])
            summary.append(
                {
                    "case": map_label,
                    "corridor": f"{a_sorted}__to__{b_sorted}",
                    "busA": a_sorted,
                    "busB": b_sorted,
                    "provinceA": prov_a_sorted,
                    "provinceB": prov_b_sorted,
                    "corridor_capacity_mw": corridor_capacity_mw,
                    "capacity_for_utilization_mw": final_capacity_mw,
                    "existing_lines_capacity_mw": base_capacity_mw,
                    "new_lines_capacity_mw": added_capacity_mw,
                    "provincial_aggregation_used": is_interprovincial
                    and using_provincial_flow
                    and corridor_capacity_mw != final_capacity_mw,
                    "max_utilization": metrics["max_utilization"],
                    "avg_utilization": metrics["avg_utilization"],
                    "hours_ge_0_8": metrics["hours_ge_0_8"],
                    "hours_ge_1_0": metrics["hours_ge_1_0"],
                    "flow_orientation": f"{bus0} -> {bus1}",
                }
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

            if line.get("is_new"):
                continue
            line_color = LINE_COLOR_NO_DATA if missing_flow else LINE_COLOR_WITH_DATA
            target_layer = no_data_layer if missing_flow else flow_layer
            folium.PolyLine(
                locations=curve,
                color=line_color,
                weight=3,
                opacity=0.9,
                tooltip=f"{bus_a} <-> {bus_b} ({kv_label}) | {line['name']} | s_nom={float(line['s_nom']):.1f}",
                popup=popup,
            ).add_to(target_layer)
            if missing_flow:
                drawn_no_data += 1
            else:
                drawn_lines += 1

    folium.LayerControl(collapsed=False).add_to(fmap)
    for output_path in (out_html, out_csv):
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
    fmap.save(out_html)

    summary_df = pd.DataFrame(summary, columns=SUMMARY_COLUMNS)
    summary_df = summary_df.sort_values(
        ["hours_ge_0_8", "max_utilization"],
        ascending=[False, False],
    )
    summary_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    logging.info(f"[{map_label}] Saved CSV: {out_csv}")

    logging.info(f"[{map_label}] Saved HTML: {out_html}")
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
