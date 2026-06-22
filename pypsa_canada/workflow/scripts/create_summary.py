"""
Create summary across scenarios.

Snakemake script: reads planning and dispatch summary CSVs,
computes cross-scenario comparison metrics and saves them.
"""

import logging
import os
import re
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
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/create_summary.log"
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

config = snakemake.config if snakemake is not None else {}
result_type = snakemake.params.result_type if snakemake is not None else None
planning_csv = (
    os.path.join(
        str(snakemake.input.planning_dir), f"{result_type}_summary_planning.csv"
    )
    if snakemake is not None
    else None
)
dispatch_csv = (
    os.path.join(
        str(snakemake.input.dispatch_dir), f"{result_type}_summary_dispatch.csv"
    )
    if snakemake is not None
    else None
)
# output_dir = str(snakemake.output.summary_output)
summary_filepath = (
    str(snakemake.output.summary_output) if snakemake is not None else None
)

reference_scenario = config.get("postprocess", {}).get("reference_scenario", 0)


# ────────────────────────────────────────────
# Comparison helper functions
# ────────────────────────────────────────────


def build_compare_table(results):
    """Pivot results into a scenario comparison matrix."""
    return results.pivot(
        index=["Parameter", "Variable", "Region", "Time"],
        columns="Scenario",
        values="Value",
    ).fillna(0)


def pre_process_results(
    compare_table, scenarios, parameters, variables, time_filter, grouping, name
):
    """Filter and group the comparison table for metric computation."""
    df = compare_table.copy().reset_index()
    df = df[df.Parameter.isin(parameters)]
    if len(parameters) > 1:
        df["Parameter"] = name
    if len(variables) > 0:
        df = df[df.Variable.isin(variables)]
    if len(time_filter) > 0:
        df = df[df.Time.isin(time_filter)]
    if len(grouping) > 0:
        df = df.groupby(grouping).sum().reset_index()
        df.index = df[grouping[0]].astype(str)
        if len(grouping) > 1:
            for g in grouping[1:]:
                df.index = df.index + "|" + df[g].astype(str)
    else:
        df = df.groupby("Parameter").sum().reset_index()
    df = df[scenarios]
    return df


def calc_solve_time_metric(compare_table, scenarios, reference_scenario, metrics):
    """Normalized solve time difference vs reference."""
    df = pre_process_results(
        compare_table, scenarios, ["Solve_Time"], [], [], [], "Normalized_Solve_Time"
    )
    if df.empty:
        logging.info("No results for run time")
        return metrics
    df = (
        df.subtract(df[reference_scenario], axis=0).divide(
            df[reference_scenario], axis=0
        )
    ).sum()
    df.name = "Run_Time_Metric"
    return pd.merge(metrics, df, how="left", left_index=True, right_index=True)


def calc_load_shedding_metrics(compare_table, scenarios, metrics):
    """Load shedding / peak load ratio."""
    load_shedding = pre_process_results(
        compare_table,
        scenarios,
        ["Annual_Generation"],
        ["load_shedding"],
        [],
        ["Region", "Time"],
        "load_shedding",
    )
    if load_shedding.empty:
        logging.info("No Load Shedding in Any Scenarios")
        return metrics
    peak_load = pre_process_results(
        compare_table, scenarios, ["Peak_Load"], [], [], ["Region", "Time"], "Peak_Load"
    )
    peak_load = (load_shedding / peak_load).dropna().sum()
    peak_load.name = "Peak_Load_Shedding_Metric"
    return pd.merge(metrics, peak_load, how="left", left_index=True, right_index=True)


def calc_emission_metrics(compare_table, scenarios, metrics):
    """Average emission intensity."""
    emissions = pre_process_results(
        compare_table, scenarios, ["Emissions"], [], [], ["Region", "Time"], "Emissions"
    )
    intensity = pre_process_results(
        compare_table,
        scenarios,
        ["Annual_Generation"],
        [],
        [],
        ["Region", "Time"],
        "Generation",
    )
    intensity = (emissions / intensity).fillna(0).mean()
    intensity.name = "Emission_Intensity_Metric"
    return pd.merge(metrics, intensity, how="left", left_index=True, right_index=True)


