# scripts/solve_planning.py
import logging
import os
import sys
import traceback

import numpy as np
import pandas as pd
import pypsa
from helpers import setup_script_logging

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/solve_dispatch.log"


setup_script_logging(LOG_PATH)

config = snakemake.config


def extract_investment_periods(network: pypsa.Network) -> list:
    """
    Extract unique investment periods from a multi-period network.

    Parameters
    ----------
    network : pypsa.Network
        Network with multi-period snapshots

    Returns
    -------
    List
        Sorted list of investment periods (preserves original format)
    """
    if isinstance(network.snapshots, pd.MultiIndex):
        periods = network.snapshots.get_level_values("period").unique()
        # Return periods as-is, don't try to convert
        return sorted(list(periods))
    else:
        # Single period network - return the first snapshot's period marker
        return [network.snapshots[0]]


def flatten_multiperiod_network(network: pypsa.Network) -> pypsa.Network:
    """
    Flatten a multi-period network into a single-period network with all periods preserved.

    This function converts the MultiIndex snapshots to a simple DatetimeIndex while keeping
    all investment periods as a continuous time series. All components and time-series data
    are preserved exactly as-is.

    Parameters
    ----------
    network : pypsa.Network
        Myopic foresight network with multi-period snapshots

    Returns
    -------
    pypsa.Network
        Flattened network with all periods in a continuous DatetimeIndex
    """
    logging.info("Flattening multi-period network to preserve all periods...")

    # Check if network has multi-period structure
    if not isinstance(network.snapshots, pd.MultiIndex):
        logging.info("Network already has single-level snapshot index")
        return network.copy()

    # Extract all periods
    periods = extract_investment_periods(network)
    logging.info(f"Found {len(periods)} investment periods: {periods}")

    # Log the actual period index to help debug
    logging.info(
        f"Period level values sample: {network.snapshots.get_level_values('period').unique()[:5]}"
    )

    # Create flattened snapshot index
    # Create a continuous time series by offsetting each period
    all_snapshots = []

    for i, period in enumerate(periods):
        # Get mask for this period - direct comparison without conversion
        period_level = network.snapshots.get_level_values("period")
        period_mask = period_level == period

        period_snapshots = network.snapshots[period_mask]
        period_times = period_snapshots.get_level_values(1)

        # # Offset snapshots to create continuous series
        # if i == 0:
        #     offset_snapshots = period_times
        # else:
        #     # Add offset based on previous periods
        #     time_offset = pd.Timedelta(days=365 * i)
        #     logging.info(f'Time offset = {time_offset}')
        #     offset_snapshots = period_times + time_offset
        #     logging.info(f'offset_snapshots = {offset_snapshots}')

        # all_snapshots.extend(offset_snapshots)
        all_snapshots.extend(period_times)

    # Create new network with flattened snapshots
    flat_net = pypsa.Network()
    flat_net.set_snapshots(pd.DatetimeIndex(all_snapshots))

    # Copy network-level attributes
    for attr in ["name", "srid", "now"]:
        if hasattr(network, attr):
            setattr(flat_net, attr, getattr(network, attr))

    # Handle snapshot weightings - concatenate all periods
    if hasattr(network, "snapshot_weightings"):
        all_weightings = []
        for period in periods:
            # Get mask for this period - direct comparison
            period_level = network.snapshots.get_level_values("period")
            period_mask = period_level == period

            period_weightings = network.snapshot_weightings.loc[
                network.snapshots[period_mask]
            ]
            all_weightings.append(period_weightings.values)
        flat_net.snapshot_weightings[:] = np.concatenate(all_weightings)

    # Copy carriers and buses
    logging.info("Copying buses and carriers...")
    flat_net._import_components_from_df(network.buses, "Bus")
    if not network.carriers.empty:
        flat_net._import_components_from_df(network.carriers, "Carrier")

    # Process each component type
    # Get list of available components dynamically from the network
    for component_name in network.components.keys():
        component = network.components[component_name]
        list_name = component["list_name"]

        # Skip buses and carriers (already copied)
        if list_name in ["buses", "carriers"]:
            continue

        df = getattr(network, list_name)

        logging.info(
            f"Found {component_name}: list_name={list_name}, df shape={df.shape}"
        )

        if df.empty:
            logging.info(f"  Skipping {component_name} - dataframe is empty")
            continue

        logging.info(f"Processing {component_name}s...")

        # Copy dataframe as-is (preserve all original attributes)
        new_df = df.copy()

        logging.info(f"  Importing {len(new_df)} {component_name}s to flat network...")

        # Import static data
        try:
            flat_net._import_components_from_df(new_df, component_name)
            logging.info(f"  Successfully imported {component_name}s")
        except Exception as e:
            logging.error(f"  Failed to import {component_name}s: {e}")
            continue

        # Process time-series data - concatenate all periods
        pnl = getattr(network, list_name + "_t")
        new_pnl = getattr(flat_net, list_name + "_t")

        # Get all time-varying attributes for this component
        # Check which attributes in pnl have data
        for attr_name in dir(pnl):
            # Skip private attributes and methods
            if attr_name.startswith("_") or callable(getattr(pnl, attr_name)):
                continue

            ts_data = getattr(pnl, attr_name, None)

            # Check if it's a DataFrame with data
            if not isinstance(ts_data, pd.DataFrame) or ts_data.empty:
                continue

            logging.info(f"  Processing time-series '{attr_name}'...")

            # Concatenate time-series from all periods
            all_period_data = []

            for i, period in enumerate(periods):
                # Get mask for this period - direct comparison
                period_level = network.snapshots.get_level_values("period")
                period_mask = period_level == period

                period_snapshots = network.snapshots[period_mask]

                # Check if this time-series has data for these snapshots
                try:
                    period_ts = ts_data.loc[period_snapshots]
                except KeyError:
                    logging.warning(
                        f"  Skipping '{attr_name}' for period {period} - no data found"
                    )
                    continue

                # Create offset snapshots for this period
                if i == 0:
                    offset_snapshots = period_snapshots.get_level_values(1)
                else:
                    time_offset = pd.Timedelta(days=365 * i)
                    offset_snapshots = (
                        period_snapshots.get_level_values(1) + time_offset
                    )

                period_ts.index = offset_snapshots
                all_period_data.append(period_ts)

            if not all_period_data:
                logging.warning(
                    f"  No data found for time-series '{attr_name}', skipping"
                )
                continue

            # Concatenate all periods
            concatenated_ts = pd.concat(all_period_data, axis=0)

            # Set in new network
            setattr(new_pnl, attr_name, concatenated_ts)

            logging.info(
                f"  Concatenated time-series '{attr_name}' with shape {concatenated_ts.shape}"
            )

    # # Copy global constraints if they exist
    # if hasattr(network, 'global_constraints') and not network.global_constraints.empty:
    #     flat_net.global_constraints = network.global_constraints.copy()

    logging.info("Flattening complete!")
    logging.info(f"  Total snapshots: {len(flat_net.snapshots)}")
    logging.info(f"  Buses: {len(flat_net.buses)}")
    logging.info(f"  Generators: {len(flat_net.generators)}")
    logging.info(f"  Storage units: {len(flat_net.storage_units)}")
    logging.info(f"  Loads: {len(flat_net.loads)}")

    return flat_net


