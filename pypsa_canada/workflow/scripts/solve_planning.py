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
    # m = network.model

    # The snapshots must only contain one unique year
    period_list = network.snapshots.get_level_values(0).unique()
    logging.info(f"Period list = {period_list}")

    # Add binary spilling variable (1: spilling, 0: not spilling) to Linopy model
    # spilling_variable_ena = constraint_dict.get("add_spilling_variable")
    # logging.info(f'Add Spilling Variable has been set to {spilling_variable_ena}')
    # if spilling_variable_ena:
    #     add_spilling_variable(
    #         network=network,
    #         snapshots=network.snapshots
    #     )

    # Add bidirectional link constraint (applies to all periods)
    if "add_bidirection_link_constraint" in constraint_dict:
        links_constraint_dict = constraint_dict["add_bidirection_link_constraint"]
        logging.info(f"Adding bidirectional link constraint: {links_constraint_dict}")
        add_bidirection_link_constraint(network, links_constraint_dict)

    # # Add prevent spill if not fully charged constraint (applies to all periods)
    # if "add_prevent_spill_if_not_fully_charged_constraint" in constraint_dict:
    #     if ("maximum_soc_storage_value" in
    #         constraint_dict["add_prevent_spill_if_not_fully_charged_constraint"]):
    #         maximum_soc_storage_value = constraint_dict[
    #             "add_prevent_spill_if_not_fully_charged_constraint"
    #         ]["maximum_soc_storage_value"]
    #         logging.info(f"Adding prevent spill constraint with M={maximum_soc_storage_value}")
    #         prevent_spill_if_not_fully_charged(
    #             network, network.snapshots, maximum_soc_storage_value
    #         )

    # Per-period constraints
    # spilling_variable_ena = constraint_dict.get("add_spilling_variable")
    # logging.info(f'Add Spilling Variable has been set to {spilling_variable_ena}')
    # if spilling_variable_ena:
    #     add_spilling_variable(
    #         network=network,
    #         snapshots=network.snapshots
    #     )

    # Add bidirectional link constraint (applies to all periods)
    if "add_bidirection_link_constraint" in constraint_dict:
        links_constraint_dict = constraint_dict["add_bidirection_link_constraint"]
        logging.info(f"Adding bidirectional link constraint: {links_constraint_dict}")
        add_bidirection_link_constraint(network, links_constraint_dict)

    # # Add prevent spill if not fully charged constraint (applies to all periods)
    # if "add_prevent_spill_if_not_fully_charged_constraint" in constraint_dict:
    #     if ("maximum_soc_storage_value" in
    #         constraint_dict["add_prevent_spill_if_not_fully_charged_constraint"]):
    #         maximum_soc_storage_value = constraint_dict[
    #             "add_prevent_spill_if_not_fully_charged_constraint"
    #         ]["maximum_soc_storage_value"]
    #         logging.info(f"Adding prevent spill constraint with M={maximum_soc_storage_value}")
    #         prevent_spill_if_not_fully_charged(
    #             network, network.snapshots, maximum_soc_storage_value
    #         )

    # Per-period constraints
    for period in period_list:
        period_snapshots = network.snapshots[
            network.snapshots.get_level_values(0) == period
        ]
        logging.info(f"Processing constraints for period {period}")
        logging.info(f"Processing constraints for period {period}")
        logging.info(f"Network multi-index = {period_snapshots}")

        # Stop production constraint

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

            # add_planning_reserve_margin(m, self.network, year, prov, margin)
            # if "provinces" in reserve_margin_config:
            #     provinces = reserve_margin_config["provinces"]
            #     margin = reserve_margin_config.get("margin", 1.2)
            #     # Check for province-specific margins
            #     province_margins = reserve_margin_config.get("province_margins", {})
            #     for province in provinces:
            #         prov_margin = province_margins.get(province, margin)
            #         logging.info(f"Adding reserve margin constraint for {province} in {period} with margin {prov_margin}")

            #         add_planning_reserve_margin(
            #             network, period_snapshots, province, prov_margin
            #         )

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

    # # Log final constraint count
    # final_constraint_count = len(m.constraints) if hasattr(m, 'constraints') else 0
    # logging.info(f"=== Finished add_all_planning_constraints ===")
    # logging.info(f"Final constraint count: {final_constraint_count}")
    # logging.info(f"Constraints added: {final_constraint_count - initial_constraint_count}")

    # # Log constraint names for debugging
    # if hasattr(m, 'constraints'):
    #     # Linopy constraints are accessed via attributes, not keys()
    #     planning_constraints = [name for name in dir(m.constraints)
    #                            if not name.startswith('_') and
    #                            ('Planning' in name or 'GlobalConstraint' in name)]
    #     if planning_constraints:
    #         logging.info(f"Custom planning constraints added ({len(planning_constraints)}):")
    #         for name in planning_constraints:
    #             logging.info(f"  - {name}")


