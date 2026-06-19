"""
Export postprocess results to IDEA format.

Snakemake script: reads planning and dispatch summary CSVs,
converts them to the IDEA standardized template format
(Model | Scenario | Region | Time | Variable | Unit | Value)
and saves individual + merged CSVs.
"""

import logging
import os
import sys

import pandas as pd
from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)

# ── Snakemake wiring ──
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0]) if snakemake is not None and snakemake.log else "logs/export_idea.log"
)
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)

config = snakemake.config if snakemake is not None else None
result_type = snakemake.params.result_type if snakemake is not None else None
planning_csv = (
    os.path.join(str(snakemake.input.planning_dir), f"{result_type}_summary_planning.csv")
    if snakemake is not None
    else None
)
dispatch_csv = (
    os.path.join(str(snakemake.input.dispatch_dir), f"{result_type}_summary_dispatch.csv")
    if snakemake is not None
    else None
)
output_dir = str(snakemake.output.idea_output) if snakemake is not None else None

# ────────────────────────────────────────────
# IDEA Variable Mapping Dictionaries
# ────────────────────────────────────────────

# Maps (Parameter, Variable) combinations to IDEA-style variable names.
# These mirror the cad exporter conventions so the exported labels stay stable.

PARAM_MAPPING = {
    "Emissions": "Emissions",
    "Removed_Emissions": "Emissions",
    "Capacity": "Total generation capacity",
    "New_Capacity": "New generation capacity",
    "New_Forced_Capacity": "New generation capacity",
    "Retired_Capacity": "Retired generation capacity",
    "Transmission_Capacity": "Total transmission capacity",
    "New_Transmission_Capacity": "New transmission capacity",
    "New_Forced_Transmission_Capacity": "New transmission capacity",
    "Retired_Transmission_Capacity": "Retired transmission capacity",
    "Annual_Generation": "Dispatch",
    "Storage_Unit_Out": "Dispatch",
    "Line_Flow": "Transmission flow",
    # Planning Costs
    "Capital_Cost": "Capital costs",
    "Fixed_OM_Cost": "FO&M costs",
    "Other_Capacity_Costs": "Capital costs",
    "Capital_Cost_Transmission": "Capital costs",
    "Fixed_OM_Cost_Transmission": "FO&M costs",
    "Other_Capacity_Costs_Transmission": "Capital costs",
    # Dispatch Costs
    "Carbon_Cost": "Carbon price",
    "Fuel_Cost": "Fuel costs",
    "Variable_Cost": "VO&M costs",
}

VAR_MAPPING = {
    "default_biomass": "Biomass|w/o CCS",
    "default_biogas": "Biogas|w/o CCS",
    "coal_IGCC": "Coal|IGCC|w/o CCS",
    "coal_pulverized": "Coal|Pulverized|w/o CCS",
    "default_diesel": "Diesel|w/o CCS",
    "gas_CC": "Gas|CC|w/o CCS",
    "gas_CT": "Gas|CT|w/o CCS",
    "hydro_ror": "Hydro|ROR",
    "import": "Import",
    "default_nuclear": "Nuclear|Conventional",
    "default_SMR": "Nuclear|SMR",
    "default_oil": "Oil|w/o CCS",
    "default_solar_PV": "Solar|PV|Open Land",
    "wind_2021": "Wind|Onshore",
    "wind_new": "Wind|Onshore",
    "load_non_commitable": "Flexible Load|Non-Commitable",
    "load_commitable": "Flexible Load|Commitable",
    "hydro_storage": "Hydro|Storage",
    "default_liion_battery": "Storage|Battery|Lithium",
    "load_shedding": "Load Shedding",
    "default_DAC": "Direct Air Capture",
}

DISPATCH_VAR_DICT = {
    "Demand": "Dispatch|Electricity|Demand",
    "biomass": "Dispatch|Electricity|Biomass",
    "biogas": "Dispatch|Electricity|Biogas",
    "coal": "Dispatch|Electricity|Coal|Pulverized",
    "diesel": "Dispatch|Electricity|Oil|Diesel",
    "gas": "Dispatch|Electricity|Gas|CC",
    "hydro": "Dispatch|Electricity|Hydro|Run",
    "hydro_storage": "Dispatch|Electricity|Hydro|Monthly",
    "nuclear": "Dispatch|Electricity|Nuclear|SMR",
    "oil": "Dispatch|Electricity|Oil|Fuel Oil",
    "solar": "Dispatch|Electricity|Solar|PV",
    "wind": "Dispatch|Electricity|Wind|New",
    "liion_storage": "Dispatch|Electricity|Storage|Battery|Lithium",
    "transfer_in": "Dispatch|Electricity|Import_temp",
    "transfer_out": "Dispatch|Electricity|Export",
}

