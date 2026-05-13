# ************************************************************************************************************************************
# *                                  ECCC Electricity and Combustion Division Representative Day Calculator                                     *
# ************************************************************************************************************************************

# NextGridClusterer class to identify representative days for capacity expansion models
# Written by Modelling and Analysis for Regulatory Support (MARS)
# A unit of Electricity and Combustion Division, Energy and Transport Directorate, Environmental Protection Branch
# Environment and Climate Change Canada
#
# For questions: pascal.lesage@ec.gc.ca

# ************************************************************************************************************************************

import calendar
import copy
import math
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

# import seaborn as sns
from scipy import sparse
from sklearn.cluster import AgglomerativeClustering

# from utils.basic_validators import validate_dir_exists #SP edit: commenting out because I couldn't locate this package


def month_and_day_from_year_day(day, year=2021):
    """
    Small helper function that returns a string calendar date from day number

    Parameters
    ----------
    day: int
        Day index, e.g. Jan. 1 = 0
    year: int, default=2021
        Default of 2021 chosen because it is not a leap year
    """
    date = datetime(year, 1, 1) + timedelta(day)
    return f"{calendar.month_abbr[date.month]} {date.day}"


class NextGridClusterer:
    """
    Used to generate clusters of similar days and representative days for each cluster.

    Implements approach detailed in Nahmmacher, Paul, Eva Schmid, Lion Hirth, and Brigitte Knopf. 2016.
    “Carpe Diem: A Novel Approach to Select Representative Days for Long-Term Power System Modeling.”
    Energy 112 (October): 430–42. https://doi.org/10.1016/j.energy.2016.06.081.

    Note that you must generate the following inputs to use this class:
        all_arrs: np.array of shape 365d * (24h * 10 provinces * time_series_types).
            Values are normalized as per approach described in paper, i.e. across all provinces for pv, wind, and hydro
            and per province for load and usLoad.
        s_dict: dict indicating the column in all_arrs where a specific time series starts,
            keys are of the format time_series_types_province, e.g., pv_ON.
        norm_factor_dict: dict providing the normalization factor for each time series, with keys identical to
            those in s_dict.

    Attributes
    ----------
    todo list attributes

    Methods
    -------
    __init__(self, all_arrs, s_dict, norm_factor_dict, provinces, weight_dict, time_series_types, n_clusters=12, contiguous_days=False)
        Initializes the clusterer with input arrays and configuration.
    get_connectivity_matrix(self, contiguous_days)
        Generates a connectivity matrix for clustering, enforcing contiguous days if specified.
    fit(self)
        Clusters days into specified number of groups, computes representative days, and scales output data.
    get_representative_array(self, time_series_type, province, cluster_id, weight_dict, spatial_id)
        Returns the time series for the representative day, scaled back to the original range.
    save_representative_day_to_csv(self, time_series_type, province, cluster_id, save_dir, weight_dict, spatial_id=None)
        Exports the representative day data for a specified cluster to CSV.
    save_all_representative_days_to_csv(self, time_series_type, save_dir, weight_dict)
        Saves all representative days for a time series type to CSV files in the specified directory.
    save_ordered_cluster_package(self, save_dir, weight_dict, text_as_list=None, save_time_series=True)
        Saves a comprehensive package of cluster data, including metadata and time series information.
    calculate_r2(self)
        Computes R² values comparing original data with representative days for each time series.
    """

    def __init__(
        self,
        all_arrs,
        s_dict,
        norm_factor_dict,
        provinces,
        weight_dict,
        time_series_types,
        n_clusters=12,
        contiguous_days=False,
    ):
        """
        Initialize the NextGridClusterer with time series data, metadata, and clustering configuration.

        Parameters
        ----------
        all_arrs : np.array
            Array of shape 365d * (24h * 10 provinces * time_series_types), normalized as described in the reference paper.
        s_dict : dict
            Dictionary indicating the start columns of each time series in all_arrs. Keys are the name of arrays ({time_series_type}_{province}),
            values are the column numbers starting that array of 24 * 365
        norm_factor_dict : dict
            Dictionary of normalization factors for each time series array. Keys are the name of arrays ({time_series_type}_{province}),
            values are normalization factors for that array
        provinces : list
            List of province identifiers for time series data.
        weight_dict : dict
            Dictionary of weight values for each time series type. Keys are the name of arrays ({time_series_type}_{province}),
            values are exogenous weights to be given to those arrays in clustering
        time_series_types : list
            List of time series types (e.g., pv, wind as strings) to be included in clustering.
        n_clusters : int, optional
            The number of clusters to generate, default is 12.
        contiguous_days : bool, optional
            If True, clusters will contain contiguous days.
        """

        self.all_arrs = all_arrs
        self.norm_factor_dict = norm_factor_dict
        self.n_clusters = n_clusters
        self.contiguous_days = contiguous_days
        self.time_series_types = time_series_types
        self.provinces = provinces
        self.connectivity_matrix = self.get_connectivity_matrix(contiguous_days)
        self.s_dict = s_dict
        self.weight_dict = weight_dict

    def get_connectivity_matrix(self, contiguous_days):
        """
        Create a connectivity matrix enforcing contiguous days if specified.

        Parameters
        ----------
        contiguous_days : bool
            If True, enforce day-to-day connectivity in clustering.

        Returns
        -------
        sparse.csr_matrix or None
            Connectivity matrix for clustering if contiguous_days is True, else None.
        """

        if contiguous_days:
            days = [d for d in range(365)]
            connectivity_arr = np.zeros(shape=(365, 365))
            for i in days:
                connectivity_arr[days[i], days[i - 1]] = 1
                connectivity_arr[days[i - 1], days[i]] = 1
            return sparse.csr_matrix(connectivity_arr)
        else:
            return None

    def fit(self):
        """
        Cluster days, identify representative days for each cluster, and compute scaled representative arrays.

        Calculates Euclidean distance to find the most typical day in each cluster as the representative day.
        Adjusts representative day arrays to match the distribution of original data.

        Side Effects
        ------------
        Sets the following attributes:
            labels, day_to_cluster, cluster_to_day, n_days_in_cluster, dates_in_cluster, centroids, etc.
        """

        all_arrs_as_list = [self.all_arrs[i, :] for i in range(self.all_arrs.shape[0])]
        ward = AgglomerativeClustering(
            n_clusters=self.n_clusters,
            linkage="ward",
            connectivity=self.connectivity_matrix,
        ).fit(all_arrs_as_list)
        self.labels = ward.labels_
        self.day_to_cluster = {k: v for k, v in enumerate(self.labels)}
        self.cluster_to_day = defaultdict(list)
        for day, cluster in self.day_to_cluster.items():
            self.cluster_to_day[cluster].append(day)
        self.n_days_in_cluster = {}
        self.dates_in_cluster = {}
        self.representative_day_dict = {}
        self.representative_day_date_dict = {}
        self.centroids = {}
        self.arrs_in_cluster = {}
        for cluster_id, days_in_cluster in self.cluster_to_day.items():
            self.n_days_in_cluster[cluster_id] = len(self.cluster_to_day[cluster_id])
            self.dates_in_cluster[cluster_id] = [
                month_and_day_from_year_day(x) for x in days_in_cluster
            ]
            self.arrs_in_cluster[cluster_id] = np.concatenate(
                [all_arrs_as_list[i].reshape(1, -1) for i in days_in_cluster], axis=0
            )
            # centroid
            Vc = (
                self.arrs_in_cluster[cluster_id].sum(axis=0).reshape(1, -1)
                / self.arrs_in_cluster[cluster_id].shape[0]
            )
            self.centroids[cluster_id] = Vc
            euclidian_distances = [
                np.sqrt(np.sum(np.square(self.arrs_in_cluster[cluster_id][i, :] - Vc)))
                for i in range(self.arrs_in_cluster[cluster_id].shape[0])
            ]
            rep_arr_idx = np.argmin(euclidian_distances)
            self.representative_day_dict[cluster_id] = days_in_cluster[rep_arr_idx]
            self.representative_day_date_dict[cluster_id] = month_and_day_from_year_day(
                self.representative_day_dict[cluster_id]
            )
        self.representative_day_arr = np.concatenate(
            [
                self.all_arrs[self.representative_day_dict[i], :].reshape(1, -1)
                for i in range(len(self.representative_day_dict))
            ],
            axis=0,
        )
        self.initial_representative_day_arr = copy.deepcopy(self.representative_day_arr)
        self.rep_day_weights = np.array(
            [
                self.n_days_in_cluster.get(i, 0)
                for i in range(len(self.representative_day_dict))
            ]
        ).reshape(-1, 1)
        for key in [key for key in self.s_dict.keys() if "market" not in key]:
            start_col = self.s_dict[key]
            end_col = start_col + 24
            numerator = np.sum(self.all_arrs[:, start_col:end_col])
            denominator = np.sum(
                self.rep_day_weights * self.representative_day_arr[:, start_col:end_col]
            )
            if denominator == 0.0:
                continue
            scaling = numerator / denominator
            while not math.isclose(scaling, 1, rel_tol=0.0001):
                self.representative_day_arr[:, start_col:end_col] = (
                    self.representative_day_arr[:, start_col:end_col] * scaling
                )
                self.representative_day_arr[:, start_col:end_col][
                    self.representative_day_arr[:, start_col:end_col] > 1
                ] = 1
                denominator = np.sum(
                    self.rep_day_weights
                    * self.representative_day_arr[:, start_col:end_col]
                )
                if denominator == 0:
                    break
                scaling = numerator / denominator

    def make_ldc_df(self, time_series_type):
        """
        Constructs a Load Duration Curve (LDC) DataFrame for a specified time series type.

        For each relevant province, this method generates two LDCs:
        one based on the original daily data, and one on the scaled representative days.
        Both LDCs are sorted in descending order of magnitude to allow direct comparison
        across hours. These LDCs are then stored in the `ldc_df` attribute for future use.

        Parameters
        ----------
        time_series_type : str
            The type of time series to generate LDCs for (e.g., "pv", "wind").

        Raises
        ------
        AssertionError
            If `time_series_type` is not a valid type in `self.time_series_types`.

        Notes
        -----
        The resulting DataFrames include columns for the time series type value, province,
        hour (in the range [0, 8760] for hourly data), and data type ("original data" or
        "representative day").

        """
        assert time_series_type in self.time_series_types
        dfs = []
        s_dict_relevant_keys = [
            k for k in self.s_dict.keys() if k.split("_")[0] == time_series_type
        ]
        for key in s_dict_relevant_keys:
            prov = key.split("_", 1)[1]
            # original data
            start_col = self.s_dict[key]
            end_col = start_col + 24
            data = self.all_arrs[:, start_col:end_col].reshape(-1, 1)
            df = pd.DataFrame(data=data, columns=[time_series_type])
            df["province"] = prov
            df.sort_values(time_series_type, inplace=True, ascending=False)
            df["hour"] = np.arange(8760)
            df["data"] = "original data"
            dfs.append(df)
            # scaled representative days
            scaled_rep_days = np.concatenate(
                [
                    np.repeat(
                        self.representative_day_arr[i, start_col:end_col],
                        self.rep_day_weights[i],
                    ).reshape(-1, 1)
                    for i in range(len(self.rep_day_weights))
                ],
                axis=0,
            )
            scaled_rep_days = np.sort(scaled_rep_days)[::-1]
            df = pd.DataFrame(data=scaled_rep_days, columns=[time_series_type])
            df.sort_values(time_series_type, inplace=True, ascending=False)
            df["hour"] = np.arange(8760)
            df["province"] = prov
            df["data"] = "representative day"
            dfs.append(df)
        if not hasattr(self, "ldc_df"):
            self.ldc_df = {}
        self.ldc_df[time_series_type] = pd.concat(dfs, axis=0, ignore_index=True)

    # def graph_ldc(self, time_series_type):
    #     """
    #     Plots Load Duration Curves (LDCs) for a specified time series type across provinces.

    #     This method retrieves or generates the LDC DataFrame for the specified time series type,
    #     then creates a line plot for each province, comparing the original and representative
    #     LDCs. The plot displays hourly values for each province and shows LDCs as separate
    #     series in each subplot.

    #     Parameters
    #     ----------
    #     time_series_type : str
    #         The type of time series for which to plot LDCs (e.g., "pv", "wind").

    #     Notes
    #     -----
    #     - The plot is a FacetGrid, showing separate subplots for each province.
    #     - It includes a legend distinguishing between "original data" and
    #     "representative day".
    #     - The number of clusters and whether they are contiguous are included in the
    #     plot title for context.

    #     """
    #     if not hasattr(self, "ldc_df") or time_series_type not in self.ldc_df:
    #         self.make_ldc_df(time_series_type)
    #     g = sns.FacetGrid(
    #         data=self.ldc_df[time_series_type], col="province", height=2.5, col_wrap=5
    #     )
    #     g.map(
    #         sns.lineplot,
    #         "hour",
    #         time_series_type,
    #         "data",
    #         estimator=None,
    #         palette=["gray", "black"],
    #     )
    #     g.fig.subplots_adjust(top=0.8)
    #     g.fig.suptitle(
    #         "Normalized LCD curves for {} with {} clusters.\nDays in cluster {} contiguous".format(
    #             time_series_type,
    #             self.n_clusters,
    #             "" if self.contiguous_days else "not necessarily",
    #         )
    #     )
    #     g.add_legend()

    def get_representative_array(
        self, time_series_type, province, cluster_id, weight_dict, spatial_id
    ):
        """
        Retrieve and rescale the representative day time series for a given cluster.

        Parameters
        ----------
        time_series_type : str
            Type of time series (e.g., pv, wind).
        province : str
            Province code.
        cluster_id : int
            Cluster identifier.
        weight_dict : dict
            Dictionary of weight values for each time series type.
        spatial_id : str or None
            Identifier for specific spatial location if available.

        Returns
        -------
        np.array
            Rescaled time series data for the representative day.
        """

        assert time_series_type in self.time_series_types
        # assert province in self.provinces
        assert cluster_id < self.n_clusters
        if spatial_id is None:
            key = f"{time_series_type}_{province}"
        else:
            key = f"{time_series_type}_{province}_{spatial_id}"
        start_col = self.s_dict[key]
        end_col = start_col + 24
        norm_factor_min = self.norm_factor_dict[key][0]
        norm_factor_max = self.norm_factor_dict[key][1]

        rep_arr = (
            (
                self.representative_day_arr[cluster_id, start_col:end_col]
                * (norm_factor_max - norm_factor_min)
            )
            / weight_dict[time_series_type]
            + norm_factor_min
        ).reshape(-1, 1)
        if time_series_type in ["pv", "wind"]:
            # Clip values in rep_arr to be between 0 and 1
            rep_arr = np.clip(rep_arr, 0, 1)

        return rep_arr

    def save_representative_day_to_csv(
        self,
        time_series_type,
        province,
        cluster_id,
        save_dir,
        weight_dict,
        spatial_id=None,
    ):
        """
        Save the representative day's time series data to CSV.

        Parameters
        ----------
        time_series_type : str
            Type of time series (e.g., pv, wind).
        province : str
            Province code.
        cluster_id : int
            Cluster identifier.
        save_dir : Path
            Directory path to save the CSV file.
        weight_dict : dict
            Dictionary of weight values for each time series type.
        spatial_id : str or None, optional
            Identifier for specific spatial location if available.
        """
        # save_dir = validate_dir_exists(save_dir)
        arr = self.get_representative_array(
            time_series_type, province, cluster_id, weight_dict, spatial_id
        )
        df = pd.DataFrame(
            data=np.concatenate([arr, np.arange(arr.size).reshape(-1, 1)], axis=1),
            columns=[time_series_type, "hour"],
        )
        if spatial_id is None:
            df.to_csv(
                save_dir / f"{time_series_type}_{province}_{cluster_id}.csv",
                index=False,
            )
        else:
            df.to_csv(
                save_dir
                / f"{time_series_type}_{province}_{spatial_id}_{cluster_id}.csv",
                index=False,
            )

    def save_all_representative_days_to_csv(
        self, time_series_type, save_dir, weight_dict
    ):
        """
        Save time series data for all representative days to CSV files.

        Parameters
        ----------
        time_series_type : str
            Type of time series to save.
        save_dir : Path
            Directory path for saving CSV files.
        weight_dict : dict
            Dictionary of weight values for each time series type.
        """
        s_dict_relevant_keys = [
            k for k in self.s_dict.keys() if k.split("_")[0] == time_series_type
        ]
        for key in s_dict_relevant_keys:
            prov = key.split("_", 1)[1]
            for cluster_id in range(self.n_clusters):
                self.save_representative_day_to_csv(
                    time_series_type, prov, cluster_id, save_dir, weight_dict
                )

    def save_ordered_cluster_package(
        self, save_dir, weight_dict, text_as_list=None, save_time_series=True
    ):
        """
        Save cluster information and data in a structured format.

        Parameters
        ----------
        save_dir : Path
            Directory path for saving package.
        weight_dict : dict
            Dictionary of weight values for each time series type.
        text_as_list : list of str, optional
            Additional text information to include in package.
        save_time_series : bool, optional
            If True, save time series data for each representative day.
        """

        csv_with_day_to_cluster_map = "day_to_cluster_map.csv"
        csv_with_cluster_weights = "cluster_weight.csv"
        csv_with_representative_day_indices = "cluster_representative_day_index.csv"
        txt_with_dates_in_cluster = "dates_in_cluster.txt"

        day_to_cluster_id_df = pd.Series(self.day_to_cluster).to_frame()
        day_to_cluster_id_df.reset_index(inplace=True)
        day_to_cluster_id_df.columns = ["day", "cluster_id"]
        day_to_cluster_id_df.to_csv(save_dir / csv_with_day_to_cluster_map, index=False)

        n_days_in_cluster_df = pd.Series(self.n_days_in_cluster).to_frame()
        n_days_in_cluster_df.reset_index(inplace=True)
        n_days_in_cluster_df.columns = ["cluster_id", "weight"]
        n_days_in_cluster_df.to_csv(save_dir / csv_with_cluster_weights, index=False)

        csv_with_representative_day_indices_df = pd.Series(
            self.representative_day_dict
        ).to_frame()
        csv_with_representative_day_indices_df.reset_index(inplace=True)
        csv_with_representative_day_indices_df.columns = ["cluster_id", "day"]
        csv_with_representative_day_indices_df.to_csv(
            save_dir / csv_with_representative_day_indices, index=False
        )

        if save_time_series:
            pv_time_series_dir = save_dir / "pv"
            pv_time_series_dir.mkdir(exist_ok=True)
            wind_time_series_dir = save_dir / "wind"
            wind_time_series_dir.mkdir(exist_ok=True)
            load_time_series_dir = save_dir / "load"
            load_time_series_dir.mkdir(exist_ok=True)
            hydro_time_series_dir = save_dir / "hydro"
            hydro_time_series_dir.mkdir(exist_ok=True)
            us_load_time_series_dir = save_dir / "usLoad"
            us_load_time_series_dir.mkdir(exist_ok=True)
            market_time_series_dir = save_dir / "market"
            market_time_series_dir.mkdir(exist_ok=True)
            self.save_all_representative_days_to_csv(
                weight_dict=weight_dict,
                time_series_type="load",
                save_dir=load_time_series_dir,
            )
            self.save_all_representative_days_to_csv(
                weight_dict=weight_dict,
                time_series_type="hydro",
                save_dir=hydro_time_series_dir,
            )
            self.save_all_representative_days_to_csv(
                weight_dict=weight_dict,
                time_series_type="usLoad",
                save_dir=us_load_time_series_dir,
            )
            self.save_all_representative_days_to_csv(
                weight_dict=weight_dict,
                time_series_type="pv",
                save_dir=pv_time_series_dir,
            )
            self.save_all_representative_days_to_csv(
                weight_dict=weight_dict,
                time_series_type="wind",
                save_dir=wind_time_series_dir,
            )
            self.save_all_representative_days_to_csv(
                weight_dict=weight_dict,
                time_series_type="market",
                save_dir=market_time_series_dir,
            )

        with open(save_dir / txt_with_dates_in_cluster, "w") as f:
            for cluster_id in range(self.n_clusters):
                f.write(f"\n\ncluster_id: {cluster_id}")
                for day in self.dates_in_cluster[cluster_id]:
                    f.write(f"\n\t{day}")
        with open(save_dir / "readme.txt", "a") as f:
            if text_as_list:
                f.writelines("\n".join(text_as_list))
            f.writelines(
                "\n".join(
                    [
                        "",
                        "--------------------------------------------------------",
                        "Description",
                        f"\tNumber of clusters: {self.n_clusters}",
                        "\tContiguous dates in clusters: {}".format(
                            "Yes" if self.connectivity_matrix else "No"
                        ),
                        f"\tRepresentative days chosen for each cluster: {csv_with_day_to_cluster_map}",
                        f"\tMap of days to cluster id: {csv_with_day_to_cluster_map}",
                        f"\tCluster weight: {csv_with_cluster_weights}",
                        f"\tDates in cluster: {txt_with_dates_in_cluster}",
                        f"\tRepresentative PV time series: {pv_time_series_dir}",
                        f"\tRepresentative wind time series: {wind_time_series_dir}",
                        f"\tRepresentative load time series: {load_time_series_dir}",
                    ]
                )
            )

    def calculate_r2(self):
        """
        Compute R² values for each time series, comparing original data with representative days.

        Side Effects
        ------------
        Sets r2_dict attribute with R² values for each time series.
        """
        if not hasattr(self, "r2_dict"):
            self.r2_dict = {}
            for key in self.s_dict.keys():
                time_series_type = key.split("_")[0]
                # original_data
                start_col = self.s_dict[key]
                end_col = start_col + 24
                data = self.all_arrs[:, start_col:end_col].reshape(-1, 1)
                df = pd.DataFrame(data=data, columns=[time_series_type])
                original_array = df[time_series_type].values
                # scaled representative days
                scaled_rep_days = np.concatenate(
                    [
                        self.representative_day_arr[
                            self.day_to_cluster[i], start_col:end_col
                        ].reshape(-1, 1)
                        for i in range(365)
                    ],
                    axis=0,
                )
                df = pd.DataFrame(data=scaled_rep_days, columns=[time_series_type])
                rep_days_array = df[time_series_type].values
                # calculate r2
                r2 = np.corrcoef(original_array, rep_days_array)[0, 1]
                self.r2_dict[key] = r2
