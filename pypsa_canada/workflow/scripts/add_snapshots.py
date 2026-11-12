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


def forecast_p_max_pu(
    n: Network,
    comp_config: dict[str, Any],
):
    p_max_pu_forecast: pd.DataFrame | None = None
    override_dir: str = comp_config["override_dir"]
    override_filepath = os.path.join(override_dir, "generators_p_max_pu_forecast.csv")
    if os.path.isfile(override_filepath):
        print(f"p_max_pu forecast file detected in {override_filepath}")
        p_max_pu_forecast = pd.read_csv(
            override_filepath, index_col=0, parse_dates=True
        )
    if p_max_pu_forecast is not None:
        # Apply wind loss factor
        wind_gens = n.generators[
            (n.generators.carrier == "wind")
            & (n.generators.index.isin(p_max_pu_forecast.columns))
        ]
        p_max_pu_forecast[wind_gens.index] *= wind_gens.loc[
            wind_gens.index, "efficiency"
        ]

        # Add or overwrite profiles in "generators-p_max_pu.csv" using "generators_p_max_pu_forecast.csv"
        common_idx = n.generators_t.p_max_pu.index.intersection(p_max_pu_forecast.index)
        for col in p_max_pu_forecast.columns:
            n.generators_t.p_max_pu.loc[common_idx, col] = p_max_pu_forecast.loc[
                common_idx, col
            ]
        n.generators_t.p_max_pu = n.generators_t.p_max_pu.round(4)
    return n


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

    # Read forecasted p_max_pu
    network = forecast_p_max_pu(network, comp_config)

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
