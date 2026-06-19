import logging
import os
import sys
import traceback

import numpy as np
import pandas as pd
from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from helpers import setup_script_logging
from load_profile import (
    LoadProfile,
)
from pypsa import Network

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/temp.log"
)


setup_script_logging(LOG_PATH)

config = snakemake.config if snakemake is not None else None


def create_yearly_snapshots(network: Network, snapshot_config: dict) -> Network:
    """
    Create multi-year snapshots by replicating reference year snapshots.

    Takes a reference year's hourly snapshots and creates corresponding snapshots
    for each year in the target period by replacing the year in datetime stamps.

    Args:
        network: PyPSA Network object to modify.
        snapshot_config: Configuration dictionary

    Returns:
        Network with updated snapshots covering all specified years.
    """

    folder_name: str = snapshot_config["folder_name"]
    years: list[int] = config["year_settings"]["investment_period"]
    ref_year: int = config["year_settings"]["ref_year"]
    snapshot_new_df: pd.DatetimeIndex = pd.DatetimeIndex([])
    period_df: pd.DatetimeIndex = pd.DatetimeIndex([])

    # Load reference year snapshots
    ref_list: pd.DataFrame = pd.read_csv(
        os.path.join(folder_name, "snapshots.csv"), usecols=[0]
    )
    ref_list = ref_list.squeeze().tolist()

    print(f"Load shape before new snapshots: {network.loads_t.p_set.shape}")
    print(f"Load df before new snapshots: {network.loads_t.p_set}")

    # Create yearly snapshots <period_df> and create new snapshot dataframe <snapshot_new_df>
    for year in years:
        temp_list = ref_list.copy()
        temp_list = list(
            map(
                lambda x: str(x).replace(str(ref_year), str(year)),
                # lambda x: str(x).replace(str(snapshot_config["ref_year"]), str(year)),
                temp_list,
            )
        )
        period_df = pd.to_datetime(temp_list)
        snapshot_new_df = snapshot_new_df.append(period_df)

    print(f"Network snapshots=\n{snapshot_new_df}")
    # network.snapshots = snapshot_new_df
    network.set_snapshots(snapshot_new_df)

    return network


# TODO Verify why canada model doesn't do this part auto. when applying I.P.
def save_ref_year_data(
    network: Network, network_ref: Network, timestep: int = 8760
) -> Network:
    """
    Replicate reference-year time-series data across all investment periods.

    After ``create_yearly_snapshots`` expands the snapshot index to cover every
    investment year, the newly added rows are empty.  This function fills them
    by tiling the reference-year data (taken from ``network_ref``) once per
    period for each supported time-varying attribute.

    Only attributes that are non-empty in ``network_ref`` are replicated, so
    optional CSVs (e.g. ``generators-p_min_pu.csv``) are handled gracefully
    without raising errors when they are absent.

    Args:
        network: Target network whose expanded snapshot index needs populating.
        network_ref: Copy of the network before snapshot expansion, holding the
            single reference-year time series.
        timestep: Number of hourly timesteps per investment period. Default 8760
            (one non-leap year).

    Returns:
        Network with all time-varying attributes replicated for every period.
    """
    # Declare every (reference component_t, target component_t, attribute) triplet
    # that should be tiled across investment periods.
    component_timeseries = [
        (network_ref.generators_t, network.generators_t, "p_max_pu"),
        (network_ref.generators_t, network.generators_t, "p_min_pu"),
        (network_ref.generators_t, network.generators_t, "marginal_cost"),
        (network_ref.generators_t, network.generators_t, "carbon_cost"),
        (network_ref.generators_t, network.generators_t, "fuel_cost"),
        (network_ref.generators_t, network.generators_t, "variable_cost"),
        (network_ref.storage_units_t, network.storage_units_t, "inflow"),
        (network_ref.links_t, network.links_t, "p_max_pu"),
        # not needed? TODO verify
        # (network_ref.links_t, network.links_t, "p_min_pu"),
    ]

    # Pre-filter to attributes that actually contain data in the reference network,
    # and snapshot the reference values before any in-place writes occur.
    replication_targets = [
        (getattr(target_component, attr), getattr(ref_component, attr).copy())
        for ref_component, target_component, attr in component_timeseries
        if not getattr(ref_component, attr).empty
    ]

    for i in range(len(config["year_settings"]["investment_period"])):
        # Compute the flat integer slice for this period's rows.
        start, end = i * timestep, (i + 1) * timestep
        # Weight each hourly snapshot equally within the period.
        network.snapshot_weightings[start:end] = 1
        # Tile each reference time series into the corresponding period slice.
        for target_ts, ref_ts in replication_targets:
            target_ts[start:end] = ref_ts.values

    return network


