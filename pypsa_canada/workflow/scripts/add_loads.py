# scripts/add_loads.py
import logging
import sys
import traceback

from helpers import setup_script_logging
from load_load_forecast import apply_load_profile

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"


setup_script_logging(LOG_PATH)

config = snakemake.config


def main():
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

    loads_p_set_updated = apply_load_profile(load_config, investment_periods, initial_loads_p_set)
    loads_p_set_updated.to_csv(snakemake.output.loads_p_set)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
