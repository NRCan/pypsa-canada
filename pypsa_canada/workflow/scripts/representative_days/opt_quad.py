import os

import linopy as lp
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa
import xarray as xr


def opt_quad_method(
    n: pypsa.Network,
    provinces: list,
    year: int = None,
    aggregate: bool = False,
    bin: int = 12,
    solver: str = "cbc",
    mip_gap: float = 0.01,
    save_fig: bool = True,
    save_csv: bool = False,
    saving_folder_path="./",
):
    """
    _summary_

    Parameters
    ----------
    n : pypsa.Network
        Imported pypsa network
    provinces : list
        List of provinces whose data are to be used to generate representative days
    year: int, optional
        Year to use to create representative days; if None (default), finds representative days for each year/period
    aggregate: boolean, optional
        If false, consider the profiles of each province separately in the list; if true, do the sum of the profiles of the provinces in the list
    cluster : int, optional
        Number of clusters, by default 6
    save_fig : bool, optional
        Save figure if needed, by default True
    save_csv : bool, optional
        Save snapshot file, by default False
    saving_folder_path: str, optional
        Location of folder to be save into, by default current working directory

    Returns
    -------
    pd.DataFrame
        Snapshot weighting dataframe
    """

    # Function to reshape a vector to (Number of days x 24)
    def daily_profile(data, hours_per_day=24):
        return np.reshape(data, (len(data) // hours_per_day, hours_per_day))

    # Function to delete last edge and reverse the array
    def trim_reverse(array):
        return array[:-1][::-1]

    # Function to get percentual values corresponding to bin edges
    def get_percentile_values(data, edges, x):
        indices = [np.where(data <= edge)[0][0] for edge in edges]
        return x[indices] / 100

    # Function to build matrix A for optimization
    def build_A_matrix(A, data, edges):
        for i, edge in enumerate(edges):
            A[i, :] = np.sum(data >= edge, axis=1) / 24
        return A

    # Function to create sets A and L for optimization
    def create_AL_sets(A, b_values, b_coord, d_coord, percentile_values):
        # A_set = {(b, d): A[b-1, d-1] for b in b_values for d in d_values}
        L_set = pd.Series({b: percentile_values[b - 1] for b in b_values})
        A_set = xr.DataArray(A, coords=[b_coord, d_coord])
        L_set = xr.DataArray(L_set, coords=[b_coord])
        return A_set, L_set

    # Function to extract non-zero elements from a dictionary
    def get_non_zero_elements(x):
        non_zero_mask = x != 0
        ind = np.where(non_zero_mask)[0]
        val = x.values[non_zero_mask]
        result = list(zip(ind, val))
        return result

    # Function to create a representative duration curve
    def create_representative_curve(data, weights):
        rep_data = []
        residue = []  # Vector to save residue
        res_data = [0] * len(data[0, :])  # Vector to estimate residual data
        for w in weights:
            row = data[w[0], :]
            int_part = int(w[1])
            res_part = w[1] - int_part
            repel = [elem for elem in row for _ in range(int_part)]
            rep_data.extend(repel)
            res_data += res_part * row  # Right now this will be the total hourly energy
            residue.append(res_part)
        sum_res = sum(residue)
        res_data = res_data / sum_res  # Now I have the average vector for the residual
        repel = [elem for elem in res_data for _ in range(round(sum_res))]
        rep_data.extend(repel)
        return np.sort(rep_data)[::-1]

    # Function to plot duration curve comparison
    def plot_duration_curves(
        xaxis, original_data, representative_data, ylabel, title, ax
    ):
        ax.plot(xaxis, original_data, "b", label="Original")
        ax.plot(xaxis, representative_data, "r", label="Representative")
        ax.set_xlabel("Percentage of Data (%)")
        ax.set_ylabel(ylabel)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 1)
        ax.legend()
        ax.grid(True)
        ax.set_title(title)

    # Function to plot duration curve and bin edges
    def plot_duration_bins(xaxis, original_data, per_data, edges, ylabel, title, ax):
        ax.plot(xaxis, original_data, "b", label="Duration Curve")
        ax.scatter(per_data * 100, edges, c="red", label="Bins")
        ax.set_xlabel("Percentage of Data (%)")
        ax.set_ylabel(ylabel)
        ax.set_xlim(0, 100)
        ax.set_ylim(0, 1)
        ax.legend()
        ax.grid(True)
        ax.set_title(title)

    # Function to plot A matrix
    def plot_A(A_data, title, ax):
        ax.imshow(A_data, cmap="jet", aspect="auto")
        ax.set_xlabel("Days")
        ax.set_ylabel("Bins")
        ax.set_title(title)

    # Function to get hourly timestamps
    def get_timestamps(non_zero, yr, df):
        start_date = str(yr) + "-01-01"
        dates = pd.date_range(
            start=start_date, end=f"{pd.to_datetime(start_date).year}-12-31", freq="D"
        )
        dates = dates[~((dates.month == 2) & (dates.day == 29))]
        for day, w in non_zero:
            day_start = dates[day]
            hour_stamps = pd.date_range(start=day_start, periods=24, freq="h")
            df.loc[pd.IndexSlice[:, hour_stamps], ["objective", "generators"]] = w
            df.loc[pd.IndexSlice[:, hour_stamps], ["stores"]] = 1
        return df

    # Load snapshots and obtain unique periods
    snap_df = n.snapshot_weightings.copy()
    snap_df[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    periods = np.unique(snap_df.index.get_level_values("period"))
    # Load generators.csv
    # gen_df = n.df("Generator")
    gen_df = n.c["Generator"].static

    gen_df["province"] = gen_df["bus"].map(n.buses["province"])
    # Load generators-p_max_pu.csv
    gen_max_df = n.generators_t.p_max_pu.copy()
    # gen_max_df['province'] = gen_max_df['bus'].map(n.buses['province'])

    # temp_load_prov = n.loads.static
    load_prov_df = n.c["Load"].static
    load_prov_df["province"] = load_prov_df["bus"].map(n.buses["province"])
    # Load loads-p_set.csv
    # load_df = n.loads_t.p_set.copy()
    # load_df['province'] = load_df['bus'].map(n.buses['province'])

    # RES list
    RES = ["wind", "solar"]

    print(f"Periods = {periods}")
    # Obtain yearly data in dictionaries
    if year is None:
        # Dictionary for year
        year_info = {}
        for period in periods:
            # Select year of interest
            gen_max_df_period = gen_max_df.loc[pd.IndexSlice[period, :], :]

            # Now to the decision if the model is aggregated or not
            if aggregate:
                # Code for aggregate
                filter_gen_df = gen_df[gen_df["carrier"].isin(RES)]
            else:
                prov_info = {}

                print("Provinces = ", provinces)
                for prov in provinces:
                    # Filter generators
                    filter_gen_df = gen_df[
                        gen_df["carrier"].isin(RES) & (gen_df["province"] == prov)
                    ]
                    # Calculate net-load
                    # Load in province
                    load_columns = n.loads[load_prov_df["province"] == prov].index
                    load_df_filtered = n.loads_t.p_set[load_columns]
                    print(f"Load columns for province {prov}: {load_df_filtered}")
                    # load_df_filtered = load_df.loc[
                    #     :, load_df["province"] == prov
                    # ]
                    # Load sum
                    load_agg = load_df_filtered.sum(axis=1)
                    load_agg = load_agg.to_frame()
                    print(f"Load agg columns for province {prov}: {load_agg}")

                    # Select the period of interest
                    load_agg = load_agg.loc[pd.IndexSlice[period, :], :]
                    ############################################
                    # Hydro in province
                    filter_hydro = gen_df[
                        (gen_df["model"] == "hydro_ror")
                        & (gen_df["province"] == prov)
                        & (
                            (
                                n.get_active_assets(
                                    c="Generator", investment_period=period
                                )
                            )
                            == True
                        )
                    ]
                    # Filter columns based on hydro sources
                    hydro_names = filter_hydro.index
                    # Hydro columns hourly capacity factor
                    hydro_cols = gen_max_df_period.loc[:, hydro_names]
                    # Multiply to get hydro hourly generation
                    for name in hydro_names:
                        hydro_cols[name] *= filter_hydro[filter_hydro.index == name][
                            "p_nom"
                        ].values[0]
                    hydro_pow = hydro_cols.sum(axis=1)
                    hydro_pow = hydro_pow.to_frame()
                    hydro_pow.index = load_agg.index
                    net_load = load_agg - hydro_pow
                    ############################################

                    # Calculate average capacity factor for each RES type
                    RES_cf = pd.DataFrame(columns=RES)
                    for res in RES:
                        # Get current RES gen
                        current_res = filter_gen_df[
                            filter_gen_df["carrier"].str.contains(
                                res, case=False, na=False
                            )
                        ]
                        # Extract the generators names
                        current_res = (
                            current_res.reset_index()
                        )  # To avoid Generator being an index
                        # Generators names
                        # names = current_res["Generator"].tolist()
                        names = current_res["name"].tolist()
                        # Columns of the respective RES
                        if not names:
                            # No generators of this type in the province; treat as zero
                            RES_cf[res] = pd.Series(0.0, index=gen_max_df_period.index)
                        else:
                            RES_col = gen_max_df.loc[:, names]
                            # Now their average
                            RES_cf[res] = RES_col.mean(axis=1)
                        RES_cf = RES_cf.loc[pd.IndexSlice[period, :], :]
                        # RES_cf.to_csv(f"{saving_folder_path}rescf.csv")
                    prov_info[prov] = {
                        "net_load": net_load,
                        "RES_cf": RES_cf,
                    }
            # with open(f"{saving_folder_path}prov_info_keys.csv", "w", newline="") as f:
            #     writer = csv.writer(f)
            #     writer.writerow(["Keys"])  # Optional header
            #     writer.writerows([[key] for key in prov_info.keys()])
            year_info[period] = {"prov_info": prov_info}
    # with open(f"{saving_folder_path}year_info_keys.csv", "w", newline="") as f:
    #     writer = csv.writer(f)
    #     writer.writerow(["Keys"])  # Optional header
    #     writer.writerows([[key] for key in year_info.keys()])

    #################################################
    # Now to obtain the duration curve & optimization models
    # Define bins for representative days
    num_bins = bin
    rep_days = num_bins
    # Hours in a day
    hd = 24
    # Get data from dictionaries
    # FIX THIS TO HAVE NON-AGGREGATE
    if not aggregate:
        year_opt = {}
        for year_key, prov_dict in year_info.items():
            prov_dict = prov_dict["prov_info"]
            prov_opt = {}
            print("=====Prov_dict======")
            print(prov_dict.items())
            for prov_key, stats in prov_dict.items():
                # Read net load and RES data, convert to numpy
                # load_prov = stats["net_load"].to_numpy()
                load_prov = stats["net_load"]
                orig_load_prov = load_prov
                load_prov = load_prov.sort_values(
                    by=load_prov.columns[0], ascending=False
                )
                RES_prov = stats["RES_cf"]
                wind_prov = RES_prov["wind"].to_numpy()
                solar_prov = RES_prov["solar"].to_numpy()

                # Sort data for duration curve
                orig_load_prov = orig_load_prov.to_numpy()
                orig_load_prov = orig_load_prov / max(orig_load_prov)
                orig_load_prov = pd.DataFrame(orig_load_prov)
                load_prov = load_prov.to_numpy()
                load_prov = load_prov / max(load_prov)
                load_prov = pd.DataFrame(load_prov)
                # load_prov.to_csv(f"{saving_folder_path}loadprov.csv", index=False)
                sort_load = load_prov.to_numpy()
                sort_wind = np.sort(wind_prov)[::-1]
                sort_solar = np.sort(solar_prov)[::-1]

                # Define x-axis for duration curves
                xaxis = np.linspace(0, 100, len(sort_load))

                # Obtain duration curve edges
                edge_load = trim_reverse(np.linspace(sort_load[-1], 1, num_bins + 1))
                edge_wind = trim_reverse(np.linspace(sort_wind[-1], 1, num_bins + 1))
                edge_solar = trim_reverse(np.linspace(sort_solar[-1], 1, num_bins + 1))
                # Save to test
                # df = pd.DataFrame(sort_wind)
                # df.to_csv(f"{saving_folder_path}debug.csv", index=False)
                # Get percentile values for bin edges
                print(
                    f"Sort load for province {prov_key} in year {year_key}: {sort_load}"
                )
                print(
                    f"sort_wind for province {prov_key} in year {year_key}: {sort_wind}"
                )
                print(
                    f"sort_solar for province {prov_key} in year {year_key}: {sort_solar}"
                )

                per_load = get_percentile_values(sort_load, edge_load, xaxis)
                per_wind = get_percentile_values(sort_wind, edge_wind, xaxis)
                per_solar = get_percentile_values(sort_solar, edge_solar, xaxis)

                # Reshape for daily profiles
                tab_load = daily_profile(orig_load_prov, hd)
                # with open(f'{saving_folder_path}tab_load.csv', mode='w', newline='') as file:
                #     writer = csv.writer(file)
                #     # Optionally write a header if needed
                #     writer.writerow([f"Hour {i+1}" for i in range(tab_load.shape[1])])  # Column header: Hour 1, Hour 2, ...
                #     # Write each row from tab_load
                #     writer.writerows(tab_load)
                tab_wind = daily_profile(wind_prov, hd)
                tab_solar = daily_profile(solar_prov, hd)

                # Build A matrices for load, wind, and solar
                A_load = build_A_matrix(
                    np.empty((num_bins, len(tab_load))), tab_load, edge_load
                )
                A_wind = build_A_matrix(
                    np.empty((num_bins, len(tab_wind))), tab_wind, edge_wind
                )
                A_solar = build_A_matrix(
                    np.empty((num_bins, len(tab_solar))), tab_solar, edge_solar
                )

                # Save the provincial data
                prov_opt[prov_key] = {
                    "xaxis": xaxis,
                    "load_prov": load_prov,
                    "wind_prov": wind_prov,
                    "solar_prov": solar_prov,
                    "sort_load": sort_load,
                    "sort_wind": sort_wind,
                    "sort_solar": sort_solar,
                    "edge_load": edge_load,
                    "edge_wind": edge_wind,
                    "edge_solar": edge_solar,
                    "per_load": per_load,
                    "per_wind": per_wind,
                    "per_solar": per_solar,
                    "tab_load": tab_load,
                    "tab_wind": tab_wind,
                    "tab_solar": tab_solar,
                    "A_load": A_load,
                    "A_wind": A_wind,
                    "A_solar": A_solar,
                }
            year_opt[year_key] = {"prov_opt": prov_opt}

    # Program to save duration curve and A matrices
    if save_fig:
        # For every year
        if not aggregate:
            for year_key, prov_dict in year_opt.items():
                prov_dict = prov_dict["prov_opt"]
                # Duration curve
                fig1, axes1 = plt.subplots(len(prov_dict), 3, squeeze=False)
                # A Plot
                fig2, axes2 = plt.subplots(len(prov_dict), 3, squeeze=False)

                # Loop through dictionary
                for i, (prov_key, stats) in enumerate(prov_dict.items()):
                    # Province data
                    xaxis = stats["xaxis"]
                    sort_load = stats["sort_load"]
                    per_load = stats["per_load"]
                    edge_load = stats["edge_load"]
                    sort_wind = stats["sort_wind"]
                    per_wind = stats["per_wind"]
                    edge_wind = stats["edge_wind"]
                    sort_solar = stats["sort_solar"]
                    per_solar = stats["per_solar"]
                    edge_solar = stats["edge_solar"]
                    A_load = stats["A_load"]
                    A_wind = stats["A_wind"]
                    A_solar = stats["A_solar"]
                    # Duration curve for load, wind & solar respectively
                    plot_duration_bins(
                        xaxis,
                        sort_load,
                        per_load,
                        edge_load,
                        "Load",
                        f"{prov_key} Load Year {year_key}",
                        axes1[i, 0],
                    )
                    plot_duration_bins(
                        xaxis,
                        sort_wind,
                        per_wind,
                        edge_wind,
                        "Wind",
                        f"{prov_key} Wind Year {year_key}",
                        axes1[i, 1],
                    )
                    plot_duration_bins(
                        xaxis,
                        sort_solar,
                        per_solar,
                        edge_solar,
                        "Solar",
                        f"{prov_key} Solar Year {year_key}",
                        axes1[i, 2],
                    )
                    # Plot A matrices for load, wind & solar respectively
                    plot_A(
                        A_load, f"{prov_key} Load A parameter {year_key}", axes2[i, 0]
                    )
                    plot_A(
                        A_wind, f"{prov_key} Wind A parameter {year_key}", axes2[i, 1]
                    )
                    plot_A(
                        A_solar, f"{prov_key} Solar A parameter {year_key}", axes2[i, 2]
                    )

                # Save figures
                fig1.savefig(
                    f"{saving_folder_path}Duration_curve_{year_key}.png",
                    dpi=300,
                    bbox_inches="tight",
                )
                fig2.savefig(
                    f"{saving_folder_path}A_parameter_{year_key}.png",
                    dpi=300,
                    bbox_inches="tight",
                )

                # Close them
                plt.close(fig1)
                plt.close(fig2)

    # Solver settings
    if solver == "cplex":
        solver_options = {"mip.tolerances.mipgap": mip_gap, "randomseed": 123}
    elif solver == "highs":
        solver_options = {"mip_rel_gap": mip_gap, "random_seed": 123}
    elif solver == "gurobi":
        solver_options = {"MIPGap": mip_gap, "Seed": 123}

    # Now to get the optimization parameters and variables
    if not aggregate:
        # Basic data for the model
        # year_one = next(iter(year_opt))
        # prov_one = next(iter(year_opt[year_one]))
        # Ntot = len(year_opt[year_one][prov_one]["tab_load"])
        # Right I'm forcing the days, make it general afterwarsds
        Ntot = 365
        Nrep = rep_days
        d_values = range(1, Ntot + 1)
        b_values = range(1, num_bins + 1)
        # Create coordinates
        d_coord = pd.Index(d_values, name="days")
        b_coord = pd.Index(b_values, name="bins")
        # Data for each year - Will optimize for each year
        # Dictionary for solutions
        year_sol = {}
        for year_key, prov_dict in year_opt.items():
            # Province parameters for optimization
            # Define model
            model = lp.Model()
            # Define the decision variables
            u = model.add_variables(coords=[d_coord], binary=True, name="u")
            w = model.add_variables(lower=0, coords=[d_coord], name="w")
            # Define the auxiliary variable
            y = model.add_variables(coords=[b_coord], name="y")

            # Define the objective function
            model.add_objective(y.sum())
            # Save province parameters per year
            prov_param = {}
            prov_dict = prov_dict["prov_opt"]
            for prov_key, stats in prov_dict.items():
                # A values
                A_load = stats["A_load"]
                A_wind = stats["A_wind"]
                A_solar = stats["A_solar"]
                # Percentile
                per_load = stats["per_load"]
                per_wind = stats["per_wind"]
                per_solar = stats["per_solar"]
                # A and L for the optimization model
                [Aopt_load, Lopt_load] = create_AL_sets(
                    A_load, b_values, b_coord, d_coord, per_load
                )
                [Aopt_wind, Lopt_wind] = create_AL_sets(
                    A_wind, b_values, b_coord, d_coord, per_wind
                )
                [Aopt_solar, Lopt_solar] = create_AL_sets(
                    A_solar, b_values, b_coord, d_coord, per_solar
                )
                prov_param[prov_key] = {
                    "Aopt_load": Aopt_load,
                    "Aopt_wind": Aopt_wind,
                    "Aopt_solar": Aopt_solar,
                    "Lopt_load": Lopt_load,
                    "Lopt_wind": Lopt_wind,
                    "Lopt_solar": Lopt_solar,
                }
            # Now to get the optimization models
            # Sum of As
            A_sum = (
                sum(prov["Aopt_load"] for prov in prov_param.values())
                + sum(prov["Aopt_wind"] for prov in prov_param.values())
                + sum(prov["Aopt_solar"] for prov in prov_param.values())
            )
            # Sum of As multiplied by the weight
            Aw = A_sum * w / Ntot
            # Sum of Ls
            L_sum = (
                sum(prov["Lopt_load"] for prov in prov_param.values())
                + sum(prov["Lopt_wind"] for prov in prov_param.values())
                + sum(prov["Lopt_solar"] for prov in prov_param.values())
            )
            # Make it an expression for linopy
            L_exp = lp.LinearExpression(L_sum, model=model)
            # Objective function (No modulus here)
            dif_exp = L_exp - Aw.sum("days")

            # Define constraints
            # Modulus constraints
            c1 = y >= dif_exp
            c2 = y >= -dif_exp
            model.add_constraints(c1)
            model.add_constraints(c2)
            # Weight upper bound
            model.add_constraints(w <= Ntot * u)
            # Additional constraints
            model.add_constraints(u.sum() == Nrep)
            model.add_constraints(w.sum() == Ntot)

            # Solve the optimization problem
            model.solve(solver_name=solver, **solver_options)

            # Now get the solution values
            # w values
            optimal_w = w.solution
            # Non-zero weights
            non_zero_weights = get_non_zero_elements(optimal_w)
            # Save solutions
            year_sol[year_key] = {
                # "optimal_w": optimal_w,
                "non_zero_weights": non_zero_weights
            }

    # Now to plot the approximated duration curve vs original
    if save_fig:
        # For every year
        if not aggregate:
            # Will need province data for each year and solutions
            for year_key, prov_dict in year_opt.items():
                # Get the nonzero weights solution
                non_zero_weights = year_sol[year_key]["non_zero_weights"]
                # Create a figure
                prov_dict = prov_dict["prov_opt"]
                fig3, axes3 = plt.subplots(len(prov_dict), 3, squeeze=False)
                # Each province
                for i, (prov_key, stats) in enumerate(prov_dict.items()):
                    # Daily profiles
                    xaxis = stats["xaxis"]
                    tab_load = stats["tab_load"]
                    tab_wind = stats["tab_wind"]
                    tab_solar = stats["tab_solar"]
                    # Create representative duration curves
                    ap_load = create_representative_curve(tab_load, non_zero_weights)
                    ap_wind = create_representative_curve(tab_wind, non_zero_weights)
                    ap_solar = create_representative_curve(tab_solar, non_zero_weights)
                    # Original curves
                    sort_load = stats["sort_load"]
                    sort_wind = stats["sort_wind"]
                    sort_solar = stats["sort_solar"]
                    # Plot duration curves
                    plot_duration_curves(
                        xaxis,
                        sort_load,
                        ap_load,
                        "Load",
                        f"{prov_key} Load Curve {year_key}",
                        axes3[i, 0],
                    )
                    plot_duration_curves(
                        xaxis,
                        sort_wind,
                        ap_wind,
                        "Wind",
                        f"{prov_key} Wind Curve {year_key}",
                        axes3[i, 1],
                    )
                    plot_duration_curves(
                        xaxis,
                        sort_solar,
                        ap_solar,
                        "Solar",
                        f"{prov_key} Solar Curve {year_key}",
                        axes3[i, 2],
                    )
                fig3.savefig(
                    f"{saving_folder_path}Original_vs_Rep_{year_key}.png",
                    dpi=300,
                    bbox_inches="tight",
                )
                plt.close(fig3)

    # Finally, snapshots
    filename = "snapshots_" + str(Nrep) + "c_OPT"
    filename_csv = f"{filename}.csv"

    # For non-aggregate snapshots:
    if not aggregate:
        # Each year
        for year_key, prov_dict in year_opt.items():
            # Get the nonzero weights solution
            non_zero_weights = year_sol[year_key]["non_zero_weights"]
            # Send to timestamps function to update snapshots
            snap_df = get_timestamps(non_zero_weights, year_key, snap_df)
    # Now to save
    snap_df.to_csv(f"{saving_folder_path}{filename_csv}")
    #############################################

    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")

    if save_csv:
        snap_df.to_csv(f"{saving_folder_path}{filename_csv}")

    return snap_df
