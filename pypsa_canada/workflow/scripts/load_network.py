# scripts/load_network.py
import logging
import sys
import traceback

# import pandas as pd
import pypsa
from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from common import validate_bus_provinces
from helpers import setup_script_logging

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0]) if snakemake is not None and snakemake.log else "logs/temp.log"
)


setup_script_logging(LOG_PATH)

config = snakemake.config if snakemake is not None else None


def main():
    if snakemake is None:
        raise RuntimeError("load_network.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    network = pypsa.Network(snakemake.input.input_data)

    validate_bus_provinces(network)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if config["run"]["export_csv"]:
        network.export_to_csv_folder(
            f"{snakemake.output.planning_unsolved_network[:-3]}_csv"
        )

    finish_benchmark_tracker(
        result_benchmark_csv_path(snakemake.output.planning_unsolved_network),
        "load_network",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("load_network failed:\n%s", traceback.format_exc())
        sys.exit(1)
