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
    # network = create_p_min_pu(network)
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
