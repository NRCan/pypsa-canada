"""
Post-process a solved planning network.

Snakemake script: reads the solved planning network, computes capacity,
capex, reserve, annual metrics, energy/storage balances and writes summary CSVs.
"""

import logging
import os
import sys
import time

import pandas as pd
import pypsa
from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from postprocess_helpers import (
    calc_annual,
    calc_energy_balance,
    calc_storage_balance,
    create_templates,
    format_annual_data,
    format_network,
    manual_capacity_calc,
    save_prov_energy_balance,
    save_storage_balance,
)

# ── Snakemake wiring ──
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/post_process_planning.log"
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
solved_network_path = (
    str(snakemake.input.solved_planning_network) if snakemake is not None else None
)
output_dir = (
    str(snakemake.output.planning_postprocess) if snakemake is not None else None
)


# ── Configuration ──
result_type = config.get("postprocess", {}).get("result_type", "Provincial")
planning_reserve_cfg = (
    config.get("planning", {})
    .get("constraints", {})
    .get("planning_reserve_margin", None)
)

# Model / scenario naming
run_name = config.get("run", {}).get("name", "default")
model_name = f"PyPSA-Canada_{run_name}"
scenario_name = run_name


# ────────────────────────────────────────────
# Planning-specific calculation functions
# ────────────────────────────────────────────


def calc_capacity(n, comp, years, templates, agg=True):
    """Compute optimal / new / retired capacity per investment period."""
    stats = n.statistics
    result = pd.DataFrame()
    optimal_capacity = pd.DataFrame()
    names = [
        "Capacity",
        "Cumulative_New_Capacity",
        "New_Capacity",
        "Cumulative_Forced_Capacity",
        "New_Forced_Capacity",
        "Retired_Capacity",
    ]

    match comp:
        case "Generator":
            template = templates["generator_template"].copy()
        case "StorageUnit":
            template = templates["storage_unit_template"].copy()
            if not template.empty:
                storage_cap_raw = stats.optimal_capacity(
                    comps="StorageUnit", groupby=False, storage=True
                ).reset_index()
                # Find the name column (varies by PyPSA version: "name", "StorageUnit", etc.)
                name_col = [
                    c
                    for c in storage_cap_raw.columns
                    if c not in ("component",) and storage_cap_raw[c].dtype == object
                ]
                if name_col:
                    storage_cap = (
                        storage_cap_raw.set_index(name_col[0])
                        .drop(columns=["component"], errors="ignore")
                        .fillna(0)
                    )
                else:
                    storage_cap = storage_cap_raw.drop(
                        columns=["component"], errors="ignore"
                    ).fillna(0)
        case "Store":
            template = templates["store_template"].copy()
            if not template.empty:
                store_cap_raw = stats.optimal_capacity(
                    comps="Store", groupby=False, storage=True
                ).reset_index()
                name_col = [
                    c
                    for c in store_cap_raw.columns
                    if c not in ("component",) and store_cap_raw[c].dtype == object
                ]
                if name_col:
                    store_cap = (
                        store_cap_raw.set_index(name_col[0])
                        .drop(columns=["component"], errors="ignore")
                        .fillna(0)
                    )
                else:
                    store_cap = store_cap_raw.drop(
                        columns=["component"], errors="ignore"
                    ).fillna(0)
        case "Transmission":
            template = templates["transmission_template"].copy()
        case "Reverse_Transmission":
            template = templates["rev_trans_template"].copy()

    if comp in ("Transmission", "Reverse_Transmission"):
        if not n.links.empty:
            link_capacity = manual_capacity_calc(n, "Link")
            link_capacity.index.name = "Transmission"
            optimal_capacity = pd.concat([optimal_capacity, link_capacity])
            if comp == "Reverse_Transmission":
                optimal_capacity = (
                    optimal_capacity.multiply(n.links.p_min_pu, axis=0)
                    .multiply(-1)
                    .fillna(0)
                )
        if not n.lines.empty:
            line_capacity = manual_capacity_calc(n, "Line")
            line_capacity.index.name = "Transmission"
            optimal_capacity = pd.concat([optimal_capacity, line_capacity])
        names = [name.replace("Capacity", "Transmission_Capacity") for name in names]
    else:
        optimal_capacity = manual_capacity_calc(n, comp)

    net_capacity = optimal_capacity.diff(axis=1).fillna(0)
    retired_capacity = net_capacity.clip(upper=0)
    new_capacity = net_capacity.clip(lower=0)

    if not template.empty:
        for year in years:
            result = pd.concat(
                [
                    result,
                    format_annual_data(
                        template,
                        optimal_capacity[year],
                        names[0],
                        "MW",
                        year,
                        model_name,
                        scenario_name,
                        agg,
                    ),
                    format_annual_data(
                        template,
                        new_capacity[year],
                        names[2],
                        "MW",
                        year,
                        model_name,
                        scenario_name,
                        agg,
                    ),
                    format_annual_data(
                        template,
                        retired_capacity[year],
                        names[5],
                        "MW",
                        year,
                        model_name,
                        scenario_name,
                        agg,
                    ),
                ]
            )
            if comp == "StorageUnit":
                result = pd.concat(
                    [
                        result,
                        format_annual_data(
                            template,
                            storage_cap[year],
                            "Storage_Capacity",
                            "MWh",
                            year,
                            model_name,
                            scenario_name,
                            agg,
                        ),
                    ]
                )
            if comp == "Store":
                result = pd.concat(
                    [
                        result,
                        format_annual_data(
                            template,
                            store_cap[year],
                            "Storage_Capacity",
                            "MWh",
                            year,
                            model_name,
                            scenario_name,
                            agg,
                        ),
                    ]
                )
    return result


