import math
import os
from collections import Counter

import numpy as np
import pandas as pd
import pypsa
from matplotlib import pyplot as plt
from sklearn_extra.cluster import KMedoids


def vre_method(
    n: pypsa.Network(),
    # nload_data: pd.DataFrame,
    # rep_length:int=1,
    cluster: int = 6,
    # extreme_select:bool=False,
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
    def daily_prof(data, hd):
        output = np.reshape(data, (int(len(data) / hd), hd))
        return output

    # Load generators.csv
    gen_df = n.df("Generator")
    # Load generators-p_max_pu.csv
    gen_max_df = n.generators_t.p_max_pu.copy()
    if gen_max_df.shape[0] > 8760:
        gen_max_df = gen_max_df.iloc[0:8760, :]

    # RES list
    RES = ["wind", "solar"]

    # Rename RES sources in 'model' column
    # def rename_model(model):
    #     for res in RES:
    #         if res in model:
    #             return res
    #     return model
    # gen_df['model'] = gen_df['model'].apply(rename_model)
    # Filter generators
    filter_gen_df = gen_df[gen_df["carrier"].isin(RES)]
    # Now to get the average of each renewable
    RES_cf = pd.DataFrame(columns=RES)
    for res in RES:
        # Get current RES generators
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
    # At this point I have a DataFrame of dimension (8760 x 2) for RES

    # Load loads-p_set.csv
    load_df = n.loads_t.p_set.copy()
    # Load sum
    load_agg = load_df.sum(axis=1)
    load_agg = load_agg.to_frame()
    # Check if load dimension is greater than 8760
    if load_agg.shape[0] > 8760:
        load_agg = load_agg.iloc[0:8760, :]
    # Now to reshape the load to (number of days x 24)
    hd = 24
    # load_agg = np.reshape(load_agg, (int(len(load_agg)/hd), hd))
    load_agg = daily_prof(load_agg, hd)
    # Normalize using min-max normalization to keep all values between [0, 1]
    # norma_load = stats.zscore(load_agg, axis=1)
    load_min = np.min(load_agg)
    load_max = np.max(load_agg)
    norma_load = (load_agg - load_min) / (load_max - load_min)
    # Now the load is all in the range [0,1] just like the RES

    # Now reshape the solar and wind to (number of days x 24)
    solar = daily_prof(RES_cf["solar"], hd)
    wind = daily_prof(RES_cf["wind"], hd)

    # Now aggregate and have the input for the k-medoid
    k_input = np.concatenate((norma_load, wind, solar), axis=1)

    # Now the k-medoid
    clusters = cluster
    kmedoids = KMedoids(n_clusters=clusters).fit(k_input)
    ctload = kmedoids.cluster_centers_  # Centroid center
    lbload = kmedoids.labels_  # Cluster label of the days
    idload = kmedoids.medoid_indices_  # Day of the year of the cluster centers
    occurrences = Counter(lbload)

    # Now to print the results
    # Indices where the centroids are located in the input data
    dcload = [np.where((k_input == ctload[i, :]).all(1))[0] for i in range(len(ctload))]

    # File name to save
    filename = "snapshots_" + str(clusters) + "c"
    filename_csv = f"{filename}.csv"

    if save_fig:
        # Plot the clusters
        t = np.array(range(1, 73))
        # plt.figure(dpi=1200)
        plt.subplots(math.ceil(len(ctload) / 2), 2)
        plt.suptitle("Clusters")
        for i in range(len(lbload)):
            plt.subplot(math.ceil(len(ctload) / 2), 2, lbload[i] + 1)
            plt.plot(t, k_input[i, :].flatten(), "k", linewidth=0.5)
        for i in range(len(ctload)):
            plt.subplot(math.ceil(len(ctload) / 2), 2, i + 1)
            plt.plot(t, k_input[dcload[i], :].flatten(), "r", linewidth=2)
        plt.savefig(f"{saving_folder_path}clusters_{filename}.png", dpi=1200)

    # Create snapshots df
    snap_df = n.snapshot_weightings.copy()
    snap_df[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    # Create index column
    snap_df["idx"] = range(len(snap_df))
    # Set the weights
    for i, idx in enumerate(idload):
        mask = snap_df["idx"].between(hd * idx, hd * idx + hd, inclusive="left")
        snap_df.loc[mask, ["objective", "stores", "generators"]] = occurrences[i]
    # Drop idx column
    snap_df.drop("idx", axis=1, inplace=True)

    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")
    with open(f"{saving_folder_path}check_csv.txt", "w") as f:
        f.write(f"Save to csv: {save_csv}\n")
    if save_csv:
        snap_df.to_csv(f"{saving_folder_path}{filename_csv}")

    return snap_df