def create_yearly_weightings(
    network: Network,
    snapshot_config: dict,
    discount_rate: float = 0.05,
) -> Network:
    """
    Create multi-period snapshots with investment weightings and load growth.

    Converts snapshots to multi-index format (period, timestep), sets investment
    periods, applies load growth forecasts, and calculates investment weightings
    based on the discount rate.

    Args:
        network: Target network to configure with multi-period data.
        snapshot_config: Configuration dictionary
        discount_rate: Discount rate for net present value calculations. Default 0.05.

    Returns:
        Network configured for multi-period optimization with investment weightings.
    """
    years = config["year_settings"]["investment_period"]
    load_mode = LoadProfile[snapshot_config["load_mode"].upper()]
    snapshot_new_df = network.snapshots

    # Save custom dynamic attributes before re-indexing snapshots,
    # because the MultiIndex conversion will NaN-out any attributes
    # that PyPSA doesn't know how to re-index.
    custom_dynamic_attrs = {}
    for attr in ["carbon_cost", "fuel_cost", "variable_cost"]:
        df = getattr(network.generators_t, attr, None)
        if df is not None and not df.empty:
            custom_dynamic_attrs[attr] = df.values.copy()

    # Convert to multi-index with period (year) and timestep
    network.snapshots = pd.MultiIndex.from_arrays(
        [snapshot_new_df.year, snapshot_new_df], names=["period", "timestep"]
    )

    # Restore custom dynamic attributes with the new index
    for attr, values in custom_dynamic_attrs.items():
        old_df = getattr(network.generators_t, attr)
        setattr(
            network.generators_t,
            attr,
            pd.DataFrame(values, index=network.snapshots, columns=old_df.columns),
        )

    print(f"Investment periods: {years}")
    network.periods = years

    # Apply load growth based on selected profile
    network = _apply_load_profile(network, load_mode)

    print(f"Load profile shape after snapshots: {network.loads_t.p_set.shape}")
    print(f"Load profile after snapshots:\n{network.loads_t.p_set}")

    network.investment_period_weightings["years"] = list(np.diff(years)) + [
        snapshot_config["last_investment_period"]
    ]
    generate_investment_weightings(n=network, years=years, discount_rate=discount_rate)

    return network


def generate_investment_weightings(
    n: Network, years: list[int], discount_rate: float = 0.05
) -> Network:
    """
    Function to generate the investment weightings based on the discount rate.
    Code taken from the example of pypsa tutorial:
    https://pypsa.readthedocs.io/en/latest/examples/multi-investment-optimisation.html

    Parameters
    ----------
    n : pypsa.Network
        The pypsa network that will be modified
    years : list[int]
        list of investment periods that will be used to calculate
        the investment periods
    discount_rate : float, optional
        the discount rate used to make the calculation of the
        weightings, by default 0.05
    """
    T = 0
    for period, nyears in n.investment_period_weightings.years.items():
        discounts = [(1 / (1 + discount_rate) ** t) for t in range(T, T + nyears)]
        n.investment_period_weightings.at[period, "objective"] = sum(discounts)
        T += nyears

    return n


def _apply_load_profile(
    network: Network,
    load_mode: LoadProfile,  # snapshot_config: dict
) -> Network:
    """
    Apply load growth to network based on selected load profile mode.

    Loads the pre-computed load forecast data and applies it to the network
    based on the specified load profile type.

    Args:
        network: PyPSA Network to update with load forecast.
        load_mode: Type of load profile to apply (from LoadProfile enum).

    Returns:
        Network with updated load time series.

    Raises:
        NotImplementedError: If the selected load mode is not yet implemented.
    """
    if load_mode == LoadProfile.DEFAULT:
        logging.info(
            "Using default load profile: base network load without applying growth forecast."
        )
        return network

    loads_forecast_df: pd.DataFrame = pd.read_csv(
        snakemake.input.loads_p_set, index_col=[0]
    )

    match load_mode:
        case LoadProfile.FULL_LOAD:
            logging.info(
                "Using full load profile: applying pre-computed load forecast to network."
            )
            network.loads_t.p_set = loads_forecast_df.copy()
            return network
        case LoadProfile.GROWTH_FORECAST:
            logging.info(
                "Using growth forecast load profile: applying load growth forecast to network for all investment periods."
            )
            network.loads_t.p_set = loads_forecast_df.copy()
            return network
        case LoadProfile.CER:
            raise NotImplementedError("CER load profile processing not yet implemented")
        case LoadProfile.CODERS:
            raise NotImplementedError(
                "CODERS load profile processing not yet implemented"
            )
        case _:
            raise ValueError(
                f"Invalid load mode: {load_mode}. Check load_profile option in config."
            )


def main():
    if snakemake is None:
        raise RuntimeError("add_snapshots.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    network = Network(snakemake.input.input_data)
    discount_rate = config["year_settings"]["discount_rate"]
    network_ref = network.copy()
    snapshot_config = config["snapshots"]

    network = create_yearly_snapshots(network=network, snapshot_config=snapshot_config)
    network = save_ref_year_data(network, network_ref)
    network = create_yearly_weightings(
        network=network, snapshot_config=snapshot_config, discount_rate=discount_rate
    )

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if config["run"]["export_csv"]:
        network.export_to_csv_folder(
            f"{snakemake.output.planning_unsolved_network[:-3]}_csv"
        )

    finish_benchmark_tracker(
        result_benchmark_csv_path(snakemake.output.planning_unsolved_network),
        "add_snapshots",
        benchmark_timer,
        benchmark_memory,
    )

    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_snapshot failed:\n%s", traceback.format_exc())
        sys.exit(1)
