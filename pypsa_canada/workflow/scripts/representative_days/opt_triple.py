import os

import linopy as lp
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa
import xarray as xr


def opt3_method(
    n: pypsa.Network(),
    # nload_data: pd.DataFrame,
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
    rep_length : int, optional
        Define the length of the representative period (Days), by default 1
    cluster : int, optional
        Number of clusters, by default 6
    extreme_select : bool, optional
        Extreme day selection, by default False
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

    # Load generators.csv
    gen_df = n.df("Generator")
    # Load generators-p_max_pu.csv
    gen_max_df = n.generators_t.p_max_pu.copy()
    if gen_max_df.shape[0] > 8760:
        gen_max_df = gen_max_df.iloc[0:8760, :]
    # Load loads-p_set.csv
    load_df = n.loads_t.p_set.copy()
    # Check if load dimension is greater than 8760
    if load_df.shape[0] > 8760:
        load_df = load_df.iloc[0:8760, :]
    # Load sum
    load = load_df.sum(axis=1).to_numpy()
    # print(load)

    # Identify wind and solar generators
    RES = ["wind", "solar"]
    filter_gen_df = gen_df[gen_df["carrier"].isin(RES)]

    # Calculate average capacity factor for each RES type
    # RES_cf = pd.DataFrame({res: gen_max_df.loc[:, filter_gen_df[filter_gen_df['carrier'] == res]].mean(axis=1) for res in RES})
    RES_cf = pd.DataFrame(columns=RES)
    for res in RES:
        # Get current RES gen
        current_res = filter_gen_df[
            filter_gen_df["carrier"].str.contains(res, case=False, na=False)
        ]
        # Extract the generators names
        current_res = current_res.reset_index()  # To avoid Generator being an index
        # Generators names
        names = current_res["Generator"].tolist()
        # Columns of the respective RES
        RES_col = gen_max_df.loc[:, names]
        # Now their average
        RES_cf[res] = RES_col.mean(axis=1)

    # Convert RES data to numpy arrays
    wind = RES_cf["wind"].to_numpy()
    solar = RES_cf["solar"].to_numpy()

    # Create sorted duration curves
    sort_load = np.sort(load)[::-1] / max(load)
    sort_wind = np.sort(wind)[::-1]
    sort_solar = np.sort(solar)[::-1]

    # Define x-axis for duration curves
    xaxis = np.linspace(0, 100, len(sort_load))

    # Define bins for representative days
    num_bins = bin
    rep_days = num_bins
    edge_load = trim_reverse(np.linspace(sort_load[-1], 1, num_bins + 1))
    edge_wind = trim_reverse(np.linspace(sort_wind[-1], 1, num_bins + 1))
    edge_solar = trim_reverse(np.linspace(sort_solar[-1], 1, num_bins + 1))

    # Get percentile values for bin edges
    per_load = get_percentile_values(sort_load, edge_load, xaxis)
    per_wind = get_percentile_values(sort_wind, edge_wind, xaxis)
    per_solar = get_percentile_values(sort_solar, edge_solar, xaxis)

    # Plot duration curves with bins
    if save_fig:
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        plot_duration_bins(
            xaxis, sort_load, per_load, edge_load, "Load", "Load Curve", axes[0]
        )
        plot_duration_bins(
            xaxis, sort_wind, per_wind, edge_wind, "Wind", "Wind Curve", axes[1]
        )
        plot_duration_bins(
            xaxis, sort_solar, per_solar, edge_solar, "Solar", "Solar Curve", axes[2]
        )
        plt.savefig(
            f"{saving_folder_path}Duration_curve.png", dpi=300, bbox_inches="tight"
        )
        plt.close()

    # Reshape for daily profiles
    hd = 24
    tab_load = daily_profile(load, hd) / max(load)
    tab_wind = daily_profile(wind, hd)
    tab_solar = daily_profile(solar, hd)

    # Build A matrices for load, wind, and solar
    A_load = build_A_matrix(np.empty((num_bins, len(tab_load))), tab_load, edge_load)
    A_wind = build_A_matrix(np.empty((num_bins, len(tab_wind))), tab_wind, edge_wind)
    A_solar = build_A_matrix(
        np.empty((num_bins, len(tab_solar))), tab_solar, edge_solar
    )

    # Plot A matrices
    if save_fig:
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        axes[0].imshow(A_load, cmap="jet", aspect="auto")
        axes[0].set_xlabel("Days")
        axes[0].set_ylabel("Bins")
        axes[0].set_title("Load")
        axes[1].imshow(A_wind, cmap="jet", aspect="auto")
        axes[1].set_xlabel("Days")
        axes[1].set_ylabel("Bins")
        axes[1].set_title("Wind")
        axes[2].imshow(A_solar, cmap="jet", aspect="auto")
        axes[2].set_xlabel("Days")
        axes[2].set_ylabel("Bins")
        axes[2].set_title("Solar")
        plt.savefig(
            f"{saving_folder_path}A_parameter.png", dpi=300, bbox_inches="tight"
        )
        plt.close()

    # Optimization setup
    Ntot = len(tab_load)
    Nrep = rep_days
    d_values = range(1, Ntot + 1)
    b_values = range(1, num_bins + 1)
    # Create coordinates
    d_coord = pd.Index(d_values, name="days")
    b_coord = pd.Index(b_values, name="bins")
    [Aopt_load, Lopt_load] = create_AL_sets(
        A_load, b_values, b_coord, d_coord, per_load
    )
    [Aopt_wind, Lopt_wind] = create_AL_sets(
        A_wind, b_values, b_coord, d_coord, per_wind
    )
    [Aopt_solar, Lopt_solar] = create_AL_sets(
        A_solar, b_values, b_coord, d_coord, per_solar
    )

    model = lp.Model()
    # model.d = pe.Set(initialize=d_values)
    # model.b = pe.Set(initialize=b_values)
    # Define the decision variables
    u = model.add_variables(coords=[d_coord], binary=True, name="u")
    w = model.add_variables(lower=0, coords=[d_coord], name="w")

    # Define the auxiliary variable
    y = model.add_variables(coords=[b_coord], name="y")

    # Define the objective function
    model.add_objective(y.sum())

    # Now to define constraints
    Aw = (Aopt_load + Aopt_wind + Aopt_solar) * w / Ntot  # Dim: [bins, days]
    L_tot = Lopt_load + Lopt_wind + Lopt_solar  # Dim: [bins]
    L_exp = lp.LinearExpression(L_tot, model=model)
    dif_exp = L_exp - Aw.sum("days")

    # Now the first set of constraints
    c1 = y >= dif_exp
    c2 = y >= -dif_exp
    model.add_constraints(c1)
    model.add_constraints(c2)
    # con1 = model.add_constraints(c1)
    # con2 = model.add_constraints(c2)

    model.add_constraints(w <= Ntot * u)

    # Additional constraints
    model.add_constraints(u.sum() == Nrep)
    model.add_constraints(w.sum() == Ntot)

    # Solve the optimization problem
    # Solve the optimization problem
    if solver == "cplex":
        solver_options = {"mip.tolerances.mipgap": mip_gap, "randomseed": 123}
    elif solver == "highs":
        solver_options = {"mip_rel_gap": mip_gap, "random_seed": 123}

    model.solve(solver_name=solver, **solver_options)

    # Access the optimal values of decision variables
    # optimal_u = u.solution
    optimal_w = w.solution

    # Extract non-zero weights
    non_zero_weights = get_non_zero_elements(optimal_w)

    # test = "model_report.txt"
    # filepath = os.path.join(saving_folder_path, test)
    # with open(filepath, "w", encoding="utf-8") as file:
    #     file.write(str(non_zero_weights))
    #     file.write("\n")

    # Create representative duration curves
    ap_load = create_representative_curve(tab_load, non_zero_weights)
    ap_wind = create_representative_curve(tab_wind, non_zero_weights)
    ap_solar = create_representative_curve(tab_solar, non_zero_weights)

    # Now to plot duration curves
    if save_fig:
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        plot_duration_curves(xaxis, sort_load, ap_load, "Load", "Load Curve", axes[0])
        plot_duration_curves(xaxis, sort_wind, ap_wind, "Wind", "Wind Curve", axes[1])
        plot_duration_curves(
            xaxis, sort_solar, ap_solar, "Solar", "Solar Curve", axes[2]
        )
        plt.savefig(
            f"{saving_folder_path}Original_vs_Representative.png",
            dpi=300,
            bbox_inches="tight",
        )
        plt.close()

    # Now to create snapshots
    filename = "snapshots_" + str(Nrep) + "c_OPT"
    filename_csv = f"{filename}.csv"
    # Create snapshots df
    snap_df = n.snapshot_weightings.copy()
    snap_df[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    # Create index column
    snap_df["idx"] = range(len(snap_df))
    # Set the weights

    for index, value in non_zero_weights:
        mask = snap_df["idx"].between(24 * index, 24 * index + 24, inclusive="left")
        snap_df.loc[mask, ["objective", "stores", "generators"]] = value
    # Drop idx column
    snap_df.drop("idx", axis=1, inplace=True)

    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")

    if save_csv:
        snap_df.to_csv(f"{saving_folder_path}{filename_csv}")

    return snap_df