EMISSION_VAR_DICT = {
    #    'hydro': 'Emissions|Electricity|Hydro|Run',
    #    'wind': 'Emissions|Electricity|Wind|New',
    #    'solar': 'Emissions|Electricity|Solar|PV',
    #    'nuclear': 'Emissions|Electricity|Nuclear|SMR',
    "gas": "Emissions|Electricity|Gas|CC",
    #    'biomass': 'Emissions|Electricity|Biomass',
    #    'biogas': 'Emissions|Electricity|Biogas',
    "coal": "Emissions|Electricity|Coal|Pulverized",
    "oil": "Emissions|Electricity|Oil|Fuel Oil",
    "diesel": "Emissions|Electricity|Oil|Diesel",
}

REP_DAYS_VAR_DICT = {
    "Demand": "Dispatch|Electricity|Demand",
    "hydro": "Dispatch|Electricity|Hydro|Run",
    "wind": "Dispatch|Electricity|Wind|New",
    "solar": "Dispatch|Electricity|Solar|PV",
    "nuclear": "Dispatch|Electricity|Nuclear|SMR",
    "gas": "Dispatch|Electricity|Gas|CC",
    "biomass": "Dispatch|Electricity|Biomass",
    "biogas": "Dispatch|Electricity|Biogas",
    "coal": "Dispatch|Electricity|Coal|Pulverized",
    "oil": "Dispatch|Electricity|Oil|Fuel Oil",
    "diesel": "Dispatch|Electricity|Oil|Diesel",
    "lithium": "Dispatch|Electricity|Storage|Battery|Lithium",
    "transfer_in": "Dispatch|Electricity|Import_temp",
    "transfer_out": "Dispatch|Electricity|Export",
}

OP_COST_VAR_DICT = {
    "hydro": "Operational|Electricity|Hydro|Run",
    "wind": "Operational|Electricity|Wind|New",
    "solar": "Operational|Electricity|Solar|PV",
    "nuclear": "Operational|Electricity|Nuclear|SMR",
    "gas": "Operational|Electricity|Gas|CC",
    "biomass": "Operational|Electricity|Biomass",
    "biogas": "Operational|Electricity|Biogas",
    "coal": "Operational|Electricity|Coal|Pulverized",
    "oil": "Operational|Electricity|Oil|Fuel Oil",
    "diesel": "Operational|Electricity|Oil|Diesel",
}


def format_var_mapping_dict(metric_name):
    match metric_name:
        case "capex":
            mapping_name = "Capital"
        case "expanded_capacity":
            mapping_name = "New generation capacity"
        case "total_gen_capacity":
            mapping_name = "Total generation capacity"
        case _:
            print(f"Generation metric {metric_name} not supported")

    VAR_MAP_DICT = {
        "biogas": f"{mapping_name}|Electricity|Biogas",
        "biomass": f"{mapping_name}|Electricity|Biomass",
        "coal": f"{mapping_name}|Electricity|Coal|Pulverized",
        "Demand": f"{mapping_name}|Electricity|Demand",
        "diesel": f"{mapping_name}|Electricity|Oil|Diesel",
        "hydro": f"{mapping_name}|Electricity|Hydro|Monthly",
        "hydro_storage": f"{mapping_name}|Electricity|Hydro|Monthly",
        "gas": f"{mapping_name}|Electricity|Gas|CC",
        "liion": f"{mapping_name}|Electricity|Storage|Battery|Lithium",
        "liion_storage": f"{mapping_name}|Electricity|Storage|Battery|Lithium",
        "nuclear": f"{mapping_name}|Electricity|Nuclear|Conventional",
        "oil": f"{mapping_name}|Electricity|Oil|Fuel Oil",
        "SMR": f"{mapping_name}|Electricity|Nuclear|SMR",
        "solar": f"{mapping_name}|Electricity|Solar|PV",
        "transfer_in": f"{mapping_name}|Electricity|Import_temp",
        "transfer_out": f"{mapping_name}|Electricity|Export",
        "wind": f"{mapping_name}|Electricity|Wind|Old",
        "wind_new": f"{mapping_name}|Electricity|Wind|New",
    }

    MODEL_TO_CARRIER_MAP_DICT = {
        "default_biogas": "biogas",
        "default_biomass": "biomass",
        "coal_IGCC": "coal",
        "coal_pulverized": "coal",
        "default_diesel": "diesel",
        "gas_CC": "gas",
        "gas_CT": "gas",
        "hydro_ror": "hydro",
        "import": "import",
        "default_nuclear": "nuclear",
        "default_SMR": "SMR",
        "default_oil": "oil",
        "default_solar_PV": "solar",
        "default_liion_battery": "liion",
        "wind_2021": "wind",
        "wind_new": "wind_new",
    }
    return VAR_MAP_DICT, MODEL_TO_CARRIER_MAP_DICT


# IDEA output column order
IDEA_COLUMNS = ["Model", "Scenario", "Region", "Time", "Variable", "Unit", "Value"]


# ────────────────────────────────────────────
# Conversion functions
# ────────────────────────────────────────────