def calc_capex(n, comp, years, templates, agg=True):
    """Compute capital, fixed O&M, other and total capex per period."""
    stats = n.statistics
    result = pd.DataFrame()
    costs = pd.DataFrame()
    expanded_capacity = pd.DataFrame()
    total_capex = pd.DataFrame()
    names = ["Capital_Cost", "Fixed_OM_Cost", "Other_Capacity_Costs", "Total_Capex"]

    if comp != "Transmission":
        expanded_capacity = manual_capacity_calc(n, comp)
        total_capex = stats.capex(comps=comp, groupby=False).fillna(0)

    match comp:
        case "Generator":
            template = templates["generator_template"]
            if not template.empty:
                costs = n.generators[["capital_cost", "cap_cost", "fixed_om"]]
        case "StorageUnit":
            template = templates["storage_unit_template"]
            if not template.empty:
                costs = n.storage_units[["capital_cost", "cap_cost", "fixed_om"]]
        case "Store":
            template = templates["store_template"]
            if not template.empty:
                costs = pd.concat([costs, n.stores[["capital_cost"]]])
                costs["cap_cost"] = costs.capital_cost
                costs["fixed_om"] = 0
        case "Transmission":
            template = templates["transmission_template"]
            names = [name + "_Transmission" for name in names]
            if not template.empty:
                if not n.lines.empty:
                    costs = pd.concat([costs, n.lines[["capital_cost"]]])
                    expanded_capacity = pd.concat(
                        [expanded_capacity, manual_capacity_calc(n, "Line")]
                    )
                    total_capex = pd.concat(
                        [
                            total_capex,
                            stats.capex(comps="Line", groupby=False).fillna(0),
                        ]
                    )
                if not n.links.empty:
                    costs = pd.concat([costs, n.links[["capital_cost"]]])
                    expanded_capacity = pd.concat(
                        [expanded_capacity, manual_capacity_calc(n, "Link")]
                    )
                    total_capex = pd.concat(
                        [
                            total_capex,
                            stats.capex(comps="Link", groupby=False).fillna(0),
                        ]
                    )
                costs["cap_cost"] = costs.capital_cost
                costs["fixed_om"] = 0

    if not template.empty:
        other_costs_mask = (costs.cap_cost.isna()) & (costs.fixed_om.isna())
        other_costs_idx = costs.loc[other_costs_mask].index
        capital_costs = (
            expanded_capacity.reindex(costs.index)
            .multiply(costs.cap_cost, axis=0)
            .dropna(how="all")
        )
        fixed_om_costs = (
            expanded_capacity.reindex(costs.index)
            .multiply(costs.fixed_om, axis=0)
            .dropna(how="all")
        )
        other_costs = (
            expanded_capacity.reindex(other_costs_idx)
            .multiply(costs.loc[other_costs_idx, "capital_cost"], axis=0)
            .dropna(how="all")
        )

        for year in years:
            weight = n.investment_period_weightings.loc[year, "objective"]
            for data, name in [
                (capital_costs, names[0]),
                (fixed_om_costs, names[1]),
                (other_costs, names[2]),
                (total_capex, names[3]),
            ]:
                result = pd.concat(
                    [
                        result,
                        format_annual_data(
                            template,
                            data[year],
                            name,
                            "$",
                            year,
                            model_name,
                            scenario_name,
                            agg,
                        ),
                        format_annual_data(
                            template,
                            data[year].multiply(weight),
                            f"Weighted_{name}",
                            "$",
                            year,
                            model_name,
                            scenario_name,
                            agg,
                        ),
                    ]
                )
    return result


