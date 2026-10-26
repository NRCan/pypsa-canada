"""Snakemake entrypoint for corridor utilization maps and summaries."""

import logging
import os
import sys
import traceback

from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from corridor_map.capacity import load_metadata
from corridor_map.data import load_context
from corridor_map.flows import index_nodal_files, load_link_flows
from corridor_map.map import MapContext, build_corridor_map
from helpers import setup_script_logging

snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/plot_corridor_map.log"
)

setup_script_logging(LOG_PATH)

config = snakemake.config if snakemake is not None else None


def main():
    """Generate corridor map and summary for the current workflow stage."""

    if snakemake is None:
        raise RuntimeError("plot_corridor_map.py must be executed by Snakemake")
    if config is None:
        raise RuntimeError("Snakemake config is not available")

    benchmark_result_anchor: str = snakemake.output[
        f"{snakemake.params.type}_corridor_summary"
    ]
    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    # Resolve workflow inputs and outputs for the current stage
    stage: str = snakemake.params.type
    res_folder: str = snakemake.input[f"{stage}_solved_network"]
    post_process_folder: str = snakemake.input[f"post_process_{stage}"]
    out_html: str = snakemake.output[f"{stage}_corridor_map"]
    out_csv: str = snakemake.output[f"{stage}_corridor_summary"]

    if stage == "dispatch":
        res_folder = os.path.join(res_folder, str(config["year_settings"]["ref_year"]))

    # Load bus locations, bus-to-province mapping, and corridor definitions
    bus_ll, bus_to_province, corridors = load_context(res_folder)
    # Load post-processing metadata for the stage
    _final_added, last_year, expansion_detail = load_metadata(post_process_folder)
    # Load direct link flows for the resolved network
    link_flows_ts, link_flows_df = load_link_flows(res_folder)
    # Index nodal files for the stage
    nodal_index = index_nodal_files(post_process_folder)

    logging.info(
        f"Generating {stage} corridor map outputs: html={out_html}, csv={out_csv}"
    )

    map_context = MapContext(
        corridors=corridors,
        bus_ll=bus_ll,
        bus_to_province=bus_to_province,
        nodal_index=nodal_index,
        link_flows_ts=link_flows_ts,
        link_flows_df=link_flows_df,
        out_html=out_html,
        out_csv=out_csv,
        map_label=stage,
        last_year=last_year,
        expansion_detail=expansion_detail,
    )
    build_corridor_map(map_context)

    finish_benchmark_tracker(
        result_benchmark_csv_path(benchmark_result_anchor),
        f"plot_corridor_map_{snakemake.params.type}",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.error(f"plot_corridor_map failed:\n{traceback.format_exc()}")
        sys.exit(1)
