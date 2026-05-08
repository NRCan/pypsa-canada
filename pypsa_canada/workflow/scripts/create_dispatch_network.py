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


def copy_optimal_capacity_values(
    target_df: pd.DataFrame,
    source_df: pd.DataFrame,
    value_column: str,
    exclude_load_shedding: bool = False,
) -> None:
    if target_df.empty or source_df.empty or value_column not in source_df.columns:
        return

    aligned_source = source_df.reindex(target_df.index)

    if exclude_load_shedding:
        load_shedding_mask = aligned_source.index.to_series().str.contains(
            "load shedding", case=False, na=False
        )
        if "carrier" in aligned_source.columns:
            load_shedding_mask |= aligned_source["carrier"].astype(str).str.contains(
                "load_shedding", case=False, na=False
            )
        if "model" in aligned_source.columns:
            load_shedding_mask |= aligned_source["model"].astype(str).str.contains(
                "load_shedding", case=False, na=False
            )
        aligned_source = aligned_source.loc[~load_shedding_mask]

    valid_values = aligned_source[value_column].notna()
    if valid_values.any():
        target_df.loc[valid_values, value_column] = aligned_source.loc[
            valid_values, value_column
        ]


def remove_zero_capacity_components(network: pypsa.Network) -> None:
    component_capacity_columns = {
        "Generator": "p_nom",
        "StorageUnit": "p_nom",
        "Store": "e_nom",
        "Line": "s_nom",
        "Link": "p_nom",
        "Transformer": "s_nom",
    }

    for component_name, capacity_column in component_capacity_columns.items():
        if component_name not in network.components.keys():
            continue

        component_df = getattr(network, network.components[component_name]["list_name"])
        if component_df.empty or capacity_column not in component_df.columns:
            continue

        zero_capacity_names = component_df.index[
            component_df[capacity_column].fillna(0) == 0
        ]
        if len(zero_capacity_names) > 0:
            network.mremove(component_name, list(zero_capacity_names))


def main():
    solved_planning_network = pypsa.Network(snakemake.input.planning_solved_network)
    network = pypsa.Network(snakemake.input.planning_unsolved_network_unfiltered)

    # Copy optimized capacities from the solved planning network.
    # Load-shedding generators are omitted from the dispatch network.
    copy_optimal_capacity_values(
        network.generators,
        solved_planning_network.generators,
        "p_nom_opt",
        exclude_load_shedding=True,
    )
    copy_optimal_capacity_values(
        network.storage_units,
        solved_planning_network.storage_units,
        "p_nom_opt",
    )
    copy_optimal_capacity_values(network.stores, solved_planning_network.stores, "e_nom_opt")
    copy_optimal_capacity_values(network.lines, solved_planning_network.lines, "s_nom_opt")
    copy_optimal_capacity_values(network.links, solved_planning_network.links, "p_nom_opt")
    copy_optimal_capacity_values(
        network.transformers,
        solved_planning_network.transformers,
        "s_nom_opt",
    )

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
    remove_zero_capacity_components(network)

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
