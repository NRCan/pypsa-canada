import pandas as pd


def distribute_CER_hours_dispatch(network, year):
    VRE_carriers = ["wind", "solar PV", "hydro"]
    VRE_gens = network.generators[
        (
            (network.generators["carrier"].isin(VRE_carriers))
            & (network.generators["p_nom"] != 0)
        )
    ]
    # hydro_inflows = network.storage_units_t.inflow.loc[f'{year}'].sum(axis=1)
    p_max_pu = network.generators_t.p_max_pu.loc[:, VRE_gens.index]
    load = network.loads_t.p_set.loc[
        f"{year}", ~network.loads_t.p_set.columns.str.contains("QC")
    ].sum(axis=1)
    CER_data = pd.DataFrame(load.values, index=load.index, columns=["load"])

    for name in VRE_gens.index:
        p_max_pu[name] *= VRE_gens[VRE_gens.index == name].p_nom.values[0]

    CER_data["VRE_generation"] = p_max_pu.sum(axis=1)
    CER_data["net_load"] = (
        CER_data["load"] - CER_data["VRE_generation"]
    )  # - hydro_inflows

    average_load = CER_data["net_load"].mean()

    CER_data["above_avg_load"] = CER_data["net_load"] - average_load

    total_hours = CER_data[CER_data["above_avg_load"] > 0].count().values[0]
    print(f"Hours exceeding average load: {total_hours}")

    return CER_data


def add_CER_constraint_dispatch(
    constraint,
    m,
    network,
    snapshots,
    uc_period,
    period_value,
    budget,
    groups,
    leftover,
    CER_gens,
):
    budget_snapshot = {}
    budget_snapshot_with_leftover = {}

    # Set the limit and offset based on the year
    year = snapshots[0].year
    limit, offset = None, None
    for limit_year in constraint["values"]["limit"]:
        if year >= int(limit_year):
            limit = constraint["values"]["limit"][limit_year]
            offset = constraint["values"]["offset"][limit_year]
            continue
        else:
            if limit is not None and offset is not None:
                break
            else:
                raise ValueError(
                    f"No limit or offset found for year {year} in constraint values."
                )

    for group in groups:
        lhs = 0
        unit = "hours"  # Default unit

        leftover_budget = leftover[group] if leftover else 0
        # Ensure budget is never negative
        leftover_budget = max(leftover_budget, 0)

        gens = CER_gens[CER_gens.group == group]
        budget_snapshot[group] = 0
        budget_snapshot_with_leftover[group] = 0

        for gen, data in gens.iterrows():
            match constraint["mode"]:
                case "hourly":
                    unit = "hours"
                    lhs += (m["Generator-status"].loc[snapshots, gen]).sum()

                    if constraint["forecast_hours"] == "carryover":
                        # If carryover, 100% of the budget is available for the first period
                        if not uc_period:
                            budget_snapshot[group] += round(limit + offset)
                    else:
                        if not uc_period:
                            # 10% of the budget for the first period
                            budget_snapshot[group] += round((limit + offset) * 0.1)
                        else:
                            # Use the period value to scale the budget
                            budget_snapshot[group] += round(
                                (limit + offset) * period_value
                            )

                case "emissions":
                    unit = "tCO2eq"
                    lhs += (m["Generator-p"].loc[snapshots, gen]).sum() * (
                        network.carriers.loc[data.carrier].co2_emissions
                        / data.efficiency
                    )

                    if constraint["forecast_hours"] == "carryover":
                        # If carryover, 100% of the budget is available for the first period
                        if not uc_period:
                            budget_snapshot[group] += (
                                (limit + offset) * data.p_nom_opt * 8760 / 1000
                            )
                    else:
                        if not uc_period:
                            # 10% of the budget for the first period
                            budget_snapshot[group] += (
                                (limit + offset) * 0.1 * data.p_nom_opt * 8760 / 1000
                            )
                        else:
                            # Use the period value to scale the budget
                            budget_snapshot[group] += (
                                (limit + offset) * data.p_nom_opt * 8760 / 1000
                            ) * period_value

        # Add leftover budget to the budget snapshot
        budget_snapshot_with_leftover[group] = budget_snapshot[group] + leftover_budget

        print(
            f"CER constraint for {group} is {budget_snapshot[group] + leftover_budget} {unit} for this period, which includes a leftover of {leftover_budget}"
        )
        # Add the constraint to the model
        m.add_constraints(
            lhs,
            "<=",
            budget_snapshot[group] + leftover_budget,
            name=f"CER_constraint_{group}_{unit}_{snapshots[0]}",
        )

    # Add the budget snapshot to the budget DataFrame
    budget = pd.concat(
        [
            budget,
            pd.DataFrame.from_dict(
                budget_snapshot_with_leftover,
                orient="index",
                columns=[f"{snapshots[0]}:{snapshots[-1]}"],
            ).T,
        ]
    )
    return budget
