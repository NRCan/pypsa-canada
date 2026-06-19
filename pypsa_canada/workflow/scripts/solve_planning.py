# scripts/solve_planning.py
import logging
import os
import sys
import traceback
from typing import TYPE_CHECKING

import pandas as pd
import pypsa
from pypsa_canada.workflow.scripts._benchmarks import (
    finish_benchmark_tracker,
    start_benchmark_tracker,
    result_benchmark_csv_path,
)
from constraints.generic_constraints import (
    CER_generator_grouping,
    add_bidirection_link_constraint,
    add_stop_prod_constraint,
)
from constraints.planning_constraints import (
    add_CER_constraint_planning,
    add_emission_constraint_planning,
    add_planning_reserve_margin,
    component_capacity_expansion_constraint,
)
from helpers import setup_script_logging

if TYPE_CHECKING:
    import pandas as pd

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0]) if snakemake is not None and snakemake.log else "logs/solve_planning.log"
)
BENCHMARK_CSV_PATH = (
    result_benchmark_csv_path(snakemake.output.solved_network_csv)
    if snakemake is not None
    else None
)

setup_script_logging(LOG_PATH)

config = snakemake.config if snakemake is not None else None


def disable_committable_for_OPT(network: pypsa.Network):
    network.generators.loc[
        network.generators["p_nom_extendable"] == True, "committable"
    ] = False
    network.generators.loc[
        network.generators["p_nom_extendable"] == True, "p_min_pu"
    ] = 0
    network.links.loc[network.links["p_nom_extendable"] == True, "committable"] = False


def add_all_planning_constraints(network: pypsa.Network, snapshots: "pd.DatetimeIndex"):
    """
    Function regroup all constraints to be added within the PlanningModel class

    Parameters
    ----------
    network : pypsa.Network
        The pypsa network class sent as an object
    snapshots : pd.Datetime.index
        The pypsa network snapshots for which the constraint will be applied
    """

    constraint_dict = config["planning"]["constraints"]
    bidirectional_link_constraint_cfg = constraint_dict["add_bidirection_link"]
    stop_production_cfg = constraint_dict["add_stop_production"]
    CER_constraint_cfg = constraint_dict["CER_constraint"]
    NZ_constraint_cfg = constraint_dict["NZ_constraint"]
    planning_reserve_margin_cfg = constraint_dict["planning_reserve_margin"]
    custom_constraints_cfg = constraint_dict["component_capacity_expansion_constraint"]

    # The snapshots must only contain one unique year
    period_list = network.snapshots.get_level_values(0).unique()
    logging.info(f"Period list = {period_list}")

    # Add bidirectional link constraint (applies to all periods)
    if bidirectional_link_constraint_cfg["enable"]:
        logging.info(
            f"Adding bidirectional link constraint: {bidirectional_link_constraint_cfg}"
        )
        add_bidirection_link_constraint(
            network, bidirectional_link_constraint_cfg.items()
        )

    # Per-period constraints
    for period in period_list:
        period_snapshots = network.snapshots[
            network.snapshots.get_level_values(0) == period
        ]
        logging.info(f"Processing constraints for period {period}")
        logging.info(f"Network multi-index = {period_snapshots}")

        # Stop production constraint
        if stop_production_cfg["enable"]:
            for stop_year in stop_production_cfg["years"]:
                if period >= stop_year:
                    logging.info(
                        f"Adding stop production constraint for {stop_production_cfg['years'][stop_year]} in {period}"
                    )
                    add_stop_prod_constraint(
                        network,
                        period_snapshots,
                        stop_production_cfg["years"][stop_year],
                    )

        # CER constraint for planning
        if CER_constraint_cfg["enable"]:
            if period >= CER_constraint_cfg["year"]:
                logging.info(f"CER constraint active for year {period}")
                CER_generators, _, CER_group_list = CER_generator_grouping(
                    network, CER_constraint_cfg, period, "planning"
                )
                logging.info(
                    f"CER generators for period {period}: {CER_generators} - {CER_group_list}"
                )
                if not CER_generators.empty:
                    logging.info(
                        f"Adding CER constraint for {len(CER_generators)} generators"
                    )
                    add_CER_constraint_planning(
                        network,
                        period_snapshots,
                        CER_constraint_cfg,
                        CER_group_list,
                        CER_generators,
                        period,
                    )

        # Net-zero/Emissions constraint
        if NZ_constraint_cfg["enable"]:
            emissions_limit = NZ_constraint_cfg[period]
            logging.info(
                f"Adding emissions constraint for {period}: {emissions_limit} MtCO2eq"
            )
            add_emission_constraint_planning(
                network, period_snapshots, emissions_limit, period
            )

        # Planning reserve margin constraint
        if planning_reserve_margin_cfg["enable"]:
            prov_list = planning_reserve_margin_cfg.get("provinces_list", {})
            capacity_values_filepath = planning_reserve_margin_cfg.get(
                "capacity_values_placeholder_filepath", None
            )
            for prov, margin in prov_list.items():
                logging.info(
                    f"Adding reserve margin constraint for {prov} in {period} with margin {margin}"
                )
                if capacity_values_filepath is None:
                    raise ValueError(
                        "capacity_values_placeholder_filename must be provided in the configuration for planning reserve margin constraint"
                    )
                add_planning_reserve_margin(
                    network, period, prov, margin, capacity_values_filepath
                )

    # Custom capacity expansion constraints (applies to all periods)
    if custom_constraints_cfg["enable"]:
        logging.info(
            f"Adding custom capacity expansion constraints: {custom_constraints_cfg}"
        )
        component_capacity_expansion_constraint(
            network, custom_constraints_cfg["custom_constraint_filepath"]
        )

    print("Display constraints")
    print(network.model.constraints)


