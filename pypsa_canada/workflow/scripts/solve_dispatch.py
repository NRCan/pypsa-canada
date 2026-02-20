import logging
import math
import os
import sys
import traceback

# from typing import Optional, Dict, Any, Union
from itertools import chain, groupby

import numpy as np
import pandas as pd
import pypsa
from pypsa.descriptors import get_activity_mask, get_switchable_as_dense
from pypsa_canada.workflow.scripts.common import drop_inactive_assets
from constraints.generic_constraints import (
    add_spilling_variable,
    add_stop_prod_constraint,
    add_bidirection_link_constraint,
    prevent_spill_if_not_fully_charged,
    CER_generator_grouping,
)
from constraints.dispatch_constraints import (
    distribute_CER_hours_dispatch,
    add_CER_constraint_dispatch,
)

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/solve_dispatch.log"

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


# Note: Local implementations removed - now using imported functions from constraints module
# - add_bidirection_link_constraint -> from constraints.generic_constraints
# - add_prevent_spill_if_not_fully_charged_constraint -> prevent_spill_if_not_fully_charged
# - distribute_CER_hours_dispatch -> from constraints.dispatch_constraints
# 
# CER constraint handling for dispatch is complex due to UC period state tracking.
# It remains integrated in the optimize_uc_period loop below where it was originally.
# The constraint functions from constraints.dispatch_constraints are used there.


def add_all_dispatch_constraints(network: pypsa.Network, snapshots: pd.DatetimeIndex):
    """
    Function adding all dispatch constraints

    Parameters
    ----------
    network : pypsa.Network
        The pypsa network class sent as an object
    snapshots : pd.Datetime.index
        The pypsa network snapshots for which the constraint will be applied
    """
    constraint_dict = config["dispatch"]["constraints"]

    # The snapshots must only contain one unique year
    period_list = snapshots.year.unique()
    if len(period_list) == 1:
        period = period_list[0]
    else:
        raise IndexError(
            "Snapshot Datetime index year does not contain exactly 1 year/period"
        )

    # Stop production constraint
    if "add_stop_production_constraint" in constraint_dict:
        stop_production_dict = constraint_dict["add_stop_production_constraint"]
        logging.debug(f"Stop_production_dictionary = {stop_production_dict}")
        if period in stop_production_dict:
            add_stop_prod_constraint(network, snapshots, stop_production_dict[period])

    # # Add binary spilling variable (1: spilling, 0: not spilling) to Linopy model
    # spilling_variable_ena = constraint_dict.get("add_spilling_variable")
    # logging.info(f'Add Spilling Variable has been set to {spilling_variable_ena}')
    # if spilling_variable_ena:
    #     add_spilling_variable(network, snapshots)

    # Bidirectional link constraint
    if "add_bidirection_link_constraint" in constraint_dict:
        links_constraint_dict = constraint_dict["add_bidirection_link_constraint"]
        add_bidirection_link_constraint(network, links_constraint_dict)

    # Prevent spill if not fully charged constraint
    if "add_prevent_spill_if_not_fully_charged_constraint" in constraint_dict:
        if (
            "maximum_soc_storage_value"
            in constraint_dict["add_prevent_spill_if_not_fully_charged_constraint"]
        ):
            maximum_soc_storage_value = constraint_dict[
                "add_prevent_spill_if_not_fully_charged_constraint"
            ]["maximum_soc_storage_value"]
            prevent_spill_if_not_fully_charged(
                network, snapshots, maximum_soc_storage_value
            )