def map_to_idea_variable(parameter, variable, region):
    """
    Convert (Parameter, Variable) pair to IDEA-style variable name.

    For generation/capacity parameters: "{IDEA_param}|Electricity|{IDEA_carrier}"
    For transmission parameters: "{IDEA_param}|{destination}"
    For load/misc parameters: "{IDEA_param}"
    """
    idea_param = PARAM_MAPPING.get(parameter, parameter)
    idea_variable = VAR_MAPPING.get(variable, variable)

    # Line flow uses the cad-style "to <destination>" naming.
    if parameter == "Line_Flow":
        if region:
            destination = region.split("->")[-1]
            return f"{idea_param}|to {destination}"
        return idea_param

    # All other mapped parameters are exported with an Electricity technology layer.
    if parameter in PARAM_MAPPING:
        if idea_variable and idea_variable != "All":
            return f"{idea_param}|Electricity|{idea_variable}"
        return idea_param

    if idea_variable != variable:
        return idea_variable

    return idea_param


def convert_to_idea_format(df):
    """
    Convert an IAMC-format summary DataFrame to IDEA format.

    Input columns: Model, Scenario, Region, Parameter, Variable, Time, Value, Unit
    Output columns: Model, Scenario, Region, Time, Variable, Unit, Value
    """
    if df.empty:
        return pd.DataFrame(columns=IDEA_COLUMNS)

    result = df.copy()

    # Keep the exact metric set supported by the original pypsa_cad exporter.
    result = result[result["Parameter"].isin(PARAM_MAPPING)]

    if result.empty:
        return pd.DataFrame(columns=IDEA_COLUMNS)

    # Map Parameter + Variable → IDEA Variable
    result["Variable"] = result.apply(
        lambda row: map_to_idea_variable(
            row["Parameter"], row["Variable"], row["Region"]
        ),
        axis=1,
    )

    # Assign the shipping province to the “Region” column for transmission flow
    mask = result["Variable"].str.contains("Transmission flow", na=False)
    result.loc[mask, "Region"] = result.loc[mask, "Region"].str.split("->").str[0]

    # Drop the Parameter column (now encoded in Variable)
    result = result.drop(columns=["Parameter"], errors="ignore")

    # Reorder to IDEA column order
    result = result[IDEA_COLUMNS]

    # Drop rows with zero or null values
    result = result[result["Value"].notna()]
    result = result[result["Value"] != 0]

    return result


def export_idea_csv(df, output_dir, filename):
    """Save a DataFrame to CSV in the output directory."""
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    df.to_csv(filepath, index=False)
    logging.info(f"Saved IDEA export: {filepath} ({len(df)} rows)")
    return df


def export_as_idea(output_folder):
    """Export planning and dispatch summaries to IDEA format."""
    planning_results = pd.DataFrame()
    dispatch_results = pd.DataFrame()

    if os.path.exists(planning_csv):
        planning_results = pd.read_csv(planning_csv)
        logging.info(f"Loaded planning summary: {len(planning_results)} rows")
    else:
        logging.warning(f"Planning summary not found: {planning_csv}")

    if os.path.exists(dispatch_csv):
        dispatch_results = pd.read_csv(dispatch_csv)
        logging.info(f"Loaded dispatch summary: {len(dispatch_results)} rows")
    else:
        logging.warning(f"Dispatch summary not found: {dispatch_csv}")

    if planning_results.empty and dispatch_results.empty:
        logging.warning("No results found for IDEA export")
        os.makedirs(output_folder, exist_ok=True)
        return pd.DataFrame(columns=IDEA_COLUMNS)

    os.makedirs(output_folder, exist_ok=True)

    dfs = []

    if not planning_results.empty:
        idea_planning = convert_to_idea_format(planning_results)
        # export_idea_csv(idea_planning, output_folder, "idea_planning.csv")
        dfs.append(idea_planning)

    if not dispatch_results.empty:
        idea_dispatch = convert_to_idea_format(dispatch_results)
        # export_idea_csv(idea_dispatch, output_folder, "idea_dispatch.csv")
        dfs.append(idea_dispatch)

    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        # TODO change this eventually. For now, Idea profile model needs to match NRCan-PyPSA
        merged["Model"] = "NRCan-PyPsa"
        # TODO removing unnecessary average rows for now to match original export. Can re-add if needed.
        merged = merged[~merged["Variable"].str.contains("average", case=False)]
        # export_idea_csv(merged, output_folder, "idea_outputs.csv")
        logging.info(f"Total IDEA export rows: {len(merged)}")
        return merged

    return pd.DataFrame(columns=IDEA_COLUMNS)


# ────────────────────────────────────────────
# Main execution
# ────────────────────────────────────────────


def main():
    if snakemake is None:
        raise RuntimeError("export_idea.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    logging.info("===== IDEA FORMAT EXPORT =====")
    root_path = os.path.dirname(output_dir)
    # output_folder = os.path.join(root_path, "idea_output")
    df = export_as_idea(root_path)

    if not df.empty:
        output_filepath = os.path.join(root_path, "idea_outputs.csv")
        df.to_csv(output_filepath, index=False)
        logging.info(f"Saved IDEA export: {output_filepath} ({len(df)} rows)")

    logging.info("IDEA export complete")

    finish_benchmark_tracker(
        result_benchmark_csv_path(output_dir),
        "export_idea",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    main()
elif snakemake is not None:
    main()
