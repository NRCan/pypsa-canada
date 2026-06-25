"""
Post-process solved dispatch network(s).

Snakemake script: reads dispatch result folders, computes annual metrics,
energy balance, storage balance, and saves summary CSVs + network map.
"""

import logging
import os
import sys
import time

import pandas as pd
import pypsa
from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from postprocess_helpers import (
    calc_annual,
    calc_energy_balance,
    calc_storage_balance,
    create_templates,
    format_network,
    save_prov_energy_balance,
    save_storage_balance,
)

# ── Snakemake wiring ──
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/post_process_dispatch.log"
)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)

config = snakemake.config if snakemake is not None else {}
solved_dispatch_path = (
    str(snakemake.input.solved_dispatch_network) if snakemake is not None else None
)
output_dir = (
    str(snakemake.output.dispatch_postprocess) if snakemake is not None else None
)

# ── Configuration ──
result_type = config.get("postprocess", {}).get("result_type", "Provincial")
run_name = config.get("run", {}).get("name", "default")
model_name = f"PyPSA-Canada_{run_name}"
scenario_name = run_name


def network_map(n: pypsa.Network, year: int, output_path: str):
    """Save an interactive HTML map of the network."""

    try:
        map_object = n.explore()
        map_path = os.path.join(output_path, f"network_map_{year}.html")
        # to_html should be the only correct save of the map object
        map_object.to_html(map_path)

        logging.info(f"Saved network map for {year}: {map_path}")

    except Exception as e:
        logging.warning(f"Could not save network map for {year}: {e}")


def main():
    if snakemake is None:
        raise RuntimeError("post_process_dispatch.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    logging.info("===== DISPATCH POST-PROCESS =====")
    start_time = time.perf_counter()

    # Discover year subdirectories (each holds a solved dispatch network)
    year_dirs = sorted(
        d
        for d in os.listdir(solved_dispatch_path)
        if os.path.isdir(os.path.join(solved_dispatch_path, d)) and d.isdigit()
    )
    if not year_dirs:
        raise FileNotFoundError(
            f"No year subdirectories found in {solved_dispatch_path}"
        )

    logging.info(f"Found dispatch year folders: {year_dirs}")

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    annual_provincial_data = pd.DataFrame()
    annual_unit_data = pd.DataFrame()
    prov_energy_balance = pd.DataFrame()
    storage_balance = pd.DataFrame()
    provinces = set()

    for year_str in year_dirs:
        year = int(year_str)
        year_path = os.path.join(solved_dispatch_path, year_str)

        logging.info(f"Loading dispatch network for {year} from {year_path}")
        n = pypsa.Network(year_path)
        n, year_provinces = format_network(n, result_type)
        provinces.update(year_provinces)

        templates = create_templates(n)

        logging.info(f"Processing dispatch year {year}")

        # Calculate annual data
        annual_provincial_data = pd.concat(
            [
                annual_provincial_data,
                calc_annual(n, year, True, False, templates, model_name, scenario_name),
            ]
        )
        annual_unit_data = pd.concat(
            [
                annual_unit_data,
                calc_annual(
                    n, year, False, False, templates, model_name, scenario_name
                ),
            ]
        )

        # Energy balance
        prov_energy_balance = pd.concat(
            [
                prov_energy_balance,
                calc_energy_balance(n, year, False),
            ]
        )

        # Storage balance
        storage_balance = pd.concat(
            [
                storage_balance,
                calc_storage_balance(n, year, False),
            ]
        )

    # ── Save results ──
    logging.info("Saving results...")
    save_start = time.perf_counter()

    annual_provincial_data.to_csv(
        os.path.join(output_dir, f"{result_type}_summary_dispatch.csv"), index=False
    )
    logging.info(
        f"Saved {result_type} summary ({round(time.perf_counter() - save_start, 3)} s)"
    )

    annual_unit_data.to_csv(
        os.path.join(output_dir, "unit_summary_dispatch.csv"), index=False
    )
    logging.info(f"Saved unit summary ({round(time.perf_counter() - save_start, 3)} s)")

    save_prov_energy_balance(prov_energy_balance, output_dir, result_type, provinces)
    save_storage_balance(storage_balance, output_dir)

    # Network map (use the last loaded network)
    network_map(n, int(year_dirs[-1]), output_dir)

    logging.info(
        f"Dispatch post-process complete ({round(time.perf_counter() - start_time, 3)} s)"
    )

    finish_benchmark_tracker(
        result_benchmark_csv_path(output_dir),
        "post_process_dispatch",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    main()
elif snakemake is not None:
    main()
