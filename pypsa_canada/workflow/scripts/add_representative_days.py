import logging
import os
import sys
import traceback

from helpers import setup_script_logging
from pypsa import Network
from representative_days.snapshot_selection import snapshots_selection

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"


setup_script_logging(LOG_PATH)

config = snakemake.config


def main():
    network = Network(snakemake.input.input_data)
    snapshots_conf = config["snapshots"]

    network.copy().export_to_netcdf(
        snakemake.output.planning_unsolved_network_unfiltered
    )

    network = snapshots_selection(network, snapshots_conf)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if config["run"]["export_csv"]:
        network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)

    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
