# scripts/add_components.py
import logging
import os
import sys
import traceback
from typing import Any

import numpy as np
import pandas as pd
from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from helpers import setup_script_logging
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


def preprocess_carriers(network: Network, comp_config: dict[str, Any]) -> Network:
    """Load and apply carrier generic data to network."""
    print("-----LOADING CARRIER DATA-----")
    components_dir: str = comp_config["components_dir"]

    carrier_data = pd.read_csv(
        os.path.join(components_dir, "carrier_generic_data.csv"), index_col=0
    )
    network.carriers = carrier_data
    return network


def create_generic_components(
    network: Network, comp_config: dict[str, Any], component: str = "Generator"
) -> pd.DataFrame:
    """
    Read generic component data and apply to network components.

    Parameters
    ----------
    network : Network
        PyPSA network object
    comp_config : dict[str, Any]
        Components configuration dictionary
    component : str
        Component type: "Generator" or "StorageUnit"

    Returns
    -------
    pd.DataFrame
        Updated component data with generic parameters applied
    """
    components_dir: str = comp_config["components_dir"]
    if component == "Generator":
        component_data = pd.read_csv(
            f"{components_dir}/generator_generic_data.csv", index_col=0
        )
        data = network.generators.copy()
    elif component == "StorageUnit":
        component_data = pd.read_csv(
            f"{components_dir}/storage_unit_generic_data.csv", index_col=0
        )
        data = network.storage_units.copy()

    for unit in data.index:
        unit_data = data.loc[unit]
        unit_data = component_data.loc[unit_data.model]

        if "OPT" not in unit:
            unit_data = unit_data.drop(["lifetime"])

        for column, value in unit_data.items():
            data.loc[unit, column] = value

    return data


def create_p_min_max(network: Network, comp_config: dict[str, Any]) -> Network:
    """Create p_max_pu and p_min_pu time series for extendable generators."""
    network = create_p_max_pu(network, comp_config)
    #network = create_p_min_pu(network)
    return network


def create_p_max_pu(network: Network, comp_config: dict[str, Any]) -> Network:
    """
    Create p_max_pu time series for extendable generators across multiple years.

    Duplicates existing p_max_pu columns for each future year after the generator's build year.
    """
    years: list[int] = config["year_settings"]["investment_period"]
    generators = network.generators[network.generators.p_nom_extendable]
    generator_t_p_max_pu_ref_df = network.generators_t.p_max_pu.copy()
    p_max_pu = generator_t_p_max_pu_ref_df.copy()

    for generator, data in generators.iterrows():
        years_filtered = [i for i in years if i > data["build_year"]]
        if generator in p_max_pu.columns:
            for year in years_filtered:
                p_max_pu = p_max_pu.join(p_max_pu[generator], rsuffix=f"-{year}")

    network.generators_t.p_max_pu = p_max_pu

    return network


def create_p_min_pu(network: Network) -> Network:
    """
    Creates the p_min_pu file for hydro generators with an existing entry in p_max_pu, and sets equal to p_max_pu since these generators are by hypothesis not flexible,
    i.e. output for these generators cannot be increased or decreased by hypothesis
    """
    generators = network.generators[network.generators.carrier == "hydro"]
    p_min_pu = network.generators_t.p_max_pu[generators.index]
    network.generators_t.p_min_pu[generators.index] = p_min_pu

    return network


def create_extendable_components(
    network: Network,
    comp_config: dict[str, Any],
    component: str = "Generator",
) -> Network:
    """
    Create extendable components with cost data for multiple investment years.

    Parameters
    ----------
    network : Network
        PyPSA network object
    comp_config : dict[str, Any]
        Components configuration dictionary
    component : str
        Component type: "Generator", "StorageUnit", "Line", or "Link"

    Returns
    -------
    Network
        Network with extendable components added for each year
    """
    costs_dir: str = comp_config["costs_dir"]
    # Use default technology costs if not specified
    technology_costs: str = comp_config.get("technology_costs", "Default_costs")
    years: list[int] = config["year_settings"]["investment_period"]
    # Get the data for the specified component type
    if component == "Generator":
        data = network.generators.copy()
    elif component == "StorageUnit":
        data = network.storage_units.copy()
    elif component == "Line":
        data = network.lines.copy()
    elif component == "Link":
        data = network.links.copy()

    # Filter components that are extendable and optional (i.e. have "OPT" in their name)
    if component == "Line":
        components = data[data.s_nom_extendable]
    else:
        components = data[data.p_nom_extendable]
    components = components[components.index.str.contains("OPT")].index

    # Read capital costs from the technology costs directory
    capital_costs = pd.read_csv(
        os.path.join(costs_dir, technology_costs, "capital_costs.csv"),
        index_col=0,
    )
    # Read fixed costs from the technology costs directory
    fixed_costs = pd.read_csv(
        os.path.join(costs_dir, technology_costs, "fixed_o_m.csv"),
        index_col=0,
    )
    # and add them to the capital costs to get total costs
    total_costs = capital_costs.add(fixed_costs)

    tech_years = np.asarray(total_costs.columns.astype(int))

    for comp in components:
        # Get the technology year closest to the build year of the component
        build_year = int(data.at[comp, "build_year"])
        tech_year = str(tech_years[(np.abs(tech_years - build_year)).argmin()])

        # If the component is a generator or storage unit, set the capital cost, cap_cost, and fixed_om
        if component == "Generator" or component == "StorageUnit":
            data.at[comp, "capital_cost"] = total_costs.at[
                data.loc[comp]["model"], tech_year
            ].round(2)
            data.at[comp, "cap_cost"] = capital_costs.at[
                data.loc[comp]["model"], tech_year
            ].round(2)
            data.at[comp, "fixed_om"] = fixed_costs.at[
                data.loc[comp]["model"], tech_year
            ].round(2)

        # For each year after the build year, create a new component with the same data
        years = [i for i in years if i > data.loc[comp]["build_year"]]
        for year in years:
            # Get the technology year closest to the current year
            tech_year = str(tech_years[(np.abs(tech_years - year)).argmin()])

            # Create a new component with the same data but with the build year set to the current year
            name = f"{comp}-{year}"
            data.loc[name] = data.loc[comp].copy()
            data.at[name, "build_year"] = year

            # If the component is a generator or storage unit, set the capital cost, cap_cost, and fixed_om
            if component == "Generator" or component == "StorageUnit":
                data.at[name, "capital_cost"] = total_costs.loc[
                    data.loc[comp]["model"]
                ][tech_year].round(2)
                data.at[name, "cap_cost"] = capital_costs.loc[data.loc[comp]["model"]][
                    tech_year
                ].round(2)
                data.at[name, "fixed_om"] = fixed_costs.loc[data.loc[comp]["model"]][
                    tech_year
                ].round(2)

    # Save the modified data back to the network
    if component == "Generator":
        network.generators = data
        data = network.generators
    elif component == "StorageUnit":
        network.storage_units = data
        data = network.storage_units
    elif component == "Line":
        network.lines = data
        data = network.lines
    elif component == "Link":
        network.links = data
        data = network.links
    return network


