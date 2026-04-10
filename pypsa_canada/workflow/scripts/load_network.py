# scripts/load_network.py
import logging
import os
import sys
import traceback

# import pandas as pd
import pypsa
from common import validate_bus_provinces

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

def main():
    network = pypsa.Network(snakemake.input.input_data)

    validate_bus_provinces(network)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if(config["run"]["export_csv"]):
        network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("load_network failed:\n%s", traceback.format_exc())
        sys.exit(1)