def calc_reserve_capacity(n, comp, years, templates, agg=True):
    """Discount capacity by planning reserve capacity values."""
    # module_dir = os.path.join(
    #     os.path.dirname(__file__), "..", "..", "data", "constraints"
    # )
    capacity_values_path = (
        config.get("planning", {})
        .get("constraints", {})
        .get("planning_reserve_margin", {})
        .get("capacity_values_placeholder_filepath", None)
    )

    if capacity_values_path and os.path.exists(capacity_values_path):
        capacity_values = pd.read_csv(capacity_values_path, index_col="Carrier")
    else:
        logging.warning("Capacity values file not found, skipping reserve capacity")
        return pd.DataFrame()

    stats = n.statistics
    capacity_values_unit = pd.DataFrame()
    result = pd.DataFrame()
    unit_cap = stats.optimal_capacity(comps=comp, groupby=False).fillna(0)

    if comp == "Generator" and not templates["generator_template"].empty:
        template = templates["generator_template"]
        capacity_values_unit = (
            pd.merge(
                n.generators["model"],
                capacity_values,
                left_on="model",
                right_index=True,
            )
            .drop("model", axis=1)
            .reindex(unit_cap.index)
        )
    elif comp == "StorageUnit" and not templates["storage_unit_template"].empty:
        template = templates["storage_unit_template"]
        capacity_values_unit = (
            pd.merge(
                n.storage_units["model"],
                capacity_values,
                left_on="model",
                right_index=True,
            )
            .drop("model", axis=1)
            .reindex(unit_cap.index)
        )

    if not capacity_values_unit.empty:
        capacity_values_unit.columns = capacity_values_unit.columns.astype(int)
        capacity_values_unit = capacity_values_unit.T.reindex(unit_cap.columns).T
        unit_cap = unit_cap.multiply(capacity_values_unit, axis=0)
        for year in years:
            result = pd.concat(
                [
                    result,
                    format_annual_data(
                        template,
                        unit_cap[year],
                        "Qualifying_Capacity",
                        "MW",
                        year,
                        model_name,
                        scenario_name,
                        agg,
                    ),
                ]
            )
    return result


def calc_reserve_load(n, years, templates, planning_reserve, agg=True):
    """Calculate required reserve load using peak load x planning reserve margin."""
    loads = n.loads_t.p_set.copy()
    template = templates["load_template"].copy()
    result = pd.DataFrame()

    for year in years:
        year_load = loads.copy().loc[year].T
        year_load["province"] = n.loads.bus.map(n.buses["province"])
        year_load = year_load[year_load.province.isin(planning_reserve.keys())]
        peak_load = year_load.groupby("province").max().max(axis=1).to_dict()
        year_load["province"] = year_load.province.replace(peak_load)
        year_load["margin"] = n.loads.bus.map(n.buses["province"])
        year_load["province"] = year_load.province.multiply(
            year_load.margin.replace(planning_reserve)
        )
        year_load = year_load["province"]
        reserve_load = format_annual_data(
            template,
            year_load,
            "Reserve_Load",
            "MWh",
            year,
            model_name,
            scenario_name,
            agg,
        )
        result = pd.concat([result, reserve_load])
    return result


def calc_misc_params(n, years, weightings):
    """Compute investment period weightings and representative days count."""
    result = pd.DataFrame()
    for year in years:
        period_weight = {
            "Model": model_name,
            "Scenario": scenario_name,
            "Region": "All",
            "Parameter": "Investment_Period_Weighting",
            "Variable": "planning_model",
            "Time": year,
            "Value": n.investment_period_weightings.loc[year, "objective"],
            "Unit": "n/a",
        }
        result = pd.concat(
            [result, pd.DataFrame.from_dict(period_weight, orient="index").T]
        )

    rep_day_data = {
        "Model": model_name,
        "Scenario": scenario_name,
        "Region": "All",
        "Parameter": "Representative_Days",
        "Variable": "planning_model",
        "Time": "All",
        "Value": int(weightings["objective"].count() / len(years) / 24),
        "Unit": "days",
    }
    result = pd.concat([result, pd.DataFrame.from_dict(rep_day_data, orient="index").T])
    return result


# ────────────────────────────────────────────
# Main execution
# ────────────────────────────────────────────


