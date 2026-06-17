import logging
import math
import os
import sys
import time
import traceback

# from typing import Optional, Dict, Any, Union
from itertools import chain, groupby

import pandas as pd
import pypsa
from constraints.dispatch_constraints import (
    add_CER_constraint_dispatch,
    distribute_CER_hours_dispatch,
)
from constraints.generic_constraints import (
    CER_generator_grouping,
    add_bidirection_link_constraint,
    add_stop_prod_constraint,
    prevent_spill_if_not_fully_charged,
)
from _benchmarks import write_benchmark_file
from helpers import setup_script_logging

from pypsa_canada.workflow.scripts.common import drop_inactive_assets

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
snakemake = globals().get("snakemake")
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/solve_dispatch.log"
BENCHMARK_PATH = getattr(snakemake, "benchmark", None)


setup_script_logging(LOG_PATH)

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
    stop_production_cfg = constraint_dict["add_stop_production"]
    # spilling_variable_cfg = constraint_dict["add_spilling_variable"]
    bidirectional_link_constraint_cfg = constraint_dict["add_bidirection_link"]
    prevent_spill_if_not_fully_charged_cfg = constraint_dict[
        "add_prevent_spill_if_not_fully_charged"
    ]
    # The snapshots must only contain one unique year
    period_list = snapshots.year.unique()
    if len(period_list) == 1:
        period = period_list[0]
    else:
        raise IndexError(
            "Snapshot Datetime index year does not contain exactly 1 year/period"
        )

    # Stop production constraint
    if stop_production_cfg["enable"]:
        logging.debug(f"Stop_production_dictionary = {stop_production_cfg}")
        for stop_year in stop_production_cfg["years"]:
            if period >= stop_year:
                logging.info(
                    f"Adding stop production constraint for {stop_production_cfg['years'][stop_year]} in {period}"
                )
                add_stop_prod_constraint(
                    network, snapshots, stop_production_cfg["years"][stop_year]
                )

    # Add binary spilling variable (1: spilling, 0: not spilling) to Linopy model
    # if spilling_variable_cfg["enable"]:
    #     add_spilling_variable(network, snapshots)

    # Bidirectional link constraint
    if bidirectional_link_constraint_cfg["enable"]:
        add_bidirection_link_constraint(
            network,
            bidirectional_link_constraint_cfg,
        )

    # Prevent spill if not fully charged constraint
    if prevent_spill_if_not_fully_charged_cfg["enable"]:
        maximum_soc_storage_value = prevent_spill_if_not_fully_charged_cfg[
            "maximum_soc_storage_value"
        ]
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
    include_objective_constant: bool = False,
    period_year: int = 0,
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

    # --- CER constraint initialisation (state shared across UC periods) ---
    constraint_dict = config.get("dispatch", {}).get("constraints", {})
    CER_constraint_cfg = constraint_dict["CER_constraint"]
    logging.info(f"CER constraint config: {CER_constraint_cfg}")
    CER_generators = pd.DataFrame()
    CER_group_list = []
    CER_data = pd.DataFrame()
    CER_total_hours = 0
    CER_group_budget = pd.DataFrame()
    CER_leftover = {}
    cer_enabled = False

    logging.info(f"Solver options for {solver_name}: {solver_options}")

    if CER_constraint_cfg["enable"] and period_year >= CER_constraint_cfg.get(
        "year", 9999
    ):
        CER_generators, CER_group_budget, CER_group_list = CER_generator_grouping(
            network, CER_constraint_cfg, period_year, "dispatch"
        )
        if CER_generators is not None and not CER_generators.empty:
            cer_enabled = True
            logging.info(
                f"CER constraint active for {period_year}: "
                f"{len(CER_generators)} generators, groups={list(CER_group_list)}"
            )
            if CER_constraint_cfg.get("forecast_hours") == "load":
                CER_data = distribute_CER_hours_dispatch(network, period_year)
                CER_total_hours = (
                    CER_data[CER_data["above_avg_load"] > 0].count().values[0]
                )
                logging.info(f"CER total hours (above average load): {CER_total_hours}")
            for group in CER_group_list:
                CER_leftover[group] = 0
        else:
            logging.info(f"No CER generators found for year {period_year}")

    # Committable generators
    com_gens = network.generators[network.generators.committable]

    length_snapshot = len(network.snapshots)
    nb_uc_period = math.ceil(length_snapshot / horizon)
    logging.info(f"Number of UC periods: {nb_uc_period}")
    nb_uc_period = int(nb_uc_period)
    logging.info(f"Number of UC periods (rounded): {nb_uc_period}")

    hours_per_yr = 8760

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
            ] = (network.generators_t.status * cumcount).iloc[a - 1, :].astype(int)
            network.generators.loc[
                network.generators_t.status.columns, "down_time_before"
            ] = (
                ((1 - network.generators_t.status) * cumcount)
                .iloc[a - 1, :]
                .astype(int)
            )

        # Build the extra_functionality callback for this UC period.
        # Base constraints are always applied via add_all_dispatch_constraints.
        # CER constraint is layered on top when active.
        if cer_enabled:
            is_last_uc = b >= length_snapshot
            _cer_snapshots = snapshots if is_last_uc else snapshots[:-overlap]

            # Calculate CER hours fraction for this UC period
            forecast_mode = CER_constraint_cfg["forecast_hours"]
            if forecast_mode == "load":
                CER_hours = (
                    CER_data[CER_data["above_avg_load"] > 0.1]
                    .loc[_cer_snapshots[0] : _cer_snapshots[-1]]
                    .count()
                    / CER_total_hours
                ).values[0]
            elif forecast_mode == "uniform":
                CER_hours = len(_cer_snapshots) / hours_per_yr
            else:  # carryover
                CER_hours = 0

            logging.info(
                f"CER UC {uc_period}: forecast_mode={forecast_mode}, "
                f"CER_hours={CER_hours:.4f}, "
                f"cer_snapshots={_cer_snapshots[0]} to {_cer_snapshots[-1]} "
                f"({len(_cer_snapshots)} steps)"
            )

            # Closure captures CER state for this UC period
            def _extra_func(
                n,
                sns,
                _cfg=CER_constraint_cfg,
                _gens=CER_generators,
                _groups=CER_group_list,
                _budget=CER_group_budget,
                _leftover=CER_leftover,
                _hours=CER_hours,
                _uc=uc_period,
                _cer_sns=_cer_snapshots,
            ):
                add_all_dispatch_constraints(n, sns)
                m = n.model
                nonlocal CER_group_budget
                CER_group_budget = add_CER_constraint_dispatch(
                    _cfg,
                    m,
                    n,
                    _cer_sns,
                    _uc,
                    _hours,
                    _budget,
                    _groups,
                    _leftover,
                    _gens,
                )
                logging.info(
                    f"CER budget after UC {_uc}:\n{CER_group_budget.to_string()}"
                )
        else:
            _extra_func = add_all_dispatch_constraints

        status, condition = network.optimize(
            snapshots=snapshots,
            linearized_unit_commitment=linearized_unit_commitment,
            include_objective_constant=include_objective_constant,
            solver_name=solver_name,
            solver_options=solver_options,
            extra_functionality=_extra_func,
        )
        logging.info("Constraints:")
        logging.info(network.model.constraints)
        cer_constraints = [
            c for c in dir(network.model.constraints) if "cer" in c.lower()
        ]
        if cer_constraints:
            logging.info(f"CER constraints in model: {cer_constraints}")
            for cname in cer_constraints:
                con = getattr(network.model.constraints, cname, None)
                if con is not None and hasattr(con, "dual"):
                    logging.info(f"  {cname} dual values: {con.dual}")
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
    start_time = time.perf_counter()
    network = pypsa.Network(snakemake.input.unsolved_dispatch_network)

    logging.info("Running Dispatch Solve")

    dispatch_settings = config["dispatch"]
    horizon = dispatch_settings["horizon"]
    overlap = dispatch_settings["overlap"]
    logging.debug(f"Dispatch_settings = {dispatch_settings}")

    solving_settings = config["solving"]

    options_settings = solving_settings["options"]["dispatch"]
    load_shedding = options_settings["load_shedding"]
    linearized_unit_commitment = options_settings["linearized_unit_commitment"]
    include_objective_constant = options_settings["include_objective_constant"]

    solver_settings = solving_settings["solver"]
    solver_name = solver_settings["name"]
    solver_options_select = solver_settings.get("options", {})
    solver_options = solving_settings["solver_options"].get(solver_options_select, {})

    if len(dispatch_settings["investment_period"]) == 0:
        investment_periods = config["year_settings"]["investment_period"]
    else:
        investment_periods = dispatch_settings["investment_period"]

    for period in investment_periods:
        # network.snapshots = original_snapshots
        logging.info(f"Loading Dispatch Network for period = {period}")
        period_snapshots = network.snapshots[network.snapshots.year == period]

        # Test mode: limit to 6 snapshots for this period
        if os.environ.get("PYPSA_TEST_MODE") == "1":
            logging.info("Test mode enabled: limiting to 6 snapshots for dispatch")
            original_snapshot_count = len(period_snapshots)
            period_snapshots = period_snapshots[:6]
            logging.info(
                f"Reduced period snapshots from {original_snapshot_count} to {len(period_snapshots)}"
            )

        period_network = network.copy()

        drop_inactive_assets(network=period_network, period=period)
        logging.info(f"Period_snapshots = {period_snapshots}")
        period_network.set_snapshots(period_snapshots)

        if linearized_unit_commitment:
            linearized_uc_ena = True
            logging.info("Linearized Unit Commitment Flag has been enabled")
        else:
            linearized_uc_ena = False
            logging.info("Linearized Unit Commitment Flag has been disabled")

        # Load shedding feature if needed
        if load_shedding:
            logging.info("Adding Load shedding option")
            period_network.optimize.add_load_shedding(marginal_cost=1000000, sign=1.0)

        period_network = optimize_uc_period(
            network=period_network,
            horizon=horizon,
            overlap=overlap,
            solver_name=solver_name,
            solver_options=solver_options,
            linearized_unit_commitment=linearized_uc_ena,
            include_objective_constant=include_objective_constant,
            period_year=period,
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

    if BENCHMARK_PATH:
        elapsed_seconds = time.perf_counter() - start_time
        benchmark_path = write_benchmark_file(BENCHMARK_PATH, elapsed_seconds)
        logging.info("Benchmark written to %s", benchmark_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("solve_dispatch failed:\n%s", traceback.format_exc())
        sys.exit(1)
