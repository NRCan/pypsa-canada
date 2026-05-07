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

# ── Snakemake wiring ──
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/export_idea.log"
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)

config = snakemake.config
result_type = snakemake.params.result_type
planning_csv = os.path.join(
    str(snakemake.input.planning_dir), f"{result_type}_summary_planning.csv"
)
dispatch_csv = os.path.join(
    str(snakemake.input.dispatch_dir), f"{result_type}_summary_dispatch.csv"
)
output_dir = str(snakemake.output.idea_output)

# ────────────────────────────────────────────
# IDEA Variable Mapping Dictionaries
# ────────────────────────────────────────────

# Maps (Parameter, Variable) combinations to IDEA-style variable names.
# Based on the pypsa_cad IDEA export conventions.

# Generator technology mapping: internal model name → IDEA carrier name
CARRIER_MAP = {
    "default_biomass": "Biomass",
    "default_biogas": "Biogas",
    "coal_IGCC": "Coal|IGCC",
    "coal_pulverized": "Coal|Pulverized",
    "default_diesel": "Diesel",
    "gas_CC": "Gas|CC",
    "gas_CT": "Gas|CT",
    "hydro_ror": "Hydro|ROR",
    "default_nuclear": "Nuclear|Conventional",
    "default_SMR": "Nuclear|SMR",
    "default_oil": "Oil",
    "default_solar_PV": "Solar|PV",
    "wind_2021": "Wind|Onshore",
    "wind_new": "Wind|Onshore|New",
    "default_liion_battery": "Storage|Battery|Lithium",
    "hydro_storage": "Hydro|Storage",
    "load_shedding": "Load Shedding",
    "default_DAC": "Direct Air Capture",
    "load_non_commitable": "Flexible Load|Non-Commitable",
    "load_commitable": "Flexible Load|Commitable",
    "import": "Import",
}

# Parameter → IDEA parameter prefix mapping
PARAM_MAP = {
    # Capacity
    "Capacity": "Total generation capacity",
    "New_Capacity": "New generation capacity",
    "Cumulative_New_Capacity": "Cumulative new generation capacity",
    "Retired_Capacity": "Retired generation capacity",
    "Storage_Capacity": "Storage capacity",
    # Transmission
    "Transmission_Capacity": "Total transmission capacity",
    "New_Transmission_Capacity": "New transmission capacity",
    "Retired_Transmission_Capacity": "Retired transmission capacity",
    # Generation / Dispatch
    "Annual_Generation": "Dispatch",
    "Annual_Generation_Mix": "Generation mix",
    "Storage_Unit_Out": "Dispatch",
    "Storage_Unit_In": "Storage charge",
    # Costs - Planning
    "Capital_Cost": "Capital costs",
    "Fixed_OM_Cost": "FO&M costs",
    "Other_Capacity_Costs": "Other capital costs",
    "Total_Capex": "Total capital expenditure",
    "Weighted_Total_Capex": "Weighted total capital expenditure",
    "Weighted_Capital_Cost": "Weighted capital costs",
    "Weighted_Fixed_OM_Cost": "Weighted FO&M costs",
    "Weighted_Other_Capacity_Costs": "Weighted other capital costs",
    "Capital_Cost_Transmission": "Capital costs|Transmission",
    "Fixed_OM_Cost_Transmission": "FO&M costs|Transmission",
    "Other_Capacity_Costs_Transmission": "Other capital costs|Transmission",
    "Total_Capex_Transmission": "Total capital expenditure|Transmission",
    "Weighted_Capital_Cost_Transmission": "Weighted capital costs|Transmission",
    "Weighted_Fixed_OM_Cost_Transmission": "Weighted FO&M costs|Transmission",
    "Weighted_Other_Capacity_Costs_Transmission": "Weighted other capital costs|Transmission",
    "Weighted_Total_Capex_Transmission": "Weighted total capital expenditure|Transmission",
    # Costs - Dispatch
    "Generator_Opex": "Operational costs",
    "Carbon_Cost": "Carbon price",
    "Fuel_Cost": "Fuel costs",
    "Variable_Cost": "VO&M costs",
    "Storage_Opex": "Storage operational costs",
    "Transmission_Cost": "Transmission costs",
    # Emissions
    "Emissions": "Emissions",
    "Removed_Emissions": "Removed emissions",
    "Average_Emission_Intensity": "Average emission intensity",
    # Performance
    "Average_Resource_Availability": "Average resource availability",
    "Average_Capacity_Factor": "Average capacity factor",
    "Average_Utilization": "Average utilization",
    "Curtailed_Energy": "Curtailed energy",
    "Line_Utilization": "Transmission utilization",
    # Load
    "Annual_Load": "Annual load",
    "Peak_Load": "Peak load",
    # Transmission flow
    "Net_Line_Flow": "Net transmission flow",
    "Line_Flow": "Transmission flow",
    # Storage
    "Average_State_of_Charge": "Average state of charge",
    "Storage_Unit_Spill": "Storage spill",
    "Storage_Unit_Inflows": "Storage inflows",
    # Misc
    "Investment_Period_Weighting": "Investment period weighting",
    "Representative_Days": "Representative days",
    "Solve_Time": "Solve time",
    "Qualifying_Capacity": "Qualifying capacity",
    "Reserve_Load": "Reserve load",
    "DAC_revenue": "DAC revenue",
}

