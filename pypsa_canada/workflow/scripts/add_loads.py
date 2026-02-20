# scripts/add_loads.py
import logging
import os
import sys
import traceback

import pandas as pd
from load_load_forecast import LoadProfile, load_load_forecast
from pypsa import Network

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Configure logging to both file and stdout (handy for --show-failed-logs)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)

config = snakemake.config


def apply_forecast_load(
    network: Network,
    load_config: dict,
) -> Network:
    # Variables
    load_mode: LoadProfile = LoadProfile[load_config["load_mode"].upper()]
    load_growth_filepath = load_config["load_growth_filepath"]
    specific_year = load_config["ref_year"]

    load_growth: pd.DataFrame

    print(f"Loading following load profile={load_mode.name}")
    load_growth = load_load_forecast(load_mode, load_growth_filepath, specific_year)

    network.loads_t.p_set = load_growth

    return network


def main():
    network = Network(snakemake.input.input_data)
    load_config = config["load"]

    network = apply_forecast_load(network, load_config)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)

    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