# def rename_dims(n):
#     for c in ["generators", "links", "storage_units"]:
#         df = getattr(n, c)
#         if "committable" in df.columns:
#             print(f"\n{c} committable:", df[(df.committable)&(df.p_nom_extendable)].index.tolist())
#         # if "p_nom_extendable" in df.columns:
#             # print(f"{c} extendable:", df[df.p_nom_extendable].index.tolist())


# def fix_network_dataarray_dims(network):
#     """
#     Fix DataArray dimension names after loading from netCDF.

#     When snapshots are MultiIndex, PyPSA may create DataArrays with generic
#     dimension names like 'dim_0' instead of 'snapshot', causing alignment errors.
#     This fixes those dimension names before model creation.
#     """
#     # Ensure all time-varying component DataFrames have properly named indices
#     for component_t in ['generators_t', 'storage_units_t', 'loads_t', 'links_t', 'stores_t']:
#         if hasattr(network, component_t):
#             comp_t_obj = getattr(network, component_t)
#             for attr_name in dir(comp_t_obj):
#                 if not attr_name.startswith('_'):
#                     try:
#                         attr = getattr(comp_t_obj, attr_name)
#                         if hasattr(attr, 'index'):
#                             # Fix the index.name attribute (not .names for level names)
#                             if attr.index.name == 'dim_0' or attr.index.name is None:
#                                 attr.index.name = 'snapshot'
#                                 logging.info(f"Fixed index name for {component_t}.{attr_name}")
#                             # Also ensure MultiIndex level names are correct
#                             if hasattr(attr.index, 'names') and len(attr.index.names) == 2:
#                                 if attr.index.names[0] is None or attr.index.names[1] is None:
#                                     attr.index.names = ['period', 'timestep']
#                                     logging.info(f"Fixed index level names for {component_t}.{attr_name}")
#                     except (AttributeError, TypeError):
#                         pass

#     # Also fix the main snapshots index
#     if hasattr(network.snapshots, 'name'):
#         if network.snapshots.name == 'dim_0' or network.snapshots.name is None:
#             network.snapshots.name = 'snapshot'
#             logging.info("Fixed snapshots index name")

#     return network

# def fix_snapshot_dim(n):
#     """Rename dim_0 -> snapshot in all dynamic component dataframes."""
#     # Iterate over time-varying (_t) component attributes instead of using deprecated dynamic()
#     # for component_t_name in ['generators_t', 'storage_units_t', 'loads_t', 'links_t', 'stores_t', 'lines_t', 'transformers_t']:
#     for component_t_name in ['storage_units_t']:
#         if not hasattr(n, component_t_name):
#             continue

#         component_t = getattr(n, component_t_name)
#         print(f'Component {component_t_name}')
#         print(f'component_t {component_t}')

#         # Iterate over attributes (e.g., p_max_pu, inflow, etc.)
#         for key in dir(component_t):
#             if key.startswith('_'):
#                 continue
#             try:
#                 da = getattr(component_t, key)
#                 if hasattr(da, 'dims') and "dim_0" in da.dims:
#                     renamed_da = da.rename({"dim_0": "snapshot"})
#                     setattr(component_t, key, renamed_da)
#                     print(f"Fixed dim_0 -> snapshot in {component_t_name}.{key}")
#             except (AttributeError, TypeError):
#                 pass


def main():
    network = pypsa.Network(snakemake.input.planning_unsolved_network)
    disable_committable_for_OPT(network)

    # # TODO Temporary fix for standing_loss dim_0 issue - should be fixed in the network loading step instead
    # network.storage_units_t.standing_loss = (
    #     network.storage_units_t.standing_loss.rename({"dim_0": "snapshot"})
    # )

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

    network.optimize.add_load_shedding(marginal_cost=1000000, sign=1.0)

    model = network.optimize.create_model(multi_investment_periods=True)  # NOQA

    solver_settings = config["solving"]["solver"]

    solve_status, solve_condition = network.optimize.solve_model(
        # multi_investment_periods=True,
        # assign_all_duals=True,
        solver_name=solver_settings["name"],
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