# IDEA output column order
IDEA_COLUMNS = ["Model", "Scenario", "Region", "Time", "Variable", "Unit", "Value"]


# ────────────────────────────────────────────
# Conversion functions
# ────────────────────────────────────────────


def map_to_idea_variable(parameter, variable):
    """
    Convert (Parameter, Variable) pair to IDEA-style variable name.

    For generation/capacity parameters: "{IDEA_param}|Electricity|{IDEA_carrier}"
    For transmission parameters: "{IDEA_param}|{destination}"
    For load/misc parameters: "{IDEA_param}"
    """
    idea_param = PARAM_MAP.get(parameter, parameter)
    idea_carrier = CARRIER_MAP.get(variable, variable)

    # Transmission-related parameters keep the variable as-is (region pair)
    if "Transmission" in parameter or "Line" in parameter:
        if variable and variable != "All":
            return f"{idea_param}|{variable}"
        return idea_param

    # Load parameters
    if parameter in ("Annual_Load", "Peak_Load"):
        return idea_param

    # Misc parameters without technology dimension
    if parameter in (
        "Investment_Period_Weighting",
        "Representative_Days",
        "Solve_Time",
    ):
        return idea_param

    # Generation / capacity / cost parameters: include electricity + carrier
    if idea_carrier and idea_carrier != "All":
        return f"{idea_param}|Electricity|{idea_carrier}"

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

    # Map Parameter + Variable → IDEA Variable
    result["Variable"] = result.apply(
        lambda row: map_to_idea_variable(row["Parameter"], row["Variable"]), axis=1
    )

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


# ────────────────────────────────────────────
# Main execution
# ────────────────────────────────────────────


def main():
    logging.info("===== IDEA FORMAT EXPORT =====")

    # Load postprocess summary CSVs
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
        os.makedirs(output_dir, exist_ok=True)
        return

    # Create output directory
    os.makedirs(output_dir, exist_ok=True)

    dfs = []

    # Convert planning results
    if not planning_results.empty:
        idea_planning = convert_to_idea_format(planning_results)
        export_idea_csv(idea_planning, output_dir, "idea_planning.csv")
        dfs.append(idea_planning)

    # Convert dispatch results
    if not dispatch_results.empty:
        idea_dispatch = convert_to_idea_format(dispatch_results)
        export_idea_csv(idea_dispatch, output_dir, "idea_dispatch.csv")
        dfs.append(idea_dispatch)

    # Merged output
    if dfs:
        merged = pd.concat(dfs, ignore_index=True)
        export_idea_csv(merged, output_dir, "idea_merged.csv")
        logging.info(f"Total IDEA export rows: {len(merged)}")

    logging.info("IDEA export complete")


if __name__ == "__main__":
    main()
else:
    main()