def calc_capacity_metrics(
    compare_table, results, scenarios, reference_scenario, metrics, unit_type
):
    """Capacity difference between scenarios in 2050."""
    match unit_type:
        case "Transmission":
            parameter = ["Cumulative_New_Transmission_Capacity"]
            variables = []
        case "Generator":
            parameter = ["Cumulative_New_Capacity"]
            variables = list(
                results[results.Variable != "default_liion_battery"].Variable.unique()
            )
        case "StorageUnit":
            parameter = ["Storage_Capacity"]
            variables = ["default_liion_battery"]
        case _:
            logging.warning(f"Invalid unit_type: {unit_type}")
            return metrics

    capacity_2050 = pre_process_results(
        compare_table,
        scenarios,
        parameter,
        variables,
        ["2050"],
        ["Variable", "Region"],
        "Capacity_2050",
    )
    if capacity_2050.empty:
        logging.info(f"No New {unit_type} Capacity")
        return metrics

    diff = (
        capacity_2050.subtract(capacity_2050[reference_scenario], axis=0).dropna().abs()
    )
    max_diff = diff.max()
    max_diff.name = f"Max_Capacity_Difference_{unit_type}"
    avg_diff = diff.mean()
    avg_diff.name = f"Average_Capacity_Difference_{unit_type}"
    metrics = pd.merge(metrics, max_diff, how="left", left_index=True, right_index=True)
    metrics = pd.merge(metrics, avg_diff, how="left", left_index=True, right_index=True)
    return metrics


def calc_cost_metrics(compare_table, results, scenarios, reference_scenario, metrics):
    """Total discounted cost (capex + opex) difference vs reference."""
    capex = pre_process_results(
        compare_table,
        scenarios,
        ["Weighted_Total_Capex"],
        [],
        [],
        ["Time"],
        "Weighted_Total_Capex",
    )
    opex = pre_process_results(
        compare_table,
        scenarios,
        ["Generator_Opex"],
        list(results[results.Variable != "load_shedding"].Variable.unique()),
        [],
        ["Time"],
        "Weighted_Generator_Opex",
    )
    weightings = pre_process_results(
        compare_table,
        scenarios,
        ["Investment_Period_Weighting"],
        [],
        [],
        ["Time"],
        "Weightings",
    )
    opex = opex.multiply(weightings)
    df = capex.add(opex, fill_value=0).sum(axis=0)
    df = df.subtract(df[reference_scenario]).divide(df[reference_scenario])
    df.name = "Cost_Metric"
    return pd.merge(metrics, df, how="left", left_index=True, right_index=True)


def calc_cost_metrics_planning(
    compare_table_planning, planning_results, scenarios, reference_scenario, metrics
):
    """Planning-specific cost metrics (capex + opex separated)."""

    def _pre(*a, **k):
        return pre_process_results(compare_table_planning, scenarios, *a, **k)

    capex = _pre(["Weighted_Total_Capex"], [], [], ["Time"], "Weighted_Total_Capex")
    opex = _pre(
        ["Generator_Opex"],
        list(
            planning_results[
                planning_results.Variable != "load_shedding"
            ].Variable.unique()
        ),
        [],
        ["Time"],
        "Weighted_Generator_Opex",
    )
    weightings = _pre(["Investment_Period_Weighting"], [], [], ["Time"], "Weightings")
    opex = opex.multiply(weightings)
    df = capex.add(opex, fill_value=0).sum(axis=0)

    # Opex only
    opex_total = opex.sum(axis=0)
    opex_diff = opex_total.subtract(opex_total[reference_scenario]).divide(
        opex_total[reference_scenario]
    )
    opex_diff.name = "Opex_Planning_Metric"

    # Capex only
    capex_total = capex.sum(axis=0)
    capex_diff = capex_total.subtract(capex_total[reference_scenario]).divide(
        capex_total[reference_scenario]
    )
    capex_diff.name = "Capex_Planning_Metric"

    # Total
    total_diff = df.subtract(df[reference_scenario]).divide(df[reference_scenario])
    total_diff.name = "Cost_Planning_Metric"

    metrics = pd.merge(
        metrics, total_diff, how="left", left_index=True, right_index=True
    )
    metrics = pd.merge(
        metrics, opex_diff, how="left", left_index=True, right_index=True
    )
    metrics = pd.merge(
        metrics, capex_diff, how="left", left_index=True, right_index=True
    )
    return metrics


def calc_crb_metrics(results, scenarios, path, metrics):
    """Parse solver log files for model columns/rows/binaries."""
    for scenario in scenarios:
        scenario_path = os.path.join(path, scenario)
        if not os.path.exists(scenario_path):
            continue
        for root, dirs, files in os.walk(scenario_path):
            for file in files:
                if file.endswith(".log"):
                    try:
                        with open(os.path.join(root, file)) as f:
                            content = f.read()
                        cols = re.findall(r"Columns\s*:\s*(\d+)", content)
                        rows = re.findall(r"Rows\s*:\s*(\d+)", content)
                        binaries = re.findall(r"Binaries\s*:\s*(\d+)", content)
                        if cols:
                            metrics.loc[scenario, "Model_Columns"] = int(cols[-1])
                        if rows:
                            metrics.loc[scenario, "Model_Rows"] = int(rows[-1])
                        if binaries:
                            metrics.loc[scenario, "Model_Binaries"] = int(binaries[-1])
                    except Exception:
                        continue
    return metrics