def main():
    if snakemake is None:
        raise RuntimeError("post_process_planning.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    logging.info("===== PLANNING POST-PROCESS =====")
    start_time = time.perf_counter()

    # Load network
    logging.info("Loading solved planning network...")
    n = pypsa.Network(solved_network_path)

    # Format network
    n, provinces = format_network(n, result_type)

    years = n.investment_periods.tolist()

    # Snapshot weightings
    weightings = n.snapshot_weightings.fillna(0)
    weightings = weightings[weightings.objective > 0]
    weightings.index = weightings.index.get_level_values("timestep")

    # Templates
    templates = create_templates(n)

    logging.info(f"Investment periods: {years}")
    logging.info(f"Network loaded ({round(time.perf_counter() - start_time, 3)} s)")

    # ── Create output directory ──
    os.makedirs(output_dir, exist_ok=True)

    # ── Capacity & Capex ──
    logging.info("Calculating capacity and capex...")
    capacity = pd.concat(
        [
            calc_capacity(n, "Generator", years, templates),
            calc_capex(n, "Generator", years, templates),
            calc_capacity(n, "StorageUnit", years, templates),
            calc_capex(n, "StorageUnit", years, templates),
            calc_capacity(n, "Store", years, templates),
            calc_capex(n, "Store", years, templates),
            calc_capacity(n, "Transmission", years, templates),
            calc_capacity(n, "Reverse_Transmission", years, templates),
            calc_capex(n, "Transmission", years, templates),
        ]
    )

    per_unit_capacity = pd.concat(
        [
            calc_capacity(n, "Generator", years, templates, agg=False),
            calc_capex(n, "Generator", years, templates, agg=False),
            calc_capacity(n, "StorageUnit", years, templates, agg=False),
            calc_capex(n, "StorageUnit", years, templates, agg=False),
            calc_capacity(n, "Store", years, templates, agg=False),
            calc_capex(n, "Store", years, templates, agg=False),
            calc_capacity(n, "Transmission", years, templates, agg=False),
            calc_capacity(n, "Reverse_Transmission", years, templates, agg=False),
            calc_capex(n, "Transmission", years, templates, agg=False),
        ]
    )

    # ── Planning reserve ──
    if planning_reserve_cfg:
        provinces_list = planning_reserve_cfg.get("provinces_list", {})
        if provinces_list:
            logging.info("Calculating planning reserve...")
            reserve = pd.concat(
                [
                    calc_reserve_capacity(n, "Generator", years, templates),
                    calc_reserve_capacity(n, "StorageUnit", years, templates),
                    calc_reserve_load(n, years, templates, provinces_list),
                ]
            )
            reserve_per_unit = pd.concat(
                [
                    calc_reserve_capacity(n, "Generator", years, templates, agg=False),
                    calc_reserve_capacity(
                        n, "StorageUnit", years, templates, agg=False
                    ),
                    calc_reserve_load(n, years, templates, provinces_list, agg=False),
                ]
            )
            capacity = pd.concat([capacity, reserve])
            per_unit_capacity = pd.concat([per_unit_capacity, reserve_per_unit])

    # Misc params
    capacity = pd.concat([capacity, calc_misc_params(n, years, weightings)])
    per_unit_capacity = pd.concat(
        [per_unit_capacity, calc_misc_params(n, years, weightings)]
    )

    # ── Annual metrics & balances ──
    logging.info("Calculating annual metrics...")
    annual_provincial_data = pd.DataFrame()
    annual_unit_data = pd.DataFrame()
    prov_energy_balance = pd.DataFrame()
    storage_balance = pd.DataFrame()

    for year in years:
        annual_provincial_data = pd.concat(
            [
                annual_provincial_data,
                calc_annual(n, year, True, True, templates, model_name, scenario_name),
            ]
        )
        annual_unit_data = pd.concat(
            [
                annual_unit_data,
                calc_annual(n, year, False, True, templates, model_name, scenario_name),
            ]
        )
        prov_energy_balance = pd.concat(
            [
                prov_energy_balance,
                calc_energy_balance(n, year, planning=True),
            ]
        )
        storage_balance = pd.concat(
            [
                storage_balance,
                calc_storage_balance(n, year, planning=True),
            ]
        )

    annual_provincial_data = pd.concat([capacity, annual_provincial_data])
    annual_unit_data = pd.concat([per_unit_capacity, annual_unit_data])

    logging.info(
        f"Calculations finished ({round(time.perf_counter() - start_time, 3)} s)"
    )

    # ── Save results ──
    logging.info("Saving results...")
    annual_provincial_data.sort_values("Parameter").to_csv(
        os.path.join(output_dir, f"{result_type}_summary_planning.csv"), index=False
    )
    annual_unit_data.sort_values("Parameter").to_csv(
        os.path.join(output_dir, "unit_summary_planning.csv"), index=False
    )

    save_prov_energy_balance(
        prov_energy_balance.reindex(weightings.index).dropna(how="all"),
        output_dir,
        result_type,
        provinces,
    )
    save_storage_balance(
        storage_balance.reindex(weightings.index).dropna(how="all"),
        output_dir,
    )

    logging.info(
        f"Planning post-process complete ({round(time.perf_counter() - start_time, 3)} s)"
    )

    finish_benchmark_tracker(
        result_benchmark_csv_path(output_dir),
        "post_process_planning",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    main()
elif snakemake is not None:
    main()
