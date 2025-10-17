
# scripts/solve_planning.py
import os
import sys
import logging
import traceback
import pandas as pd
import pypsa


# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/solve_planning.log"

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
    # with open(snakemake.input[0], "r") as infile, open(snakemake.output[0], "w") as outfile:
    #     for line in infile:
    #         if snakemake.config.get("uppercase", False):
    #             outfile.write(line.upper())
    #         else:
    #             outfile.write(line)
    #         logging.info("Done.")    
    # in_path = str(snakemake.input[0])
    # out_path = str(snakemake.output[0])

    # logging.info("Reading input: %s", in_path)
    # with open(in_path, "r", encoding="utf-8") as f:
    #     text = f.read().strip()

    # # Minimal "processing": make it uppercase
    # result = text.upper()

    # # Ensure output directory exists
    # os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # logging.info("Writing output: %s", out_path)
    # with open(out_path, "w", encoding="utf-8") as f:
    #     f.write(result + "\n")

    # logging.info("Done.")


    # ----------------------------
    # 1. Create network and multi-index snapshots
    # ----------------------------
    periods = [2025, 2030]

    # timestamps_2025 = pd.date_range("2025-08-11 00:00", periods=4, freq="H")
    # timestamps_2030 = pd.date_range("2030-08-11 00:00", periods=4, freq="H")

    # multi_snapshots = pd.MultiIndex.from_arrays(
    #     [4 * [2025] + 4 * [2030],
    #      list(timestamps_2025) + list(timestamps_2030)],
    #     names=["period", "timestamp"]
    # )
    timestamps_2025 = pd.date_range("2025-08-11 00:00", periods=4, freq="H")
    timestamps_2030 = pd.date_range("2030-08-11 00:00", periods=4, freq="H")
    period_labels = [2025] * len(timestamps_2025) + [2030] * len(timestamps_2030)
    timestamps = list(timestamps_2025) + list(timestamps_2030)

    multi_snapshots = pd.MultiIndex.from_arrays(
        [period_labels, timestamps], names=["period", "timestamp"]
    )

    network = pypsa.Network()
    network.set_snapshots(multi_snapshots)

    weightings = pd.Series(
        [1.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0], index=multi_snapshots, name="objective"
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
    network.add("Bus", "bus0")
    network.add("Carrier", "gas", co2_emissions=0.5)  # tCO2 per MWh
    network.add("Carrier", "wind", co2_emissions=0.0)
    # Add fossil generator (with emissions)
    network.add(
        "Generator",
        "gen0",
        bus="bus0",
        p_nom=100,
        marginal_cost=10,
        p_nom_extendable=True,
        capital_cost=60,
        carrier="gas",
    )

    # Add wind generator (no emissions)
    network.add(
        "Generator",
        "wind0",
        bus="bus0",
        p_nom=80,
        marginal_cost=0,
        p_nom_extendable=True,
        capital_cost=100,
        carrier="wind",
    )

    # network.add("Generator", "gen_optional1",
    #             bus="bus0",
    #             p_nom_extendable=True,
    #             p_max_pu=1.0,
    #             p_nom_max=200,
    #             p_nom_min=10,
    #             capital_cost=100,  # €/MW
    #             build_year=2025,
    #             marginal_cost=20,
    #             p_nom_extendable=True,
    #             carrier="gas")
    # network.add("Generator", "gen_optional2",
    #             bus="bus0",
    #             p_nom_extendable=True,
    #             p_max_pu=1.0,
    #             capital_cost=100,  # €/MW
    #             build_year=2030,
    #             lifetime=20,
    #             marginal_cost=20,
    #             carrier="gas")
    # Add load
    load_series = pd.Series(120, index=network.snapshots)
    network.add("Load", "load0", bus="bus0", p_set=load_series)

    # ----------------------------
    # 4. Set generator availability (p_max_pu)
    # ----------------------------
    availability = pd.DataFrame(
        {
            "gen0": [1.0, 0.8, 0.5, 0.4] * 2,
            "wind0": [0.4, 0.2, 0.3, 0.1] * 2,
            # "gen_optional1": [1.0] * 8,
            # "gen_optional2": [1.0] * 8,
        },
        index=network.snapshots,
    )

    network.generators_t.p_max_pu = availability

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
    network.set_snapshots(positive_snapshots)

    # IMPORTANT: also update snapshot_weightings to keep only filtered snapshots
    network.snapshot_weightings = weightings.loc[positive_snapshots]
    print(f"New_snapshots={network.snapshot_weightings}")

    model = network.optimize.create_model(multi_investment_periods=True)

    #add_emission_constraint_planning(model, network, network.snapshots, 100.0, 2025)
    #add_emission_constraint_planning(model, network, network.snapshots, 0, 2030)

    # # m = network.lopf
    solve_status, solve_condition = network.optimize.solve_model(
        assign_all_duals=True,
        solver_name="highs",
    )

    out_path = str(snakemake.output[0])

    network.export_to_csv_folder(out_path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("solve_planning failed:\n%s", traceback.format_exc())
        sys.exit(1)