# def flatten_multiperiod_network(
#     network: pypsa.Network,
#     fix_capacities: bool = True,
#     enable_unit_commitment: bool = False,
#     committable_carriers: Optional[List[str]] = None,
#     uc_parameters: Optional[Dict[str, float]] = None,
#     preserve_extendable: bool = False
# ) -> pypsa.Network:
#     """
#     Flatten a multi-period network into a single-period network with all periods preserved.

#     This function converts the MultiIndex snapshots to a simple DatetimeIndex while keeping
#     all investment periods as a continuous time series. Components are preserved with their
#     period information in the time series.

#     Parameters
#     ----------
#     network : pypsa.Network
#         Myopic foresight network with multi-period snapshots
#     fix_capacities : bool, default True
#         If True, sets p_nom from p_nom_opt and disables extendable flags
#     enable_unit_commitment : bool, default False
#         Whether to enable unit commitment constraints
#     committable_carriers : List[str], optional
#         List of carrier types that should be committable (e.g., ['coal', 'gas', 'nuclear'])
#     uc_parameters : Dict[str, float], optional
#         Unit commitment parameters:
#         - 'min_up_time': Minimum up time in hours (default: 4)
#         - 'min_down_time': Minimum down time in hours (default: 4)
#         - 'start_up_cost': Start-up cost (default: 0)
#         - 'shut_down_cost': Shut-down cost (default: 0)
#     preserve_extendable : bool, default False
#         If True, keeps extendable flags even when fix_capacities=True

