import logging
import os
import sys
import traceback

from pypsa import Network
from representative_days.snapshot_profile import SnapshotStatus, snapshots_selection

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
    network = Network(snakemake.input.input_data)
    snapshot_status: SnapshotStatus
    # network_ref = network.copy()
    snapshots_conf = config["snapshots"]

    network.copy().export_to_netcdf(
        snakemake.output.planning_unsolved_network_unfiltered
    )

    network, snapshot_status = snapshots_selection(network, snapshots_conf)

    with open(snakemake.output.snapshot_status, "w") as f:
        f.write(str(snapshot_status.value))

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
