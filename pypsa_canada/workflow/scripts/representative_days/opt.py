import os

import linopy as lp
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa
import xarray as xr


def opt_method(
    n: pypsa.Network(),
    nload_data: pd.DataFrame,
    bin: int = 12,
    solver: str = "cbc",
    mip_gap: float = 0.01,
    save_fig: bool = True,
    save_csv: bool = False,
    saving_folder_path="./",
):
    # Load net load
    nload = nload_data.values

    # Change it to a table
    nload = np.reshape(nload, (int(len(nload) / 24), 24))

    # Flatten the data into a 1D array
    flattened_data = nload.flatten()

    # Sort the flattened data in descending order
    sorted_data = np.sort(flattened_data)[::-1]
    sort_norm = sorted_data / max(sorted_data)

    # Calculate the duration curve
    duration_curve = np.linspace(0, 100, len(sort_norm))

    # Divide the duration curve into 10 bins
    num_bins = bin
    bin_edges = np.linspace(min(sort_norm), 1, num_bins + 1)
    # bin_indices = np.digitize(sort_norm, bin_edges)
    # Delete the last bin edge
    bin_edges = bin_edges[:-1]
    bin_edges = bin_edges[::-1]

    # Find the values corresponding to the bin edges
    index = []
    for edge in bin_edges:
        indices = np.where(sort_norm <= edge)[0]
        index.append(indices[0])

    # Plot the bins
    per_bin = duration_curve[index] / 100

    if save_fig:
        # Plot the duration curve
        plt.plot(duration_curve, sort_norm, label="Duration Curve")

        plt.scatter(per_bin * 100, np.array(bin_edges), c="red", label="Bins")
        plt.xlabel("Percentage of Data (%)")
        plt.ylabel("Load")
        plt.title("Duration Curve")
        plt.xlim(0, 100)
        plt.ylim(0, 1)
        plt.grid(True)
        plt.legend()
        plt.savefig(
            f"{saving_folder_path}Dur_curve_bins.png", dpi=300, bbox_inches="tight"
        )
        plt.clf()

    # Now to determine parameter A
    A = np.empty((num_bins, 365))
    # First normalize net load data
    load_norm = nload / max(sorted_data)

    # Now to go over the days
    for i, edge in enumerate(bin_edges):
        A[i, :] = np.sum(load_norm >= edge, axis=1) / 24

    if save_fig:
        plt.imshow(A, cmap="jet", aspect="auto")
        plt.colorbar()
        plt.xlabel("Days")
        plt.ylabel("Bins")
        plt.savefig(
            f"{saving_folder_path}A_param_map.png", dpi=300, bbox_inches="tight"
        )
        plt.clf()

    # Now the next step is the optimization model
    # Start with parameters
    Nrep = num_bins
    Ntot = 365

    # Create sets
    d_values = range(1, 366)  # Days
    b_values = range(1, num_bins + 1)  # Bins

    # Create coordinates
    d_coord = pd.Index(d_values, name="days")
    b_coord = pd.Index(b_values, name="bins")

    # Make A and L parameters with their corresponding sets
    # A = pd.DataFrame(A, index=b_coord, columns=d_coord)
    L = pd.Series({b: per_bin[b - 1] for b in b_values})

    # Convert to xarray
    A = xr.DataArray(A, coords=[b_coord, d_coord])
    L = xr.DataArray(L, coords=[b_coord])

    # Create the optimization model
    model = lp.Model()

    # Define the decision variables
    u = model.add_variables(coords=[d_coord], binary=True, name="u")
    w = model.add_variables(lower=0, coords=[d_coord], name="w")

    # Define the auxiliary variable
    y = model.add_variables(coords=[b_coord], name="y")

    # Define the objective function
    model.add_objective(y.sum())

    # Define the constraints
    # A is a matrix and w a vector, linopy does not multiply
    # a matrix and vector in a conventional way (At least not for now)
    Aw = A * w / Ntot
    # Aw is a matrix of dimension [num_bins, num_days], it is each element
    # of A multiplied with each element of w

    # Now, as a separate expression, the difference between L and Aw
    # L is seen as an np array, have to be converted to an expression to
    # avoid errors
    L_exp = lp.LinearExpression(L, model=model)
    dif_exp = L_exp - Aw.sum("days")

    # Now just have to sum Aw in the days column
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
    if solver == "cplex":
        solver_options = {"mip.tolerances.mipgap": mip_gap, "randomseed": 123}
    elif solver == "highs":
        solver_options = {"mip_rel_gap": mip_gap, "random_seed": 123}

    model.solve(solver_name=solver, **solver_options)

    # Print the optimal objective value
    # print("Optimal Objective Value:", model.solution())

    # Access the optimal values of decision variables
    # optimal_u = u.solution
    optimal_w = w.solution

    # Now to get the non-zero positions
    def non_zer(x):
        non_zero_mask = x != 0
        ind = np.where(non_zero_mask)[0]
        val = x.values[non_zero_mask]
        result = list(zip(ind, val))
        return result

    # u_non0 = non_zer(optimal_u)
    w_non0 = non_zer(optimal_w)
    #########################################
    # To view how solution is presented
    # test = 'model_report.txt'
    # filepath = os.path.join(saving_folder_path,test)
    # with open(filepath, 'w', encoding='utf-8') as file:
    # file.write(str(con1))
    # file.write('\n')
    # file.write(str(con2))
    # file.write('\n')
    # file.write(str(y.solution))
    # file.write('\n')
    # file.write(str(optimal_w))
    # file.write('\n')
    # file.write(str(w_non0))
    # file.write('\n')
    #     file.write(str(model))
    #     file.write('\n')
    #     file.write(str(model.objective_value))
    #     file.write('\n')
    #     file.write(solver)
    #########################################

    # Separate the integer part of the weights from the residue to estimate
    # the energy from the residues, for a more accurate duration curve
    rep_load = []
    residue = []  # Vector to save residue
    res_data = [0] * len(load_norm[0, :])  # Vector to estimate residual data
    for w in w_non0:
        row = load_norm[w[0], :]
        int_part = int(w[1])
        res_part = w[1] - int_part
        repel = [elem for elem in row for _ in range(int_part)]
        rep_load.extend(repel)
        res_data += res_part * row  # Right now this will be the total hourly energy
        residue.append(res_part)
    sum_res = sum(residue)
    res_data = res_data / sum_res  # Now I have the average vector for the residual
    test = "residue.txt"
    filepath = os.path.join(saving_folder_path, test)
    with open(filepath, "w", encoding="utf-8") as file:
        file.write(str(sum_res))
        file.write("\n")
        file.write(str(res_data))
        file.write("\n")
    repel = [elem for elem in res_data for _ in range(round(sum_res))]
    rep_load.extend(repel)
    sort_rep = np.sort(rep_load)[::-1]

    if save_fig:
        # Plot the duration curve
        plt.plot(duration_curve, sort_norm, "b", label="Original")
        plt.plot(duration_curve, sort_rep, "r", label="Representative")
        plt.xlabel("Percentage of Data (%)")
        plt.ylabel("Load")
        plt.title("Duration Curve")
        plt.xlim(0, 100)
        plt.ylim(0, 1)
        plt.legend()
        plt.grid(True)
        plt.savefig(
            f"{saving_folder_path}Orig_vs_rep.png", dpi=300, bbox_inches="tight"
        )
        plt.clf()

    snapshot_weighting = n.snapshot_weightings.copy()
    snapshot_weighting[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    snapshot_weighting["idx"] = range(len(snapshot_weighting))

    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")

    # Now to save the files
    filename = "snapshots_1d_" + str(Nrep) + "c_OPT"
    filename_csv = f"{filename}.csv"

    for index, value in w_non0:
        mask = snapshot_weighting["idx"].between(
            24 * index, 24 * index + 24, inclusive="left"
        )
        snapshot_weighting.loc[mask, ["objective", "stores", "generators"]] = value

    snapshot_weighting.drop("idx", axis=1, inplace=True)

    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")

    if save_csv:
        print(f"Saving: {saving_folder_path}{filename_csv}")
        snapshot_weighting.to_csv(f"{saving_folder_path}{filename_csv}")

    # raise RuntimeError("Stopping execution at this point!")

    return snapshot_weighting
    # # Just save the file now
    # # Open the CSV file in write mode
    # with open(file_name, "w", newline="") as file:
    #     # Create a CSV writer object
    #     writer = csv.writer(file)

    #     # Write the modified rows back to the CSV file
    #     writer.writerows(rows)