def run_all_metrics(
    results,
    planning_results,
    compare_table,
    compare_table_planning,
    scenarios,
    reference_scenario,
    path,
):
    """Run all comparison metrics."""
    metrics = pd.DataFrame(index=scenarios)

    metrics = calc_solve_time_metric(
        compare_table, scenarios, reference_scenario, metrics
    )
    metrics = calc_crb_metrics(results, scenarios, path, metrics)
    metrics = calc_load_shedding_metrics(compare_table, scenarios, metrics)
    metrics = calc_emission_metrics(compare_table, scenarios, metrics)

    for unit_type in ["Generator", "Transmission", "StorageUnit"]:
        metrics = calc_capacity_metrics(
            compare_table, results, scenarios, reference_scenario, metrics, unit_type
        )

    metrics = calc_cost_metrics(
        compare_table, results, scenarios, reference_scenario, metrics
    )
    metrics = calc_cost_metrics_planning(
        compare_table_planning, planning_results, scenarios, reference_scenario, metrics
    )

    return metrics


# ────────────────────────────────────────────
# Main execution
# ────────────────────────────────────────────


def main():
    if snakemake is None:
        raise RuntimeError("create_summary.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    logging.info("===== RESULT COMPARISON =====")
    logging.info("Loading summary inputs")

    # Load results
    results = (
        pd.read_csv(dispatch_csv) if os.path.exists(dispatch_csv) else pd.DataFrame()
    )
    planning_results = (
        pd.read_csv(planning_csv) if os.path.exists(planning_csv) else pd.DataFrame()
    )

    if results.empty and planning_results.empty:
        logging.warning("No results found for comparison")
        # os.makedirs(output_dir, exist_ok=True)
        finish_benchmark_tracker(
            result_benchmark_csv_path(summary_filepath),
            "create_summary",
            benchmark_timer,
            benchmark_memory,
        )
        return

    # Aggregate
    if not results.empty:
        logging.info("Aggregating dispatch results")
        results = (
            results.groupby(["Scenario", "Parameter", "Variable", "Region", "Time"])
            .sum()
            .reset_index()
        )
    if not planning_results.empty:
        logging.info("Aggregating planning results")
        planning_results = (
            planning_results.groupby(
                ["Scenario", "Parameter", "Variable", "Region", "Time"]
            )
            .sum()
            .reset_index()
        )

    # Create output directory
    # os.makedirs(output_dir, exist_ok=True)

    # Determine reference scenario
    logging.info("Selecting reference scenario")
    ref = reference_scenario
    if ref == 0 and not results.empty:
        rep_days = results[results.Parameter == "Representative_Days"]
        if not rep_days.empty:
            ref = results.loc[rep_days.Value.idxmax()].Scenario
        else:
            ref = results.Scenario.iloc[0]
    elif ref == 0 and not planning_results.empty:
        ref = planning_results.Scenario.iloc[0]

    # Build comparison matrices
    logging.info("Combining planning and dispatch results")
    result_frames = [frame for frame in [results, planning_results] if not frame.empty]
    all_results = (
        pd.concat(result_frames, ignore_index=True) if result_frames else pd.DataFrame()
    )
    # scenarios = all_results.Scenario.unique()

    # compare_table = (
    #     build_compare_table(all_results) if not all_results.empty else pd.DataFrame()
    # )
    # compare_table_planning = (
    #     build_compare_table(planning_results)
    #     if not planning_results.empty
    #     else pd.DataFrame()
    # )

    # Save intermediate files
    logging.info("Writing summary CSV")
    all_results = all_results[
        [
            "Model",
            "Scenario",
            "Region",
            "Time",
            "Parameter",
            "Variable",
            "Unit",
            "Value",
        ]
    ]

    all_results.to_csv(summary_filepath, index=False)
    logging.info("Summary CSV written")
    # if not compare_table.empty:
    #     compare_table.to_csv(os.path.join(output_dir, "comparison_matrix.csv"))
    # if not compare_table_planning.empty:
    #     compare_table_planning.to_csv(
    #         os.path.join(output_dir, "comparison_matrix_planning.csv")
    #     )

    # # Run metrics
    # if not compare_table.empty:
    #     path = os.path.dirname(os.path.dirname(planning_csv))
    #     metrics = run_all_metrics(
    #         all_results,
    #         planning_results,
    #         compare_table,
    #         compare_table_planning,
    #         scenarios,
    #         ref,
    #         path,
    #     )
    #     metrics.to_csv(os.path.join(output_dir, "metrics.csv"))

    finish_benchmark_tracker(
        result_benchmark_csv_path(summary_filepath),
        "create_summary",
        benchmark_timer,
        benchmark_memory,
    )
    logging.info("Create summary complete")
    #     logging.info(f"Metrics:\n{metrics}")

    # logging.info("Result comparison complete")


if __name__ == "__main__":
    main()
elif snakemake is not None:
    main()
