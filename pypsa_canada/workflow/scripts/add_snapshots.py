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
from typing import Any

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
        # (network_ref.generators_t, network.generators_t, "carbon_cost"),
        # (network_ref.generators_t, network.generators_t, "fuel_cost"),
        # (network_ref.generators_t, network.generators_t, "variable_cost"),
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

def create_marginal_costs(
    network: Network,
    comp_config: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Create marginal cost time series for generators.

    Combines fuel costs, variable O&M, and carbon costs (with optional OBPS).
    Supports manual cost overrides via generator_price_override.csv.

    Parameters
    ----------
    network : Network
        PyPSA network object
    comp_config : dict[str, Any]
        Components configuration dictionary

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]
        Marginal costs, carbon costs, fuel costs, and variable costs
    """
    override_dir: str = comp_config["override_dir"]
    costs_dir: str = comp_config["costs_dir"]
    years: list[int] = config["year_settings"]["investment_period"]
    technology_costs: str = comp_config["technology_costs"]
    carbon_tax_dict: dict[str, int] = comp_config["carbon_tax"]
    obps: bool = comp_config["obps"]
    marginal_costs_result = pd.DataFrame()
    carbon_cost_result = pd.DataFrame()
    fuel_cost_result = pd.DataFrame()
    variable_cost_result = pd.DataFrame()

    marginal_costs_base = pd.DataFrame(network.generators.marginal_cost).T
    marginal_costs_base = marginal_costs_base.loc[
        marginal_costs_base.index.repeat(8760)
    ].reset_index(drop=True)

    manual_costs: pd.DataFrame | None = None
    override_filepath = os.path.join(override_dir, "generator_price_override.csv")
    if os.path.isfile(override_filepath):
        print("Marginal cost override file detected")
        manual_costs = pd.read_csv(override_filepath, index_col=0)

    for year in years:
        dates = pd.date_range(
            start=f"{year}-01-01", end=f"{year}-12-31 23:00:00", freq="h"
        )
        dates = dates[(dates.day != 29) | (dates.month != 2)]  # drops leap days
        marginal_costs = marginal_costs_base.copy().set_index(dates)

        # Drop the marginal costs for those manually defined, then merge manual costs
        if manual_costs is not None:
            manual_costs = manual_costs.copy().set_index(dates)
            marginal_costs = marginal_costs.drop(manual_costs.columns, axis=1)
            marginal_costs = marginal_costs.join(manual_costs)

        gen_carbon_costs = marginal_costs.copy()
        gen_variable_costs = marginal_costs.copy()
        gen_fuel_cost = marginal_costs.copy()
        ### FUEL COST CALCULATIONS ###
        # finds closest year between the technology evolution files and the run years
        fuel_costs = pd.read_csv(
            os.path.join(costs_dir, technology_costs, "fuel_costs.csv"),
            index_col=0,
        )
        tech_years = np.asarray(fuel_costs.columns.astype(int))
        tech_year = str(tech_years[(np.abs(tech_years - year)).argmin()])

        # adds carbon tax
        carbon_tax_years = np.array(list(carbon_tax_dict.keys()), dtype=int)
        carbon_tax_year = carbon_tax_years[(np.abs(carbon_tax_years - year)).argmin()]
        carbon_tax = carbon_tax_dict.get(f"{carbon_tax_year}", 0)
        print(f"Carbon tax for {year} = {carbon_tax}")

        for gen_name in marginal_costs.columns:
            carrier = network.generators.loc[gen_name].carrier
            carrier_data = network.carriers.loc[carrier]
            model = network.generators.loc[gen_name].model
            extendable = network.generators.at[gen_name, "p_nom_extendable"]
            co2_intensity = (
                carrier_data.co2_emissions / network.generators.efficiency.loc[gen_name]
            )
            if obps:
                tax_adjustment = apply_OBPS(
                    year, co2_intensity, carbon_tax, carrier_data.type, extendable
                )
            else:
                tax_adjustment = round(co2_intensity * carbon_tax, 2)

            # NOTE: Does not add fuel costs to any manually defined generators
            if manual_costs is not None:
                if model in fuel_costs.index and gen_name not in manual_costs.columns:
                    marginal_costs[gen_name] = fuel_costs.loc[model, tech_year]
                    gen_fuel_cost[gen_name] = fuel_costs.loc[model, tech_year]
                else:
                    gen_fuel_cost[gen_name] = 0
            else:
                if model in fuel_costs.index:
                    marginal_costs[gen_name] = fuel_costs.loc[model, tech_year]
                    gen_fuel_cost[gen_name] = fuel_costs.loc[model, tech_year]

            # NOTE: carbon costs are added to all generators, even those with manually-defined costs
            marginal_costs[gen_name] += tax_adjustment
            gen_carbon_costs[gen_name] = tax_adjustment

        ### VARIABLE O&M CALCULATION ###
        var_costs = pd.read_csv(
            os.path.join(costs_dir, technology_costs, "var_o_m.csv"),
            index_col=0,
        )
        tech_years = np.asarray(var_costs.columns.astype(int))
        tech_year = str(tech_years[(np.abs(tech_years - year)).argmin()])
        # NOTE: variable O&M not added to manually-defined generator costs
        for gen_name in marginal_costs.columns:
            model = network.generators.loc[gen_name].model
            if manual_costs is not None:
                if model in var_costs.index and gen_name not in manual_costs.columns:
                    marginal_costs[gen_name] += var_costs.loc[model, tech_year]
                    gen_variable_costs[gen_name] = var_costs.loc[model, tech_year]
                else:
                    gen_variable_costs[gen_name] = 0
            else:
                if model in var_costs.index:
                    marginal_costs[gen_name] += var_costs.loc[model, tech_year]
                    gen_variable_costs[gen_name] = var_costs.loc[model, tech_year]

        marginal_costs_result = pd.concat([marginal_costs_result, marginal_costs])
        carbon_cost_result = pd.concat([carbon_cost_result, gen_carbon_costs])
        fuel_cost_result = pd.concat([fuel_cost_result, gen_fuel_cost])
        variable_cost_result = pd.concat([variable_cost_result, gen_variable_costs])

    network.generators_t.marginal_cost = marginal_costs_result.round(2)
    network.generators_t.carbon_cost = carbon_cost_result.round(2)
    network.generators_t.fuel_cost = fuel_cost_result.round(2)
    network.generators_t.variable_cost = variable_cost_result.round(2)

    return (
        marginal_costs_result,
        carbon_cost_result,
        fuel_cost_result,
        variable_cost_result,
    )


def apply_OBPS(
    year: int,
    co2_intensity: float,
    carbon_tax: float,
    fuel_type: str,
    extendable: bool,
) -> float:
    """
    Applies the output-based pricing system to adjust carbon tax

    Reference: https://laws-lois.justice.gc.ca/eng/regulations/SOR-2019-266/page-11.html#h-1185036

    Parameters
    ----------
    year : int
        Year for OBPS calculation
    co2_intensity : float
        CO2 emissions intensity (tonnes/MWh)
    carbon_tax : float
        Carbon tax rate ($/tonne)
    fuel_type : str
        Fuel type: "solid", "liquid", or "gas"
    extendable : bool
        Whether the generator is extendable

    Returns
    -------
    float
        Adjusted carbon tax cost ($/MWh)
    """
    obps_standard = {
        "solid": {"2021": 0.622, "2025": 0.51, "2030": 0.37},
        "liquid": 0.55,
        "gas": {"2021": 0.37, "2025": 0.206, "2030": 0},
    }
    solid_obps_pds = list({int(k) for k in obps_standard["solid"].keys()})
    new_gas_obps_pds = list({int(k) for k in obps_standard["gas"].keys()})

    # assume OBPS doesn't apply after 2035
    if fuel_type in obps_standard.keys() and not (int(year) >= 2035):
        # apply OBPS
        # print(f"Applying OBPS in {year}")
        match fuel_type:
            case "solid":
                if str(year) not in obps_standard["solid"].keys():
                    closest_year = min(solid_obps_pds, key=lambda x: abs(x - year))
                else:
                    closest_year = int(year)

                regulated_co2 = (
                    co2_intensity - obps_standard["solid"][str(closest_year)]
                )
            case "liquid":
                regulated_co2 = co2_intensity - obps_standard["liquid"]
            case "gas":
                if extendable:
                    if str(year) not in obps_standard["gas"].keys():
                        closest_year = min(
                            new_gas_obps_pds, key=lambda x: abs(x - year)
                        )
                    else:
                        closest_year = int(year)

                    regulated_co2 = (
                        co2_intensity - obps_standard["gas"][str(closest_year)]
                    )
                else:
                    regulated_co2 = co2_intensity - obps_standard["gas"]["2021"]
    else:
        regulated_co2 = co2_intensity

    # Ensure only positive values
    regulated_co2 = max(regulated_co2, 0)
    return round(regulated_co2 * carbon_tax, 2)


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
    
    comp_config: dict[str, Any] = config["components"]

    # Calculate marginal costs and save cost components
    # This step is here because the costs vary over different investment periods
    marginal_costs, carbon_cost, fuel_cost, variable_cost = create_marginal_costs(
        network,
        comp_config,
    )
    print("Marginal Cost")
    print(marginal_costs)
    print(f"Carbon Cost: {carbon_cost}")
    print(f"Fuel Cost: {fuel_cost}")
    print(f"Variable Cost: {variable_cost}")
    
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
