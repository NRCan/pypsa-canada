# scripts/add_loads.py
import logging
import sys
import traceback

from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from helpers import setup_script_logging
from load_profile import apply_load_profile

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
        raise RuntimeError("add_loads.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    load_config = config["load"]
    investment_periods = config["year_settings"]["investment_period"]
    # Todo verify if this is required
    # Only load the initial load profile if we are applying a growth forecast
    # initial_loads_p_set = (
    #     snakemake.input.loads_p_set
    #     if load_config["load_mode"].upper() == "GROWTH_FORECAST"
    #     else None
    # )
    initial_loads_p_set = snakemake.input.loads_p_set

    loads_p_set_updated = apply_load_profile(
        load_config, investment_periods, initial_loads_p_set
    )
    loads_p_set_updated.to_csv(snakemake.output.loads_p_set)

    finish_benchmark_tracker(
        result_benchmark_csv_path(snakemake.output.loads_p_set),
        "add_loads",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
