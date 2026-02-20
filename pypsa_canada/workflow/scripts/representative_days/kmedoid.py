import math
import os
from collections import Counter

import numpy as np
import pandas as pd
import pypsa
from matplotlib import pyplot as plt
from scipy import stats
from sklearn_extra.cluster import KMedoids


def kmedoid_method(
    n: pypsa.Network(),
    nload_data: pd.DataFrame,
    rep_length: int = 14,
    cluster: int = 6,
    extreme_select: bool = False,
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
    nload_data : pd.DataFrame
        Net load demand calculated
    rep_length : int, optional
        Define the length of the representative period (Days), by default 14
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

    nload = nload_data.values
    rep_length = rep_length
    clusters = cluster

    # Make it a matrix
    hd = rep_length * 24
    match rep_length:
        case 1:
            nload = np.reshape(nload, (int(len(nload) / hd), hd))
        case 2:
            nload = np.reshape(nload[:-24], (int(len(nload) / hd), hd))
        case 3:
            nload = np.reshape(nload[:-48], (int(len(nload) / hd), hd))
        case 7:
            nload = np.reshape(nload[:-24], (int(len(nload) / hd), hd))
        case 14:
            nload = np.reshape(nload[:-24], (int(len(nload) / hd), hd))

    # Now the matrix is obtained, get clusters
    # Normalize data
    # print(f"nload.shape={nload.shape}")
    norma_load = stats.zscore(nload, axis=1)
    kmedoids = KMedoids(n_clusters=clusters).fit(norma_load)
    ctload = kmedoids.cluster_centers_  # Centroid center
    lbload = kmedoids.labels_  # Cluster label of the days
    idload = kmedoids.medoid_indices_  # Day of the year of the cluster centers
    occurrences = Counter(lbload)

    if extreme_select:
        # Dictionary to store indices for each label
        label_indices = {label: [] for label in set(lbload)}
        # Identify the indices for each label
        for index, label in enumerate(lbload):
            label_indices[label].append(index)
        # Iterate over each label
        for label, indices in label_indices.items():
            select_data = nload[indices]
            tot_load = np.sum(select_data, axis=1)
            ind_max = np.argmax(tot_load)
            ctload[label, :] = norma_load[indices[ind_max]]
            idload[label] = indices[ind_max]

    # print(occurrences)
    dcload = [
        np.where((norma_load == ctload[i, :]).all(1))[0] for i in range(len(ctload))
    ]

    # Now to save the files
    if extreme_select:
        filename = "snapshots_" + str(rep_length) + "d_" + str(clusters) + "c_extr"
    else:
        filename = "snapshots_" + str(rep_length) + "d_" + str(clusters) + "c"
    filename_csv = f"{filename}.csv"

    if save_fig:
        # Hours for plotting
        t = np.array(range(1, 24 * rep_length + 1))
        # Plot center and days
        plt.figure(dpi=1200)
        plt.subplots(math.ceil(len(ctload) / 2), 2)
        plt.suptitle("Clusters")
        for i in range(len(lbload)):
            plt.subplot(math.ceil(len(ctload) / 2), 2, lbload[i] + 1)
            plt.plot(t, nload[i, :].flatten(), "k", linewidth=0.5)
        for i in range(len(ctload)):
            plt.subplot(math.ceil(len(ctload) / 2), 2, i + 1)
            plt.plot(t, nload[dcload[i], :].flatten(), "r", linewidth=2)
        plt.savefig(f"{saving_folder_path}clusters_{filename}.png", dpi=1200)

    snapshot_weighting = n.snapshot_weightings.copy()
    snapshot_weighting[["objective", "stores", "generators"]] = 0.0  # Use float to allow decimal weights
    snapshot_weighting["idx"] = range(len(snapshot_weighting))

    # Now set the weights to the clusters associated with their occurrences
    for i, idx in enumerate(idload):
        mask = snapshot_weighting["idx"].between(
            hd * idx, hd * idx + hd, inclusive="left"
        )
        snapshot_weighting.loc[mask, ["objective", "stores", "generators"]] = (
            occurrences[i]
        )

    # snapshot_v2 = snapshot_weighting.copy()
    snapshot_weighting.drop("idx", axis=1, inplace=True)

    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")

    if save_csv:
        snapshot_weighting.to_csv(f"{saving_folder_path}{filename_csv}")

    return snapshot_weighting

    # snapshot_v2[['objective','stores', 'generators']] = 0

    # for i, idx in enumerate(idload):
    #     print(f'i={i}, idx={idx}')
    #     for j in range(len(snapshot_v2)):
    #         if j in range(hd*idx, hd*idx+hd):
    #             #print(f'index_inside={index} and occ = {occurrences[i]}')
    #             print(f'Saved for index = {index} and occ = {occurrences[i]}')
    #             snapshot_v2.iloc[j] = occurrences[i]
    #     #mask = (snapshot_weighting['idx'] in range(hd*idx, hd*idx+hd))

    # snapshot_v2.drop('idx', axis=1, inplace=True)
    # snapshot_v2.to_csv('./snapshots_rep_days_2.csv')
