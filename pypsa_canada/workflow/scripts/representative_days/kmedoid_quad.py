import datetime
import math
import os
from collections import Counter

import numpy as np
import pandas as pd
import pypsa
from matplotlib import pyplot as plt
from sklearn_extra.cluster import KMedoids

RES = ["wind", "solar"]
HD = 24


def kmedoid_quad_method(
    n: pypsa.Network,
    provinces: list = None,
    year: int = None,
    cluster: int = 6,
    save_fig: bool = True,
    save_csv: bool = False,
    saving_folder_path="./",
):
    """

    Parameters
    ----------
    n : pypsa.Network
        Imported pypsa network
    provinces : list, optional
        List of provinces whose data (load, VRE) are to be used to generate representative days, by default None
    year : int, optional
        If year is None, it will run by period, else it will run by the year in the variable.
    clusters : int, optional
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
    if provinces is None:
        provinces = [None]
    snap_df = n.snapshot_weightings.copy()
    snap_df[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    filename = "snapshots_" + str(cluster) + "c"
    filename_csv = f"{filename}.csv"
    if year is not None:
        periods = [year]
    elif year is None:
        periods = np.unique(snap_df.index.get_level_values("period"))
    snap_df = create_snapshots(
        n=n,
        provinces=provinces,
        periods=periods,
        cluster=cluster,
        filename=filename,
        saving_folder_path=saving_folder_path,
        snap_df=snap_df,
        save_fig=save_fig,
        year=year,
    )

    snap_to_csv(saving_folder_path, save_csv, snap_df, filename_csv)
    return snap_df


def daily_prof(data, hd: int) -> np.ndarray:
    """
    Function to reshape a vector to (Number of days x 24)

    Parameters
    ----------
    data : array_like
        Vector
    hd : int
        Number of days

    Returns
    -------
    np.ndarray
    """
    output = np.reshape(data, (int(len(data) / hd), hd))
    return output


def load_generators(n: pypsa.Network) -> pd.DataFrame:
    """
    Load generators.csv from the network in parameter.

    Parameters
    ----------
    n : pypsa.Network
        The network to load generators.csv from.

    Returns
    -------
    pd.DataFrame
        Returns the dataframe representing the file generators.csv.
    """
    return n.df("Generator")


def load_generators_p_max_pu(n: pypsa.Network, period=None, year=None) -> pd.DataFrame:
    """
    Load generators-p_max_pu.csv from the network in parameter.

    Parameters
    ----------
    n : pypsa.Network
        The network to load generators-p_max_pu.csv from.

    period : int, optional
        Represents the year, by default None
    year : int, optional
        Represents a specific year, by default None.
        Needed for condition.

    Returns
    -------
    pd.DataFrame
        Returns the dataframe representing the file generators-p_max_pu.csv.
    """
    gen_max_df = n.generators_t.p_max_pu.copy()
    if year is None:
        gen_max_df = gen_max_df.loc[pd.IndexSlice[period, :], :]
    else:
        if gen_max_df.shape[0] > 8760:
            return gen_max_df.iloc[0:8760, :]
    return gen_max_df


def get_average_each_renewable(
    gen_df: pd.DataFrame, gen_max_df: pd.DataFrame, province: str = None
) -> pd.DataFrame:
    """
    Filter generators and get the average of each renewable.

    Parameters
    ----------
    gen_df : pd.DataFrame
        The dataframe to filter
    gen_max_df : pd.DataFrame
        The dataframe to take the names from
    province : str
        A province

    Returns
    -------
    pd.DataFrame
        Returns a dataframe of dimension (8760 x 2) for RES
    """
    if province is not None:
        filter_gen_df = gen_df[
            gen_df["carrier"].isin(RES)
            & (gen_df["bus"].str.split("_").str[0] == province)
        ]
    else:
        filter_gen_df = gen_df[gen_df["carrier"].isin(RES)]
    RES_cf = pd.DataFrame(columns=RES)
    for res in RES:
        current_res = filter_gen_df[
            filter_gen_df["carrier"].str.contains(res, case=False, na=False)
        ]
        current_res = current_res.reset_index()
        names = current_res["Generator"].tolist()
        RES_col = gen_max_df.loc[:, names]
        RES_cf[res] = RES_col.mean(axis=1)

    return RES_cf


def load_p_set(
    n: pypsa.Network, period: int = None, province: str = None, year: int = None
) -> pd.DataFrame:
    """
    Load loads-p_set.csv from the network.

    Parameters
    ----------
    n : pypsa.Network
        Network to load loads-p_set.csv from.
    period : int, optional
        Represents the year, by default None.
    province : str, optional
        Represent the province, by default None.
    year : int, optional
        Represents a specific year, by default None.
        Needed for condition.

    Returns
    -------
    pd.DataFrame
        returns a dataframe of the aggregated load.
    """
    load_df = n.loads_t.p_set.copy()
    if province is not None:
        load_df_filtered = load_df.loc[:, load_df.columns.str.startswith(province)]
        load_agg = load_df_filtered.sum(axis=1)
    else:
        load_agg = load_df.sum(axis=1)
    load_agg = load_agg.to_frame()

    if year is None:
        load_agg = load_agg.loc[pd.IndexSlice[period, :], :]
    else:
        if load_agg.shape[0] > 8760:
            load_agg = load_agg.iloc[0:8760, :]
    return load_agg


def load_by_run_river(
    n: pypsa.Network,
    gen_df: pd.DataFrame,
    gen_max_df: pd.DataFrame,
    load_agg: pd.DataFrame,
    province: str = None,
    period: int = None,
    year: int = None,
) -> pd.DataFrame:
    """
    Calculate load subtracted by run of river, filter columns based on hydro sources,
       hydro columns hourly capacity factor, multiply to get hydro hourly generation

    Parameters
    ----------
    n : pypsa.Network
        The network.
    gen_df : pd.DataFrame
        The dataframe to filter
    gen_max_df : pd.DataFrame
        The dataframe to take the names from
    load_agg : pd.DataFrame
        The aggregated load
    province : str, optional
        The province to get data, by default None
    period : int, optional
        The year, by default None
    year : int, optional
        Represents a specific year, by default None.
        Needed for condition.

    Returns
    -------
    pd.DataFrame
        Returning a dataframe that represent the net_load
    """
    if province is not None and year is None:
        filter_hydro = gen_df[
            (gen_df["model"] == "hydro_ror")
            & (gen_df["bus"].str.split("_").str[0] == province)
            & ((n.get_active_assets(c="Generator", investment_period=period)) == True)
        ]
    else:
        filter_hydro = gen_df[gen_df["carrier"].isin(["hydro"])]
    hydro_names = filter_hydro.index
    hydro_cols = gen_max_df.loc[:, hydro_names]
    for name in hydro_names:
        hydro_cols[name] *= filter_hydro[filter_hydro.index == name]["p_nom"].values[0]
    hydro_pow = hydro_cols.sum(axis=1)
    hydro_pow = hydro_pow.to_frame()
    hydro_pow.index = load_agg.index
    return load_agg - hydro_pow


def get_norma_load(net_load: pd.DataFrame, hd: int) -> pd.DataFrame:
    """
    Normalize using min-max normalization to keep all values between [0, 1]

    Parameters
    ----------
    net_load : pd.DataFrame
        The net load to normalize.
    hd : int
        Number of days

    Returns
    -------
    pd.DataFrame
        return a dataframe that the load is all in the range [0,1] just like the RES
    """
    net_load = daily_prof(net_load, hd)
    load_min = np.min(net_load)
    load_max = np.max(net_load)
    return (net_load - load_min) / (load_max - load_min)


def get_solar_wind(RES_cf: pd.DataFrame, hd: int, year: int = None) -> np.ndarray:
    """
    Reshapes the solar and wind to (number of days x 24 (hd))

    Parameters
    ----------
    RES_cf : pd.DataFrame
        Dataframe of dimension (8760 x 2) for RES
    hd : int
        Number of days
    year : int, optional
        Represents a specific year, by default None.
        Needed for condition.

    Returns
    -------
    np.ndarray
        returns two ndarray shaped like norma_load.
    """
    solar = daily_prof(RES_cf["solar"], hd)
    wind = daily_prof(RES_cf["wind"], hd)
    if year is None:
        solar_min = np.min(solar)
        solar_max = np.max(solar)
        wind_min = np.min(wind)
        wind_max = np.max(wind)
        solar = (solar - solar_min) / (solar_max - solar_min)
        wind = (wind - wind_min) / (wind_max - wind_min)
    return solar, wind


def get_k_input(
    norma_load: pd.DataFrame,
    solar: np.ndarray,
    wind: np.ndarray,
    k_input: np.ndarray,
    year: int = None,
) -> np.ndarray:
    """
    Aggregates the dataframes. (norma_load, solar, wind)
       To prepare for the input for the k-medoid

    Parameters
    ----------
    norma_load : pd.DataFrame
        A dataframe that the load is all in the range [0,1] just like the RES
    solar : np.ndarray
        Ndarray shaped like norma_load
    wind : np.ndarray
        Ndarray shaped like norma_load
    k_input : np.ndarray
        Ndarray empty or representing the output of the return of this function
    year : int, optional
        Represents a specific year, by default None.
        Needed for condition.

    Returns
    -------
    np.ndarray
        return a ndarray equals to the aggregation of the others arrays.
    """
    if year is None:
        if contains_nan(solar) and contains_nan(wind):
            k_input_prov = norma_load
        elif not np.all(wind):
            k_input_prov = np.concatenate((norma_load, solar), axis=1)
        elif not np.all(solar):
            k_input_prov = np.concatenate((norma_load, wind), axis=1)
        else:
            k_input_prov = np.concatenate((norma_load, wind, solar), axis=1)
        return np.concatenate((k_input, k_input_prov), axis=1)
    return np.concatenate((norma_load, wind, solar), axis=1)


def saving_figures(
    filename: str,
    k_input: np.ndarray,
    kmedoids: KMedoids,
    saving_folder_path: str,
    period: int = None,
):
    """
    Make plots of the clusters.

    Parameters
    ----------
    filename : str
        Name of the file
    k_input : np.ndarray
        Data to plot
    kmedoids : KMedoids

    saving_folder_path : str
        Path of the folder to save.
    period : int, optional
        Year, by default None
    """
    ctload = kmedoids.cluster_centers_
    lbload = kmedoids.labels_
    dcload = [np.where((k_input == ctload[i, :]).all(1))[0] for i in range(len(ctload))]
    if period is None:
        t = np.array(range(1, 73))
    else:
        t = np.array(range(1, k_input.shape[1] + 1))
    plt.subplots(math.ceil(len(ctload) / 2), 2)
    plt.suptitle("Clusters")
    for i in range(len(lbload)):
        plt.subplot(math.ceil(len(ctload) / 2), 2, lbload[i] + 1)
        plt.plot(t, k_input[i, :].flatten(), "k", linewidth=0.5)
    for i in range(len(ctload)):
        plt.subplot(math.ceil(len(ctload) / 2), 2, i + 1)
        plt.plot(t, k_input[dcload[i], :].flatten(), "r", linewidth=2)
    if period is not None:
        plt.savefig(f"{saving_folder_path}clusters_{filename}_{period}.png", dpi=1200)
    else:
        plt.savefig(f"{saving_folder_path}clusters_{filename}.png", dpi=1200)


def snap_df_period(
    period: int, snap_df: pd.DataFrame, kmedoids: KMedoids
) -> pd.DataFrame:
    """
    Fill in snapshots dataframe weights for the period

    Parameters
    ----------
    period : int
        Period to modify.
    snap_df : pd.DataFrame
        Dataframe of the snapshots to fill.
    kmedoids : KMedoids


    Returns
    -------
    pd.DataFrame
        The snapshots dataframe filled with weights.
    """
    idload = kmedoids.medoid_indices_
    occurrences = Counter(kmedoids.labels_)
    rep_day_dates = [
        datetime.date(period, 1, 1) + pd.Timedelta(days=int(day)) for day in idload
    ]

    for i in range(len(rep_day_dates)):
        snap_df.loc[
            (snap_df.index.get_level_values("period") == period)
            & (snap_df.index.get_level_values("timestep").date == rep_day_dates[i]),
            ["objective", "generators"],
        ] = occurrences[i]
        snap_df.loc[
            (snap_df.index.get_level_values("period") == period)
            & (snap_df.index.get_level_values("timestep").date == rep_day_dates[i]),
            "stores",
        ] = 1
    return snap_df


def snap_df_no_period(
    snap_df: pd.DataFrame, hd: int, kmedoids: KMedoids
) -> pd.DataFrame:
    """
    Fill in snapshots dataframe weights without period

    Parameters
    ----------
    snap_df : pd.DataFrame
        Dataframe of the snapshots to fill.
    hd : int
        Numbers of days.
    kmedoids : KMedoids

    Returns
    -------
    pd.DataFrame
        The snapshots dataframe filled with weights.
    """
    idload = kmedoids.medoid_indices_
    occurrences = Counter(kmedoids.labels_)
    snap_df["idx"] = range(len(snap_df))
    for i, idx in enumerate(idload):
        mask = snap_df["idx"].between(hd * idx, hd * idx + hd, inclusive="left")
        snap_df.loc[mask, ["objective", "stores", "generators"]] = occurrences[i]
    snap_df.drop("idx", axis=1, inplace=True)

    return snap_df


def snap_to_csv(
    saving_folder_path: str, save_csv: bool, snap_df: pd.DataFrame, filename_csv: str
):
    """
    Creates a CSV from the snapshots dataframes.

    Parameters
    ----------
    saving_folder_path : str
        Path where the csv file will be saved.
    save_csv : bool
        Condition if the file will be saved or not.
    snap_df : pd.DataFrame
        The dataframe representing the snapshots to put into a csv file.
    filename_csv : str
        Name of the file
    """
    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")
    with open(f"{saving_folder_path}check_csv.txt", "w") as f:
        f.write(f"Save to csv: {save_csv}\n")
    if save_csv:
        snap_df.to_csv(f"{saving_folder_path}{filename_csv}")


def create_snapshots(
    n: pypsa.Network,
    provinces: list,
    periods: list,
    cluster: int,
    filename: str,
    saving_folder_path: str,
    snap_df: pd.DataFrame,
    save_fig: bool,
    year: int,
):
    """
    Creates snapshots with period and provinces.
       Assemble lots of function together.

    Parameters
    ----------
    n : pypsa.Network
        Network to create the k_inputs from.
    provinces : list
        List of the provinces to iterate from.
    periods : list
        List of the periods to iterate from.
    cluster : int

    filename : str
        Name of the file that will be created.
    saving_folder_path : str
        Path of the folder where the file will be saved.
    snap_df : pd.dataframe
        Dataframe of the snapshots
    year : int
        The specific year to represent the snapshots if one year only

    Returns
    -------
    pd.datraframe
        A dataframe representing the k_inputs with period and provinces from the network.
    """
    gen_df = load_generators(n)
    for period in periods:
        gen_max_df = load_generators_p_max_pu(n=n, period=period, year=year)
        k_input = np.empty((365, 0))
        for prov in provinces:
            RES_cf = get_average_each_renewable(
                gen_df=gen_df, gen_max_df=gen_max_df, province=prov
            )
            load_agg = load_p_set(n=n, period=period, province=prov, year=year)
            net_load = load_by_run_river(
                n=n,
                gen_df=gen_df,
                gen_max_df=gen_max_df,
                load_agg=load_agg,
                province=prov,
                period=period,
                year=year,
            )
            norma_load = get_norma_load(net_load=net_load, hd=HD)
            solar, wind = get_solar_wind(RES_cf=RES_cf, hd=HD, year=year)
            k_input = get_k_input(
                norma_load=norma_load,
                solar=solar,
                wind=wind,
                k_input=k_input,
                year=year,
            )
        kmedoids = KMedoids(n_clusters=cluster).fit(k_input)
        if year is None:
            snap_df = snap_df_period(snap_df=snap_df, period=period, kmedoids=kmedoids)
        elif year is not None:
            snap_df = snap_df_no_period(snap_df=snap_df, hd=HD, kmedoids=kmedoids)
        if save_fig:
            saving_figures(
                filename=filename,
                k_input=k_input,
                kmedoids=kmedoids,
                saving_folder_path=saving_folder_path,
                period=period,
            )
    return snap_df


def contains_nan(array: list) -> bool:
    """
    Checks if the array contains a NaN.

    Parameters
    ----------
    array: list
        List containing items

    Returns
    -------
    bool
        True if it contains Nan.
    """
    for items in array:
        for item in items:
            if math.isnan(item):
                return True
    return False