def apply_wind_loss_factors(network: Network) -> Network:
    """
    Apply wind loss factors to capacity factors.

    Multiplies wind p_max_pu by efficiency coefficient to account for losses.
    """
    # Select wind generators and multiply their capacity factors in p_max_pu by the loss coefficient
    generators = network.generators[network.generators.carrier == "wind"]
    p_max_pu = (
        network.generators_t.p_max_pu[generators.index]
        * generators.loc[generators.index, "efficiency"]
    )

    # Replace wind generator capacity factors with new values
    network.generators_t.p_max_pu[generators.index] = p_max_pu

    return network


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


def preprocess_components(
    network: Network,
    comp_config: dict[str, Any],
) -> Network:
    """
    Preprocess all network components with generic data and costs.

    Applies generic component data, creates extendable components,
    calculates marginal costs, and processes all component types.

    Parameters
    ----------
    network : Network
        PyPSA network object
    comp_config : dict[str, Any]
        Components configuration dictionary

    Returns
    -------
    Network
        Network with all components preprocessed
    """
    # Read generic carrier data
    network = preprocess_carriers(network, comp_config)

    print("-----CREATING GENERATOR DATA-----")
    # Modify generator dataframe to add generic data
    network.generators = create_generic_components(network, comp_config, "Generator")

    # Modify p_max and p_min files to add extendable generators
    network = create_p_min_max(network, comp_config)

    # Modify generator dataframe to add extendable generators
    network = create_extendable_components(network, comp_config, "Generator")

    # Apply wind losses in p_max file
    network = apply_wind_loss_factors(network)

    # Calculate marginal costs and save cost components
    marginal_costs, carbon_cost, fuel_cost, variable_cost = create_marginal_costs(
        network,
        comp_config,
    )
    print("Marginal Cost")
    print(marginal_costs)
    print(f"Carbon Cost: {carbon_cost}")
    print(f"Fuel Cost: {fuel_cost}")
    print(f"Variable Cost: {variable_cost}")
    network.generators_t.marginal_cost = marginal_costs.copy()
    network.generators_t.carbon_cost = carbon_cost.copy()
    network.generators_t.fuel_cost = fuel_cost.copy()
    network.generators_t.variable_cost = variable_cost.copy()
    print("-----CREATING STORAGE UNITS DATA-----")
    if not network.storage_units.empty:
        # Modify storage units dataframe to add generic data
        network.storage_units = create_generic_components(
            network, comp_config, "StorageUnit"
        )

        # Modify storage units dataframe to add extendable storage units
        network = create_extendable_components(network, comp_config, "StorageUnit")

    print("-----CREATING LINES DATA-----")
    if not network.lines.empty:
        network = create_extendable_components(network, comp_config, "Line")

    print("-----CREATING LINKS DATA-----")
    if not network.links.empty:
        network = create_extendable_components(network, comp_config, "Link")

    return network


def main() -> None:
    if snakemake is None:
        raise RuntimeError("add_components.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    network: Network = Network(snakemake.input.input_data)
    comp_config: dict[str, Any] = config["components"]

    network = preprocess_components(network, comp_config)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if config["run"]["export_csv"]:
        network.export_to_csv_folder(
            f"{snakemake.output.planning_unsolved_network[:-3]}_csv"
        )

    finish_benchmark_tracker(
        result_benchmark_csv_path(snakemake.output.planning_unsolved_network),
        "add_components",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
