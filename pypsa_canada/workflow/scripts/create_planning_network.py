# scripts/solve_planning.py
import logging
import os
import sys
import traceback

import pandas as pd
import pypsa

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/create_planning.log"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Configure logging to both file and stdout (handy for --show-failed-logs)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)


def main():
    # ----------------------------
    # 1. Create network and multi-index snapshots
    # ----------------------------
    # periods = [2025, 2030]

    # timestamps_2025 = pd.date_range("2025-08-11 00:00", periods=4, freq="h")
    # timestamps_2030 = pd.date_range("2030-08-11 00:00", periods=4, freq="h")

    # multi_snapshots = pd.MultiIndex.from_arrays(
    #     [4 * [2025] + 4 * [2030],
    #      list(timestamps_2025) + list(timestamps_2030)],
    #     names=["period", "timestamp"]
    # )
    timestamps_2025 = pd.date_range("2025-08-11 00:00", periods=8, freq="h")
    timestamps_2030 = pd.date_range("2030-08-11 00:00", periods=8, freq="h")
    period_labels = [2025] * len(timestamps_2025) + [2030] * len(timestamps_2030)
    timestamps = list(timestamps_2025) + list(timestamps_2030)

    multi_snapshots = pd.MultiIndex.from_arrays(
        [period_labels, timestamps], names=["period", "timestep"]
    )

    network = pypsa.Network()
    network.set_snapshots(multi_snapshots)

    weightings = pd.Series(
        [1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0] * 2,
        index=multi_snapshots,
        name="objective",
    )
    network.snapshot_weightings = weightings
    # ----------------------------
    # 2. Add period to snapshot weightings and set objective weights
    # ----------------------------
    network.snapshot_weightings["period"] = network.snapshots.get_level_values("period")

    # Set weights: Only 2025 contributes to objective
    # network.snapshot_weightings["objective"] = network.snapshot_weightings["period"].map({
    #     2025: 6,   # Each 2025 snapshot counts for 6 hours
    #     2030: 2    # Skip 2030 in objective
    # })
    network.investment_periods = pd.Index([2025, 2030])
    network.investment_period_weightings["discount_rate"] = 0.05
    network.investment_period_weightings["objective"] = {2025: 1, 2030: 1}
    network.investment_period_weightings["years"] = {2025: 5, 2030: 5}

    # Clean snapshot_weightings to avoid export bug
    if "period" in network.snapshot_weightings.columns:
        network.snapshot_weightings = network.snapshot_weightings.drop(columns="period")
    # ----------------------------
    # 3. Add components
    # ----------------------------
    network.add("Bus", "bus0", province="QC")
    network.add("Bus", "bus0", province="QC")
    network.add("Carrier", "gas", co2_emissions=0.5)  # tCO2 per MWh
    network.add("Carrier", "wind", co2_emissions=0.0)
    # Add fossil generator (with emissions)
    network.add(
        "Generator",
        "gen0",
        bus="bus0",
        p_nom=100,
        p_nom_min=200,
        marginal_cost=10,
        p_nom_extendable=True,
        capital_cost=60,
        carrier="gas",
        model="gas_CC",
    )

    # network.add(
    #     "Generator",
    #     "nuclear0",
    #     bus="bus0",
    #     p_nom=100,
    #     marginal_cost=1,
    #     # committable=True,
    #     p_nom_extendable=True,
    #     build_year=2030,
    #     p_min_pu=0.3,
    #     p_max_pu=1,
    #     ramp_limit_up=1,
    #     ramp_limit_start_up=0.3,
    #     ramp_limit_shut_down=1,
    #     start_up_cost=10,
    #     shut_down_cost=10,
    #     capital_cost=120,
    #     carrier="nuclear",
    # )

    # Add wind generator (no emissions)
    network.add(
        "Generator",
        "wind0",
        bus="bus0",
        p_nom=80,
        p_nom_min=100,
        marginal_cost=0,
        p_nom_extendable=True,
        capital_cost=50,
        carrier="wind_new",
        model="wind_new",
    )

    network.add(
        "Generator",
        "gen_optional1",
        bus="bus0",
        p_nom_extendable=True,
        p_max_pu=1.0,
        p_nom_max=200,
        p_nom_min=10,
        capital_cost=100,  # €/MW
        build_year=2025,
        lifetime=20,
        marginal_cost=20,
        carrier="gas_CC",
        model="gas_CC",
    )
    network.add(
        "Generator",
        "gen_optional2",
        bus="bus0",
        p_nom_extendable=True,
        p_max_pu=1.0,
        capital_cost=100,  # €/MW
        build_year=2025,
        lifetime=20,
        marginal_cost=20,
        carrier="wind_new",
        model="wind_new",
    )

    network.add(
        "Generator",
        "gen_optional3",
        bus="bus0",
        p_nom_extendable=True,
        p_max_pu=1.0,
        capital_cost=100,  # €/MW
        build_year=2025,
        lifetime=20,
        marginal_cost=20,
        carrier="wind_new",
        model="wind_new",
    )

    network.add(
        "Generator",
        "gen_optional3",
        bus="bus0",
        p_nom_extendable=True,
        p_max_pu=1.0,
        capital_cost=100,  # €/MW
        build_year=2030,
        lifetime=20,
        marginal_cost=20,
        carrier="wind",
        model="wind_new",
    )
    # Add load
    # load_series = pd.Series(120, index=network.snapshots)
    # load_series = load_series.reindex(network.snapshots)
    # network.add("Load", "load0", bus="bus0", p_set=load_series)

    # ----------------------------
    # 4. Set generator availability (p_max_pu)
    # ----------------------------

    availability = pd.DataFrame(
        {"gen0": [1.0, 0.8, 0.5, 0.4] * 4, "wind0": [0.4, 0.2, 0.3, 0.1] * 4},
        index=multi_snapshots,
    ).reindex(network.snapshots)
    network.generators_t.p_max_pu = availability

    load_series = pd.Series(
        [120, 150, 200, 220, 265, 100000, 100000, 167] * 2, index=multi_snapshots
    ).reindex(network.snapshots)
    # network.loads_t.p_set = load_series
    network.add("Load", "QC", bus="bus0", p_set=load_series, province="QC")
    print("names:", network.snapshots.names)
    print("SW aligned:", network.snapshot_weightings.index.equals(network.snapshots))
    print(
        "p_max_pu aligned:",
        network.generators_t.p_max_pu.index.equals(network.snapshots),
    )
    print("p_set aligned:", network.loads_t.p_set.index.equals(network.snapshots))
    # ----------------------------
    # 5. Add global constraints (emissions per period)
    # ----------------------------
    # for period in periods:
    #     network.add("GlobalConstraint", f"emission_limit_{period}",
    #                 type="emissions",
    #                 carrier_attribute="emissions",
    #                 sense="<=",
    #                 constant=20.0,
    #                 period=period)

    # ----------------------------
    # 6. Build the optimization model (no snapshot slicing!)
    # ----------------------------

    # # Get snapshot_weightings DataFrame (multi-index with 'period' and timestamp)
    # sw = network.snapshot_weightings.copy()

    # # For each period, find the last snapshot and set its 'objective' weighting to 0
    # for period in sw.index.get_level_values('period').unique():
    #     # Filter to this period
    #     sw_period = sw.loc[period]

    #     # Get the last snapshot timestamp for this period
    #     last_snapshot = sw_period.index.max()

    #     # Set its weighting to 0
    #     sw.loc[(period, last_snapshot), 'objective'] = 0

    # # Assign back to the network
    # network.snapshot_weightings = sw
    # print(f'New_snapshots={network.snapshot_weightings}')

    # valid_snapshots = network.snapshot_weightings.query("objective > 0").index
    # print(f'Valid_snapshots={valid_snapshots}')
    # filtered_snapshots = network.snapshots.intersection(valid_snapshots)
    # print(f'Intersection={valid_snapshots}')
    # network.set_snapshots(filtered_snapshots)
    # print(f'New_snapshots={network.snapshot_weightings}')

    # # Dict mapping period to list of snapshots to remove in that period
    # snapshots_to_remove_per_period = {
    #     2025: [pd.Timestamp('2025-08-11 02:00:00')],
    #     2030: [pd.Timestamp('2025-08-11 03:00:00')]
    # }

    # # Build a mask to keep only snapshots not in removal lists per period
    # def keep_snapshot(idx):
    #     period, snapshot = idx
    #     remove_list = snapshots_to_remove_per_period.get(period, [])
    #     return snapshot not in remove_list

    # mask = network.snapshot_weightings.index.map(keep_snapshot)

    # network.snapshot_weightings = network.snapshot_weightings[mask]

    # Filter snapshots to keep only those with weighting > 0
    positive_snapshots = weightings[weightings > 0].index
    # Set snapshots in network to filtered snapshots (dropping zero-weight snapshots)
    # network.set_snapshots(positive_snapshots)

    # IMPORTANT: also update snapshot_weightings to keep only filtered snapshots
    # network.snapshot_weightings = weightings.loc[positive_snapshots]
    # print(f"New_snapshots={network.snapshot_weightings}")

    # 1) Ensure the MultiIndex level names are exactly ["period", "timestep"]
    if network.snapshots.names != ["period", "timestep"]:
        network.set_snapshots(network.snapshots.set_names(["period", "timestep"]))

    # 2) Keep snapshot_weightings as a DataFrame and reindex it to the (possibly renamed) snapshots
    if not hasattr(network.snapshot_weightings, "columns"):
        # If it ever became a Series accidentally, convert to a DataFrame
        network.snapshot_weightings = network.snapshot_weightings.to_frame("objective")

    # network.snapshot_weightings = network.snapshot_weightings.loc[network.snapshots]

    # 3) Reindex ALL time-series tables to the updated snapshots
    # network.generators_t.p_max_pu = network.generators_t.p_max_pu.reindex(network.snapshots)
    # network.loads_t.p_set         = network.loads_t.p_set.reindex(network.snapshots)

    # 4) (Optional but tidy) make sure the investment periods index is explicitly named
    # import pandas as pd
    if getattr(network.investment_periods, "name", None) != "period":
        network.investment_periods = pd.Index(network.investment_periods, name="period")

    # 5) Sanity checks
    # logging.info(f'network_snapshots.names = {network.snapshots.names}')
    assert network.snapshots.names == ["period", "timestep"]
    assert network.snapshot_weightings.index.equals(network.snapshots)
    assert network.generators_t.p_max_pu.index.equals(network.snapshots)
    assert network.loads_t.p_set.index.equals(network.snapshots)

    # Save a copy of the network unfiltered
    # network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    network.export_to_netcdf(snakemake.output.planning_unsolved_network_unfiltered)

    # Filter snapshots to keep only those with weighting > 0
    positive_snapshots = weightings[weightings > 0].index
    # Set snapshots in network to filtered snapshots (dropping zero-weight snapshots)
    network.set_snapshots(positive_snapshots)

    # IMPORTANT: also update snapshot_weightings to keep only filtered snapshots
    network.snapshot_weightings = weightings.loc[positive_snapshots]
    network.snapshot_weightings = network.snapshot_weightings.loc[network.snapshots]
    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if(config["run"]["export_csv"]):
        network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("solve_planning failed:\n%s", traceback.format_exc())
        sys.exit(1)
