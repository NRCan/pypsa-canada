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
from corridor_map.map import build_corridor_map
from corridor_map.settings import POST_PROCESS_FILE_GLOB
from helpers import setup_script_logging

snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/plot_corridor_map.log"
)

setup_script_logging(LOG_PATH)

config = snakemake.config if snakemake is not None else None


def get_named_value(named_values, name: str) -> str | None:
    """Return a named Snakemake input/output value when it is declared."""
    try:
        value = getattr(named_values, name)
    except (AttributeError, KeyError):
        return None
    if value is None:
        return None
    value = str(value)
    return value if value else None


def require_named_value(named_values, name: str, value_type: str) -> str:
    """Return a required named Snakemake input/output value."""
    value = get_named_value(named_values, name)
    if value is None:
        raise RuntimeError(
            f"plot_corridor_map.py requires {value_type}.{name} for this output"
        )
    return value


def generate_corridor_map(stage: str, generated_maps: list):
    """Resolve workflow inputs and outputs and generate the stage's map."""
    if stage not in ["planning", "dispatch"]:
        return

    out_html = get_named_value(snakemake.output, f"{stage}_corridor_map")
    out_csv = get_named_value(snakemake.output, f"{stage}_corridor_summary")
    res_folder = require_named_value(
        snakemake.input, f"{stage}_solved_network", "input"
    )
    if stage == "dispatch":
        res_folder = os.path.join(res_folder, str(config["year_settings"]["ref_year"]))

    post_process_folder = require_named_value(
        snakemake.input, f"post_process_{stage}", "input"
    )
    bus_ll, bus_to_province, corridors = load_context(res_folder, stage)
    final_added, last_year, expansion_detail = load_metadata(post_process_folder, stage)
    logging.info(
        f"Generating {stage} corridor map outputs: html={out_html}, csv={out_csv}"
    )
    link_flows_ts, link_flows_df = load_link_flows(res_folder)
    planning_nodal_index = index_nodal_files(
        post_process_folder, POST_PROCESS_FILE_GLOB
    )
    build_corridor_map(
        corridors,
        bus_ll,
        bus_to_province,
        planning_nodal_index,
        link_flows_ts,
        link_flows_df,
        out_html,
        out_csv,
        stage,
        final_added,
        last_year,
        expansion_detail,
    )
    generated_maps.append(stage)


def main():
    """Run map generation with workflow logging and benchmark tracking."""
    if snakemake is None:
        raise RuntimeError("plot_corridor_map.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()
    generated_maps = []
    benchmark_result_anchor = None

    generate_corridor_map(snakemake.params.type, generated_maps)
    benchmark_result_anchor = get_named_value(
        snakemake.output, f"{snakemake.params.type}_corridor_summary"
    )

    finish_benchmark_tracker(
        result_benchmark_csv_path(benchmark_result_anchor),
        f"plot_corridor_map_{'_'.join(generated_maps)}",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.error(f"plot_corridor_map failed:\n{traceback.format_exc()}")
        sys.exit(1)