def main():
    if snakemake is None:
        raise RuntimeError("solve_planning.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()
    network = pypsa.Network(snakemake.input.planning_unsolved_network)
    disable_committable_for_OPT(network)

    # # TODO Temporary fix for standing_loss dim_0 issue - should be fixed in the network loading step instead
    # network.storage_units_t.standing_loss = (
    #     network.storage_units_t.standing_loss.rename({"dim_0": "snapshot"})
    # )
    solving_settings = config["solving"]

    options_settings = solving_settings["options"]["planning"]
    load_shedding = options_settings["load_shedding"]
    linearized_unit_commitment = options_settings["linearized_unit_commitment"]
    include_objective_constant = options_settings["include_objective_constant"]

    solver_settings = solving_settings["solver"]
    solver_name = solver_settings["name"]
    solver_options_select = solver_settings.get("options", {})
    solver_options = solving_settings["solver_options"].get(solver_options_select, {})

    # Test mode: limit to first 6 snapshots per investment period if PYPSA_TEST_MODE environment variable is set
    if os.environ.get("PYPSA_TEST_MODE") == "1":
        logging.info(
            "Test mode enabled: limiting to first 6 snapshots per investment period"
        )
        original_snapshot_count = len(network.snapshots)

        # Get unique investment periods
        if isinstance(network.snapshots, pd.MultiIndex):
            # Multi-period model: take first 6 snapshots from each period
            periods = network.snapshots.get_level_values(0).unique()
            selected_snapshots = []
            for period in periods:
                period_snapshots = network.snapshots[
                    network.snapshots.get_level_values(0) == period
                ]
                selected_snapshots.append(period_snapshots[:6])
            network.snapshots = pd.MultiIndex.from_tuples(
                [snap for sublist in selected_snapshots for snap in sublist],
                names=network.snapshots.names,
            )
            logging.info(
                f"Selected first 6 snapshots from each of {len(periods)} investment periods"
            )
        else:
            # Single period model: just take first 6
            network.snapshots = network.snapshots[:6]

        logging.info(
            f"Reduced snapshots from {original_snapshot_count} to {len(network.snapshots)}"
        )

        # Set all snapshot weightings to 1 for test mode
        logging.info("Test mode: setting all snapshot weightings to 1")
        network.snapshot_weightings.loc[:, ["objective", "stores", "generators"]] = 1
        logging.info(
            f"Snapshot weightings set to: {network.snapshot_weightings.head()}"
        )
    else:
        # Identify snapshots where objective is NOT 0
        valid_snapshots = network.snapshot_weightings[
            network.snapshot_weightings["objective"] != 0
        ].index

        # Update the network to only include those snapshots
        network.set_snapshots(valid_snapshots)

    if linearized_unit_commitment:
        linearized_uc_ena = True
        logging.info("Linearized Unit Commitment Flag has been enabled")

    else:
        linearized_uc_ena = False
        logging.info("Linearized Unit Commitment Flag has been disabled")

    # Load shedding feature if needed
    if load_shedding:
        logging.info("Adding Load shedding option")
        network.optimize.add_load_shedding(marginal_cost=1000000, sign=1.0)

    network.optimize.create_model(
        multi_investment_periods=True,
        linearized_unit_commitment=linearized_uc_ena,
        include_objective_constant=include_objective_constant,
    )

    logging.info(
        f"Solving optimization model with solver: {solver_name} and options: {solver_options}"
    )

    solve_status, solve_condition = network.optimize.solve_model(
        # multi_investment_periods=True,
        # assign_all_duals=True,
        solver_name=solver_name,
        solver_options=solver_options,
        extra_functionality=add_all_planning_constraints,
    )

    logging.info(f"Optimization model: {network.model}")
    if "infeasible" in solve_condition:
        if solver_name in ["gurobi", "xpress"]:
            logging.info("Computing IIS for infeasibility diagnosis")
            labels = network.model.compute_infeasibilities()
            logging.info(f"Labels:\n{labels}")
            network.model.print_infeasibilities()
            logging.info(
                "Infeasibility report written to infeasibility_report.ilp (ILP format)"
            )
        raise RuntimeError("Model is infeasible. Check logs for details.")

    out_path = str(snakemake.output.solved_network_csv)

    network.export_to_csv_folder(out_path)

    if BENCHMARK_CSV_PATH is not None:
        finish_benchmark_tracker(
            BENCHMARK_CSV_PATH,
            "solve_planning",
            benchmark_timer,
            benchmark_memory,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("solve_planning failed:\n%s", traceback.format_exc())
        sys.exit(1)