#     Returns
#     -------
#     pypsa.Network
#         Flattened network with all periods in a continuous DatetimeIndex
#     """
#     logging.info("Flattening multi-period network to preserve all periods...")

#     # Check if network has multi-period structure
#     if not isinstance(network.snapshots, pd.MultiIndex):
#         logging.info("Network already has single-level snapshot index")
#         return network.copy()

#     # Extract all periods
#     periods = extract_investment_periods(network)
#     logging.info(f"Found {len(periods)} investment periods: {periods}")

#     # Log the actual period index to help debug
#     logging.info(f"Period level values sample: {network.snapshots.get_level_values('period').unique()[:5]}")

#     # Create flattened snapshot index
#     # Create a continuous time series by offsetting each period
#     all_snapshots = []

#     for i, period in enumerate(periods):
#         # Get mask for this period - direct comparison without conversion
#         period_level = network.snapshots.get_level_values('period')
#         period_mask = period_level == period

#         period_snapshots = network.snapshots[period_mask]
#         period_times = period_snapshots.get_level_values(1)

#         # Offset snapshots to create continuous series
#         if i == 0:
#             offset_snapshots = period_times
#         else:
#             # Add offset based on previous periods
#             time_offset = pd.Timedelta(days=365 * i)
#             offset_snapshots = period_times + time_offset

#         all_snapshots.extend(offset_snapshots)

#     # Create new network with flattened snapshots
#     flat_net = pypsa.Network()
#     flat_net.set_snapshots(pd.DatetimeIndex(all_snapshots))

#     # Copy network-level attributes
#     for attr in ['name', 'srid', 'now']:
#         if hasattr(network, attr):
#             setattr(flat_net, attr, getattr(network, attr))

#     # Handle snapshot weightings - concatenate all periods
#     if hasattr(network, 'snapshot_weightings'):
#         all_weightings = []
#         for period in periods:
#             # Get mask for this period - direct comparison
#             period_level = network.snapshots.get_level_values('period')
#             period_mask = period_level == period

#             period_weightings = network.snapshot_weightings.loc[network.snapshots[period_mask]]
#             all_weightings.append(period_weightings.values)
#         flat_net.snapshot_weightings[:] = np.concatenate(all_weightings)

#     # Copy carriers and buses
#     logging.info("Copying buses and carriers...")
#     flat_net._import_components_from_df(network.buses, 'Bus')
#     if not network.carriers.empty:
#         flat_net._import_components_from_df(network.carriers, 'Carrier')

#     # Set default UC parameters
#     if uc_parameters is None:
#         uc_parameters = {
#             'min_up_time': 4,
#             'min_down_time': 4,
#             'start_up_cost': 0,
#             'shut_down_cost': 0
#         }

#     # Process each component type
#     component_types = [
#         'Generator', 'StorageUnit', 'Store', 'Load',
#         'Line', 'Link', 'Transformer', 'ShuntImpedance'
#     ]

#     for component_name in component_types:
#         if component_name not in network.components.keys():
#             continue

