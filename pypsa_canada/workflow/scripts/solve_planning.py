# scripts/solve_planning.py
import logging
import os
import sys
import traceback
from typing import TYPE_CHECKING

import pandas as pd
import pypsa
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

if TYPE_CHECKING:
    import pandas as pd

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/solve_planning.log"

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

    # The snapshots must only contain one unique year
    period_list = network.snapshots.get_level_values(0).unique()
    logging.info(f"Period list = {period_list}")

    # Add bidirectional link constraint (applies to all periods)
    if "add_bidirection_link_constraint" in constraint_dict:
        links_constraint_dict = constraint_dict["add_bidirection_link_constraint"]
        logging.info(f"Adding bidirectional link constraint: {links_constraint_dict}")
        add_bidirection_link_constraint(network, links_constraint_dict)

    # Per-period constraints
    for period in period_list:
        period_snapshots = network.snapshots[
            network.snapshots.get_level_values(0) == period
        ]
        logging.info(f"Processing constraints for period {period}")
        logging.info(f"Processing constraints for period {period}")
        logging.info(f"Network multi-index = {period_snapshots}")

        # Stop production constraint
        if "add_stop_production_constraint" in constraint_dict:
            stop_production_dict = constraint_dict["add_stop_production_constraint"]
            logging.debug(f"Stop_production_dictionary = {stop_production_dict}")
            if period in stop_production_dict:
                logging.info(
                    f"Adding stop production constraint for {stop_production_dict[period]}"
                )
                logging.info(
                    f"Adding stop production constraint for {stop_production_dict[period]}"
                )
                add_stop_prod_constraint(
                    network, period_snapshots, stop_production_dict[period]
                )

        # CER constraint for planning
        CER_constraint = constraint_dict.get("CER_constraint")
        if CER_constraint:
            if period >= CER_constraint["year"]:
                logging.info(f"CER constraint active for year {period}")
                CER_generators, _, CER_group_list = CER_generator_grouping(
                    network, CER_constraint, period, "planning"
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
                        CER_constraint,
                        CER_group_list,
                        CER_generators,
                        period,
                    )

        # Net-zero/Emissions constraint
        NZ_constraint = constraint_dict.get("NZ_constraint")
        if NZ_constraint:
            if period in NZ_constraint:
                emissions_limit = NZ_constraint[period]
                logging.info(
                    f"Adding emissions constraint for {period}: {emissions_limit} MtCO2eq"
                )
                add_emission_constraint_planning(
                    network, period_snapshots, emissions_limit, period
                )

        # Planning reserve margin constraint
        reserve_margin_config = constraint_dict.get("planning_reserve_margin").get(
            "provinces_list", {}
        )
        capacity_values_filepath = constraint_dict.get("planning_reserve_margin").get(
            "capacity_values_placeholder_filepath", None
        )
        for prov, margin in reserve_margin_config.items():
            logging.info(
                f"Adding reserve margin constraint for {prov} in {period} with margin {margin}"
            )
            print(
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
    custom_constraints = constraint_dict.get(
        "component_capacity_expansion_constraint", False
    )
    if custom_constraints:
        logging.info(
            f"Adding custom capacity expansion constraints: {custom_constraints}"
        )
        component_capacity_expansion_constraint(
            network, custom_constraints.get("custom_constraint_filepath")
        )


def main():
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

    out_path = str(snakemake.output.solved_network_csv)

    network.export_to_csv_folder(out_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("solve_planning failed:\n%s", traceback.format_exc())
        sys.exit(1)
