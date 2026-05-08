import datetime
import math

# import os
from collections import defaultdict

import numpy as np
import pandas as pd
import pypsa

# import pypsa_cad.preprocess.representative_days.carpe_diem.temporal_clustering_class as temporal_clustering_class
# import pypsa_cad.preprocess.representative_days.carpe_diem.temporal_clustering_class as temporal_clustering_class
import representative_days.temporal_clustering_class as temporal_clustering_class

# from matplotlib import pyplot as plt
# from sklearn_extra.cluster import KMedoids

RES_DICT = {
    "solar": "pv",
    "pv": "solar",
    "wind": "wind",
    "load": "load",
}

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
    gen_df = n.c["Generator"].static
    bus_df = n.c["Bus"].static
    gen_df['province'] = gen_df['bus'].map(bus_df['province'])
    return gen_df

def carpe_diem_method(n: pypsa.Network, provinces: list, clusters: int = 6):
    """
    _summary_

    Parameters
    ----------
    n : pypsa.Network
        Imported pypsa network
    provinces : list
        List of provinces whose data (load, VRE) are to be used to generate representative days
    clusters : int, optional
        Number of clusters, by default 6

    Returns
    -------
    pd.DataFrame
        Snapshot weighting dataframe
    """

    # Function to reshape a vector to (Number of days x 24)
    def daily_prof(data, hd):
        output = np.reshape(data, (int(len(data) / hd), hd))
        return output

    # RES list
    RES = ["wind", "solar"]

    time_series_types = ["load", "wind", "pv"]
    # List of time series types (e.g., pv, wind as strings) to be included in clustering. (Could make this an input if we intend to change it sometimes)

    # Load snapshots and obtain unique periods
    snap_df = n.snapshot_weightings.copy()
    snap_df[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    periods = np.unique(snap_df.index.get_level_values("period"))

    # Load generators.csv

    gen_df = load_generators(n)

    # # File name to save
    # if save_fig:
    #     filename = "snapshots_" + str(clusters)   + "c"
    #     filename_csv = f"{filename}.csv"

    # Load generators-p_max_pu.csv
    gen_max_df = n.generators_t.p_max_pu.copy()

    # Load loads-p_set.csv
    load_df = n.loads_t.p_set.copy()

    for period in periods:
        # Select the period (year) of interest. Will want to iterate over periods to choose rep days for each.
        gen_max_df_period = gen_max_df.loc[pd.IndexSlice[period, :], :]

        # Initialize numpy array with data used to generate representative days
        k_input = np.empty((365, 0))

        # Initialize a dictionary with minimum and maximum values used in normalizing load, wind and solar timeseries
        norm_factor_dict = defaultdict(lambda: defaultdict(list))

        for prov in provinces:
            # Filter generators
            filter_gen_df = gen_df[
                gen_df["carrier"].isin(RES)
                & (gen_df["province"] == prov)
            ]
            # Now to get the average of each renewable
            RES_cf = pd.DataFrame(columns=RES)
            used_res = ["load"]
            for res in RES:
                # Get current RES generators
                current_res = filter_gen_df[
                    filter_gen_df["carrier"].str.contains(res, case=False, na=False)
                ]
                # Extract the generators names
                current_res = (
                    current_res.reset_index()
                )  # To avoid Generator being an index
                # Generators names
                names = current_res["name"].tolist()
                if len(names) > 0:
                    # Columns of the respective RES
                    RES_col = gen_max_df_period.loc[:, names]
                    # Now their average
                    RES_cf[res] = RES_col.mean(axis=1)
                    used_res.append(res)
            # At this point I have a DataFrame of dimension (8760 x 2) for RES

            # Filter to relevant province
            load_df_filtered = load_df.loc[:, load_df.columns.str.startswith(prov)]
            # Load sum
            load_agg = load_df_filtered.sum(axis=1)
            load_agg = load_agg.to_frame()
            # Select the period of interest
            load_agg = load_agg.loc[pd.IndexSlice[period, :], :]

            ##########################################################
            # Calculate load subtracted by run of river
            filter_hydro = gen_df[
                (gen_df["model"] == "hydro_ror")
                & (gen_df["province"] == prov)
                & (
                    (n.get_active_assets(c="Generator", investment_period=period))
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
            ##########################################################

            # Now to reshape the load to (number of days x 24)
            hd = 24
            # load_agg = np.reshape(load_agg, (int(len(load_agg)/hd), hd))
            net_load = daily_prof(net_load, hd)

            # Normalize using min-max normalization to keep all values between [0, 1]
            # norma_load = stats.zscore(load_agg, axis=1)
            load_min = np.min(net_load)
            load_max = np.max(net_load)
            load_denom = load_max - load_min
            if load_denom == 0:
                norma_load = np.zeros_like(net_load, dtype=float)
            else:
                norma_load = (net_load - load_min) / load_denom
            # Now the load is all in the range [0,1] just like the RES

            if "solar" in used_res:
                # Now reshape the solar and wind to (number of days x 24)
                solar = daily_prof(RES_cf["solar"], hd)
                solar_min = np.min(solar)
                solar_max = np.max(solar)
                solar_denom = solar_max - solar_min
                if solar_denom == 0:
                    solar = np.zeros_like(solar, dtype=float)
                else:
                    solar = (solar - solar_min) / solar_denom

            if "wind" in used_res:
                wind = daily_prof(RES_cf["wind"], hd)
                # Normalize in the same way that the load was normalized (not crucial)
                wind_min = np.min(wind)
                wind_max = np.max(wind)
                wind_denom = wind_max - wind_min
                if wind_denom == 0:
                    wind = np.zeros_like(wind, dtype=float)
                else:
                    wind = (wind - wind_min) / wind_denom

            k_input_res = [norma_load]
            if "wind" in used_res:
                k_input_res.append(wind)
            if "solar" in used_res:
                k_input_res.append(solar)
            k_input_prov = np.concatenate(k_input_res, axis=1)
            # Now aggregate the different provinces and prepare input for k-medoid
            k_input = np.concatenate((k_input, k_input_prov), axis=1)

            norm_factor_dict[f"load_{prov}"][0] = load_min
            norm_factor_dict[f"load_{prov}"][1] = load_max
            if "wind" in used_res:
                norm_factor_dict[f"wind_{prov}"][0] = wind_min
                norm_factor_dict[f"wind_{prov}"][1] = wind_max
            if "solar" in used_res:
                norm_factor_dict[f"pv_{prov}"][0] = solar_min
                norm_factor_dict[f"pv_{prov}"][1] = solar_max

            # Dictionary of normalization factors for each time series array. Keys are the name of arrays ({time_series_type}_{province}),
            # values are normalization factors for that array

        # Now the ECCC carpe diem implementation
        s_dict = {}
        weight_dict = {}
        column_value = 0
        for prov in provinces:
            for type in time_series_types:
                if RES_DICT[type] in used_res:
                    s_dict[f"{type}_{prov}"] = column_value
                    column_value = column_value + hd

        for type in time_series_types:
            weight_dict[f"{type}"] = 1

        # from ipdb import set_trace; set_trace()

        clusterer = temporal_clustering_class.NextGridClusterer(
            all_arrs=k_input,
            s_dict=s_dict,
            norm_factor_dict=norm_factor_dict,
            provinces=provinces,
            weight_dict=weight_dict,
            time_series_types=time_series_types,
            n_clusters=clusters,
            contiguous_days=False,
        )
        clusterer.fit()

        rep_day_dates = [
            datetime.date(period, 1, 1) + pd.Timedelta(days=int(day))
            for day in clusterer.representative_day_dict.values()
        ]
        occurrences = [value for value in clusterer.n_days_in_cluster.values()]

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

        # Now compute new values of generator_p_max_pu with rescalings applied such that weighted average over rep days matches average over the full year for each province
        # for each VRE type, and for (load - run-of-river hydro). In each case, rescalings will be set to 1 as needed to avoid exceeding capacity factors of 1 or load greater than max load.

        # Get the rescaled representative day values from clusterer, and then need weighted sum over rep days of our data to match these
        # weighted_means_dict = {}

        # for prov in provinces:
        #     for type in time_series_types:
        #         key = f"{type}_{prov}"
        #         rep_arr = (clusterer.representative_day_arr[:,s_dict[key]:s_dict[key]+hd]*
        #             (clusterer.norm_factor_dict[key][1]-clusterer.norm_factor_dict[key][0])/weight_dict2[type]+
        #             clusterer.norm_factor_dict[key][0])

        #         rep_arr_times_weights = rep_arr * np.array(occurrences)[:, np.newaxis]
        #         # Dictionary with the weighted annual means for each time_series_type that will need to be matched
        #         weighted_means_dict[key] = np.sum(rep_arr_times_weights)/8760

        #         # Start with wind and solar cases
        #         if (type=='wind' or type=='pv'):

        # TODO: This code is inefficient because it redoes many of the calculations used to run the clustering
        for prov in provinces:
            # Repeating relevant code from above

            # Filter generators to solar and wind
            filter_gen_df = gen_df[
                gen_df["carrier"].isin(RES)
                & (gen_df["province"] == prov)
            ]

            for res in RES:  # Start by doing wind and solar cases
                # Get current RES generators
                current_res = filter_gen_df[
                    filter_gen_df["carrier"].str.contains(res, case=False, na=False)
                ]
                # Extract the generators names
                current_res = (
                    current_res.reset_index()
                )  # To avoid Generator being an index
                # Generators names
                names = current_res["name"].tolist()

                if len(names):
                    # Columns of the respective RES for the given period
                    RES_col = gen_max_df.loc[pd.IndexSlice[period, :], names]
                    # Compute average over all res for the province and period. This is the target that we will try to reach by rescaling rep days
                    RES_mean_target = RES_col.mean(axis=None)

                    RES_col_rep_days = RES_col.loc[
                        (RES_col.index.get_level_values("period") == period)
                        & np.isin(
                            RES_col.index.get_level_values("timestep").date,
                            rep_day_dates,
                        )
                    ]

                    RES_col_rep_days_times_weights = RES_col_rep_days.multiply(
                        snap_df.loc[
                            (snap_df.index.get_level_values("period") == period)
                            & np.isin(
                                snap_df.index.get_level_values("timestep").date,
                                rep_day_dates,
                            ),
                            "objective",
                        ],
                        axis=0,
                    )

                    RES_mean_rep_days = (
                        RES_col_rep_days_times_weights.sum().sum()
                        / 8760
                        / RES_col_rep_days_times_weights.shape[1]
                    )
                    scaling = RES_mean_target / RES_mean_rep_days

                    while not math.isclose(scaling, 1, rel_tol=0.0001):
                        RES_col_rep_days = RES_col_rep_days * scaling
                        RES_col_rep_days[RES_col_rep_days > 1] = 1

                        RES_col_rep_days_times_weights = RES_col_rep_days.multiply(
                            snap_df.loc[
                                (snap_df.index.get_level_values("period") == period)
                                & np.isin(
                                    snap_df.index.get_level_values("timestep").date,
                                    rep_day_dates,
                                ),
                                "objective",
                            ],
                            axis=0,
                        )

                        RES_mean_rep_days = (
                            RES_col_rep_days_times_weights.sum().sum()
                            / 8760
                            / RES_col_rep_days_times_weights.shape[1]
                        )
                        scaling = RES_mean_target / RES_mean_rep_days

                    # When complete, replace the relevant rows and columns in the p_max_pu dataframe by the rescaled values for the rep days for the given province and period
                    gen_max_df.loc[
                        (gen_max_df.index.get_level_values("period") == period)
                        & np.isin(
                            gen_max_df.index.get_level_values("timestep").date,
                            rep_day_dates,
                        ),
                        names,
                    ] = RES_col_rep_days

            # Now do rescaling for loads and for run-of-river (ror) hydro. Set rescaling to 1 if ror hydro capacity factor is greater than one or if load is greater than peak load
            # Repeating code from above

            # Filter to relevant province
            load_df_filtered = load_df.loc[:, load_df.columns.str.startswith(prov)]
            # Select the period of interest
            load_df_filtered = load_df_filtered.loc[pd.IndexSlice[period, :], :]
            # Find maxima of each column for future reference
            load_df_filtered_maxima = load_df_filtered.max()

            # Load sum
            load_agg = load_df_filtered.sum(axis=1)
            load_agg = load_agg.to_frame()
            # Select the period of interest
            load_agg = load_agg.loc[pd.IndexSlice[period, :], :]

            # Calculate load subtracted by run of river
            filter_hydro = gen_df[
                (gen_df["model"] == "hydro_ror")
                & (gen_df["province"] == prov)
                & (
                    (n.get_active_assets(c="Generator", investment_period=period))
                    == True
                )
            ]
            # Filter columns based on hydro sources
            hydro_names = filter_hydro.index
            # Hydro columns hourly capacity factor
            hydro_cols = gen_max_df.loc[pd.IndexSlice[period, :], hydro_names]
            # Multiply to get hydro hourly generation
            for name in hydro_names:
                hydro_cols[name] *= filter_hydro[filter_hydro.index == name][
                    "p_nom"
                ].values[0]
            hydro_pow = hydro_cols.sum(axis=1)
            hydro_pow = hydro_pow.to_frame()
            hydro_pow.index = load_agg.index
            net_load = load_agg - hydro_pow

            # Compute average for the province and period. This is the target that we will try to reach by rescaling rep days
            net_load_mean_target = net_load.mean(axis=None)

            # Filter loads and hydro capacity factors to representative days, and combine to compute weighted average over rep days
            load_df_filtered_rep_days = load_df_filtered.loc[
                (load_df_filtered.index.get_level_values("period") == period)
                & np.isin(
                    load_df_filtered.index.get_level_values("timestep").date,
                    rep_day_dates,
                )
            ]

            # Load sum
            load_agg_rep_days = load_df_filtered_rep_days.sum(axis=1)
            load_agg_rep_days = load_agg_rep_days.to_frame()

            hydro_cols_rep_days = gen_max_df.loc[
                np.isin(
                    gen_max_df.index.get_level_values("timestep").date, rep_day_dates
                ),
                hydro_names,
            ]

            # Multiply to get hydro hourly generation
            hydro_power_rep_days = hydro_cols_rep_days.copy()

            for name in hydro_names:
                hydro_power_rep_days[name] *= filter_hydro[filter_hydro.index == name][
                    "p_nom"
                ].values[0]
            hydro_pow_rep_days = hydro_power_rep_days.sum(axis=1)
            hydro_pow_rep_days = hydro_pow_rep_days.to_frame()
            hydro_pow_rep_days.index = load_agg_rep_days.index
            net_load_rep_days = load_agg_rep_days - hydro_pow_rep_days

            # Computed weighted average over the year
            net_load_rep_days_times_weights = net_load_rep_days.multiply(
                snap_df.loc[
                    (snap_df.index.get_level_values("period") == period)
                    & np.isin(
                        snap_df.index.get_level_values("timestep").date, rep_day_dates
                    ),
                    "objective",
                ],
                axis=0,
            )

            net_load_mean_rep_days = net_load_rep_days_times_weights.sum().sum() / 8760
            scaling = net_load_mean_target / net_load_mean_rep_days

            while not math.isclose(scaling, 1, rel_tol=0.0001):
                hydro_cols_rep_days = hydro_cols_rep_days * scaling
                hydro_cols_rep_days[hydro_cols_rep_days > 1] = 1

                load_df_filtered_rep_days = load_df_filtered_rep_days * scaling
                load_df_filtered_rep_days.clip(upper=load_df_filtered_maxima, axis=1)

                # Load sum
                load_agg_rep_days = load_df_filtered_rep_days.sum(axis=1)
                load_agg_rep_days = load_agg_rep_days.to_frame()

                # Multiply to get hydro hourly generation
                hydro_power_rep_days = hydro_cols_rep_days.copy()

                for name in hydro_names:
                    hydro_power_rep_days[name] *= filter_hydro[
                        filter_hydro.index == name
                    ]["p_nom"].values[0]
                hydro_pow_rep_days = hydro_power_rep_days.sum(axis=1)
                hydro_pow_rep_days = hydro_pow_rep_days.to_frame()
                hydro_pow_rep_days.index = load_agg_rep_days.index
                net_load_rep_days = load_agg_rep_days - hydro_pow_rep_days

                # Computed weighted average over the year
                net_load_rep_days_times_weights = net_load_rep_days.multiply(
                    snap_df.loc[
                        (snap_df.index.get_level_values("period") == period)
                        & np.isin(
                            snap_df.index.get_level_values("timestep").date,
                            rep_day_dates,
                        ),
                        "objective",
                    ],
                    axis=0,
                )

                net_load_mean_rep_days = (
                    net_load_rep_days_times_weights.sum().sum() / 8760
                )
                scaling = net_load_mean_target / net_load_mean_rep_days

            # When complete, replace the relevant rows and columns in the p_max_pu dataframe and the loads_p_set dataframe by the rescaled values for the rep days for the given province and period
            gen_max_df.loc[
                (gen_max_df.index.get_level_values("period") == period)
                & np.isin(
                    gen_max_df.index.get_level_values("timestep").date, rep_day_dates
                ),
                hydro_names,
            ] = hydro_cols_rep_days

            load_df.loc[
                (load_df.index.get_level_values("period") == period)
                & np.isin(
                    load_df.index.get_level_values("timestep").date, rep_day_dates
                ),
                load_df.columns.str.startswith(prov),
            ] = load_df_filtered_rep_days

    # TODO: Add other variables we need to return
    return snap_df, gen_max_df, load_df