#         component = network.components[component_name]
#         df = getattr(network, component['list_name'])

#         if df.empty:
#             continue

#         logging.info(f"Processing {component_name}s...")

#         # Copy dataframe
#         new_df = df.copy()

#         # # Optionally fix capacities
#         # if fix_capacities:
#         #     if 'p_nom_opt' in new_df.columns and new_df['p_nom_opt'].notna().any():
#         #         new_df['p_nom'] = new_df['p_nom_opt']
#         #         if not preserve_extendable:
#         #             new_df['p_nom_extendable'] = False
#         #         logging.info(f"  Set p_nom from p_nom_opt for {len(new_df)} {component_name}s")

#         #     if 's_nom_opt' in new_df.columns and new_df['s_nom_opt'].notna().any():
#         #         new_df['s_nom'] = new_df['s_nom_opt']
#         #         if not preserve_extendable:
#         #             new_df['s_nom_extendable'] = False

#         #     if 'e_nom_opt' in new_df.columns and new_df['e_nom_opt'].notna().any():
#         #         new_df['e_nom'] = new_df['e_nom_opt']
#         #         if not preserve_extendable:
#         #             new_df['e_nom_extendable'] = False

#         # # Enable unit commitment if requested
#         # if enable_unit_commitment and component_name == 'Generator':
#         #     if committable_carriers is None:
#         #         committable_carriers = ['coal', 'gas', 'CCGT', 'OCGT', 'oil', 'nuclear']

#         #     committable_mask = new_df['carrier'].isin(committable_carriers)
#         #     new_df.loc[committable_mask, 'committable'] = True

#         #     for param, value in uc_parameters.items():
#         #         if param in new_df.columns:
#         #             new_df.loc[committable_mask, param] = value

#         #     n_committable = committable_mask.sum()
#         #     logging.info(f"  Enabled unit commitment for {n_committable} generators")

#         # Import static data
#         flat_net.import_components_from_dataframe(new_df, component_name)

#         # Process time-series data - concatenate all periods
#         pnl = getattr(network, component['list_name'] + '_t')
#         new_pnl = getattr(flat_net, component['list_name'] + '_t')

#         for attr in component.get('attrs', []):
#             attr_name = attr['name']
#             if not attr.get('varying', False):
#                 continue

#             ts_data = getattr(pnl, attr_name, pd.DataFrame())

#             if ts_data.empty:
#                 continue

#             # Concatenate time-series from all periods
#             all_period_data = []

#             for i, period in enumerate(periods):
#                 # Get mask for this period - direct comparison
#                 period_level = network.snapshots.get_level_values('period')
#                 period_mask = period_level == period

#                 period_snapshots = network.snapshots[period_mask]
#                 period_ts = ts_data.loc[period_snapshots]

#                 # Create offset snapshots for this period
#                 if i == 0:
#                     offset_snapshots = period_snapshots.get_level_values(1)
#                 else:
#                     time_offset = pd.Timedelta(days=365 * i)
#                     offset_snapshots = period_snapshots.get_level_values(1) + time_offset

#                 period_ts.index = offset_snapshots
#                 all_period_data.append(period_ts)

#             # Concatenate all periods
#             concatenated_ts = pd.concat(all_period_data, axis=0)

#             # Set in new network
#             setattr(new_pnl, attr_name, concatenated_ts)

#             logging.info(f"  Concatenated time-series '{attr_name}' with shape {concatenated_ts.shape}")

#     # Copy global constraints if they exist
#     if hasattr(network, 'global_constraints') and not network.global_constraints.empty:
#         flat_net.global_constraints = network.global_constraints.copy()

#     logging.info(f"Flattening complete!")
#     logging.info(f"  Total snapshots: {len(flat_net.snapshots)}")
#     logging.info(f"  Buses: {len(flat_net.buses)}")
#     logging.info(f"  Generators: {len(flat_net.generators)}")
#     logging.info(f"  Storage units: {len(flat_net.storage_units)}")
#     logging.info(f"  Loads: {len(flat_net.loads)}")