def optimize_uc_period(
    network: pypsa.Network,
    horizon: int,
    overlap: int,
    solver_name: str,
    solver_options: dict = {},
    linearized_unit_commitment: bool = False,
):
    solvetime_df = pd.DataFrame(
        {
            "UC Period": int,
            "UC Start": [" "],
            "UC End": [" "],
            "Seconds to Solve": int,
            "Status": [" "],
            "Condition": [" "],
        }
    )

    # Committable generators
    com_gens = network.generators[network.generators.committable]

    length_snapshot = len(network.snapshots)
    nb_uc_period = math.ceil(length_snapshot / horizon)
    logging.info(f"Number of UC periods: {nb_uc_period}")
    nb_uc_period = int(nb_uc_period)
    logging.info(f"Number of UC periods (rounded): {nb_uc_period}")

    # for uc_period in range(self.settings.uc_periods_per_yr):
    for uc_period in range(nb_uc_period):
        starttime = pd.Timestamp.now()
        a = uc_period * horizon
        b = (uc_period + 1) * horizon
        logging.info(str(a) + " : " + str(b))

        if b >= length_snapshot:
            b = length_snapshot
            snapshots = network.snapshots[a:b].copy()
        else:
            snapshots = network.snapshots[a : b + overlap].copy()
        logging.info(f"Solving UC ({uc_period}): {snapshots[0]} to {snapshots[-1]}")
        # if a:
        if not network.stores.empty:
            network.stores.e_initial = network.stores_t.e.loc[network.snapshots[a - 1]]
        if not network.storage_units.empty:
            network.storage_units.state_of_charge_initial = (
                network.storage_units_t.state_of_charge.loc[network.snapshots[a - 1]]
            )
        if not com_gens.empty:
            # Compute up_time_before and down_time_before at a
            cumcount = pd.DataFrame(
                index=network.snapshots,
                columns=network.generators_t.status.columns,
            )

            for col in network.generators_t.status.columns:
                cumcount[col] = list(
                    chain(
                        *(
                            list(range(len(list(g))))
                            for _, g in groupby(network.generators_t.status[col])
                        )
                    )
                )

                # Add 1 since previous gives 1 for two consecutive values, 2 for 3 and so on
                cumcount[col] = cumcount[col] + 1

            # Calculate up time and down time at given time step, and then use time step before, for generators with status (note: ignore initial values at first snapshot for simplicity, since length of UC periods is greater than the min_up_time and min_down_time anyway)
            network.generators.loc[
                network.generators_t.status.columns, "up_time_before"
            ] = (network.generators_t.status * cumcount).iloc[a - 1, :]
            network.generators.loc[
                network.generators_t.status.columns, "down_time_before"
            ] = ((1 - network.generators_t.status) * cumcount).iloc[a - 1, :]

        status, condition = network.optimize(
            snapshots=snapshots,
            linearized_unit_commitment=linearized_unit_commitment,
            solver_name=solver_name,
            solver_options=solver_options,
            extra_functionality=add_all_dispatch_constraints,
        )
        logging.info("Constraints:")
        logging.info(network.model.constraints)
        if status != "ok":
            logging.warning(
                "Optimization failed with status %s and condition %s",
                status,
                condition,
            )

        endtime = pd.Timestamp.now()
        runtime = endtime - starttime
        solvetime_data_df = pd.DataFrame(
            {
                # "Year": [period],
                "UC Period": [uc_period],
                "UC Start": [snapshots[0]],
                "UC End": [snapshots[-1]],
                "Seconds to Solve": [runtime.seconds],
                "Status": [status],
                "Condition": [condition],
            }
        )
        solvetime_df = pd.concat([solvetime_df, solvetime_data_df], ignore_index=True)
        logging.info(
            f"UC Period {uc_period} ({snapshots[0]} to {snapshots[-1]}). Runtime: {runtime.seconds} seconds"
        )

    solvetime_df = solvetime_df.drop(
        [0]
    )  # Remove first (empty) row of solve times/status dataframe
    solvetime_df = solvetime_df.reindex(
        columns=[
            "Year",
            "UC Period",
            "UC Start",
            "UC End",
            "Seconds to Solve",
            "Status",
            "Condition",
        ]
    )
    # Check if planning solve stats exist
    out_path = str(snakemake.output.dispatch_output_file_csv)
    if not os.path.exists(out_path):
        os.makedirs(out_path)
    solve_stats_path = os.path.join(out_path, "solve_stats.csv")
    if os.path.isfile(solve_stats_path):
        solvetime_df = pd.concat([pd.read_csv(solve_stats_path), solvetime_df])
    solvetime_df.to_csv(solve_stats_path, index=False)

    return network


def main():
    network = pypsa.Network(snakemake.input.unsolved_dispatch_network)

    logging.info("Running Dispatch Solve")

    dispatch_settings = config["dispatch"]
    horizon = dispatch_settings["horizon"]
    overlap = dispatch_settings["overlap"]
    load_shedding = dispatch_settings["load_shedding"]
    linearized_unit_commitment = dispatch_settings["linearized_unit_commitment"]
    logging.debug(f"Dispatch_settings = {dispatch_settings}")
    solver_settings = config["solving"]["solver"]
    solver_name = solver_settings["name"]

    if len(dispatch_settings["investment_period"]) == 0:
        investment_periods = config["planning"]["investment_period"]
    else:
        investment_periods = dispatch_settings["investment_period"]

    for period in investment_periods:
        # network.snapshots = original_snapshots
        logging.info(f"Loading Dispatch Network for period = {period}")
        period_snapshots = network.snapshots[network.snapshots.year == period]
        period_network = network.copy()

        drop_inactive_assets(network=period_network, period=period)
        logging.info(f'Period_snapshots = {period_snapshots}')
        period_network.set_snapshots(period_snapshots)

        if linearized_unit_commitment:
            linearized_uc_ena = True
            logging.info("Linearized Unit Commitment Flag has been enabled")
        else:
            linearized_uc_ena = False
            logging.info("Linearized Unit Commitment Flag has been disabled")

        # Load shedding feature if needed
        if load_shedding:
            period_network.optimize.add_load_shedding(marginal_cost=1000000, sign=1.0)

        period_network = optimize_uc_period(
            network=period_network,
            horizon=horizon,
            overlap=overlap,
            solver_name=solver_name,
            solver_options={},
            linearized_unit_commitment=linearized_uc_ena,
        )

        # os.makedirs(os.path.dirname(str(snakemake.output.dispatch_output_file_csv)), exist_ok=True)
        out_path = str(snakemake.output.dispatch_output_file_csv)
        period_network_path = os.path.join(out_path, str(period))
        logging.info(
            f"Exporting to csv folder at the following directory: {period_network_path}"
        )

        if not os.path.exists(out_path):
            os.makedirs(out_path)
        period_network.export_to_csv_folder(period_network_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("solve_dispatch failed:\n%s", traceback.format_exc())
        sys.exit(1)