#     return flat_net


def main():
    network = pypsa.Network(snakemake.input.planning_unsolved_network_unfiltered)

    # Applying Optimal Generators Values to Unfiltered Network
    optimal_gen_values = pd.read_csv(
        os.path.join(snakemake.input.planning_solved_network, "generators.csv"),
        index_col="name",
    )
    optimal_gen_values = optimal_gen_values[optimal_gen_values["model"].notna()]
    network.generators.p_nom_opt = optimal_gen_values["p_nom_opt"].values

    # Applying Optimal Storage-units Values to Unfiltered Network
    if os.path.exists(os.path.join(snakemake.input.planning_solved_network, "storage-units.csv")):
        optimal_storage_values = pd.read_csv(
            os.path.join(snakemake.input.planning_solved_network, "storage-units.csv"),
            index_col="name",
        )
        optimal_storage_values = optimal_storage_values[optimal_storage_values["model"].notna()]
        network.storage_units.p_nom_opt = optimal_storage_values["p_nom_opt"].values

    # Applying Optimal Stores Values to Unfiltered Network
    if os.path.exists(os.path.join(snakemake.input.planning_solved_network, "stores.csv")):
        optimal_store_values = pd.read_csv(
            os.path.join(snakemake.input.planning_solved_network, "stores.csv"),
            index_col="name",
        )
        optimal_store_values = optimal_store_values[optimal_store_values["model"].notna()]
        network.stores.e_nom_opt = optimal_store_values["e_nom_opt"].values

    # Applying Optimal Lines Values to Unfiltered Network
    if os.path.exists(os.path.join(snakemake.input.planning_solved_network, "lines.csv")): 
        optimal_line_values = pd.read_csv(
            os.path.join(snakemake.input.planning_solved_network, "lines.csv"),
            index_col="name",
        )
        optimal_line_values = optimal_line_values[optimal_line_values["model"].notna()]
        network.lines.s_nom_opt = optimal_line_values["s_nom_opt"].values

    # Applying Optimal Links Values to Unfiltered Network
    if os.path.exists(os.path.join(snakemake.input.planning_solved_network, "links.csv")):
        optimal_link_values = pd.read_csv(
            os.path.join(snakemake.input.planning_solved_network, "links.csv"),
            index_col="name",
        )
        optimal_link_values = optimal_link_values[optimal_link_values["model"].notna()]
        network.links.p_nom_opt = optimal_link_values["p_nom_opt"].values

    # Applying Optimal Transformers Values to Unfiltered Network
    if os.path.exists(os.path.join(snakemake.input.planning_solved_network, "transformers.csv")):
        optimal_transfo_values = pd.read_csv(
            os.path.join(snakemake.input.planning_solved_network, "transformers.csv"),
            index_col="name",
        )
        optimal_transfo_values = optimal_transfo_values[optimal_transfo_values["model"].notna()]
        network.transformers.s_nom_opt = optimal_transfo_values["s_nom_opt"].values

    # Re-establish correct weighting
    # TODO Verify if we put 1,1,1 or something
    network.snapshot_weightings.loc[:, ["objective", "stores", "generators"]] = 1

    # TODO move this to a function
    # Set all committables components to True
    if not network.generators.empty:
        network.generators.loc[
            network.generators.carrier.isin(["coal", "gas", "nuclear"]), "committable"
        ] = True
    # TODO Validate if all links should be committable?
    if not network.links.empty:
        network.links.loc[:, "committable"] = True

    # Set Optimal Capacity to all Components
    network.optimize.fix_optimal_capacities()
    dispatch_network = flatten_multiperiod_network(network)
    dispatch_network.export_to_netcdf(
        snakemake.output.dispatch_planning_unsolved_network_nc
    )
    dispatch_network.export_to_csv_folder(
        snakemake.output.dispatch_planning_unsolved_network_csv
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("convert network to dispatch failed:\n%s", traceback.format_exc())
        sys.exit(1)
