import os
from collections import defaultdict

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pypsa


def avg_peak_method(
    n: pypsa.Network(),
    provinces: list,
    year=None,
    aggregate=False,
    save_fig: bool = True,
    save_csv: bool = True,
    saving_folder_path="./",
):
    """
    _summary_

    n : pypsa.Network
        Imported pypsa network
    provinces : list
        List of provinces whose data (load, in this method) are to be used to generate representative days
    year: int, optional
        Year to use to create representative days; if None (default), finds representative days for each year/period
    aggregate: boolean, optional
        If false, chooses peak and average day in each province in the list; if true, selects days for the entire region based on total load
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
        output = pd.DataFrame(output)
        return output

    # Function get monthly peak and average
    def get_month_stat(df, provinces):
        results = {}

        for month, group in df.groupby(df.index.month):
            peak_hour_load = group.max().max()
            peak_hour_time = group == peak_hour_load

            # Find peak day
            peak_day = peak_hour_time.any(axis=1).idxmax()

            # Get the vector of peak day
            peak_day_vector = group.loc[peak_day].values

            # Average
            month_avg = group.mean().values

            # Identify the day with lowest RMSE with month avg
            rmse = np.sqrt(((group - month_avg) ** 2).mean(axis=1))
            avg_day = rmse.idxmin()
            avg_vector = group.loc[avg_day].values

            # Weights for peak and avg day
            w_peak = 1 / len(provinces)
            w_avg = (len(group) - w_peak * len(provinces)) / len(provinces)

            results[month] = {
                "peak_day": peak_day,
                "avg_day": avg_day,
                "peak_day_vector": peak_day_vector,
                "avg_vector": avg_vector,
                "w_peak": w_peak,
                "w_avg": w_avg,
            }
        return results

    # Load loads-p_set.csv
    load_df = n.loads_t.p_set.copy()

    # Load snapshots
    snap_df = n.snapshot_weightings.copy()
    # Get periods
    periods = np.unique(snap_df.index.get_level_values("period"))
    # To reshape the load to (number of days x 24)
    hd = 24
    # Make a list that either contains a single region, or the list of provinces
    if aggregate == False:
        regions_list = provinces
    else:
        regions_list = ["aggregated"]

    ########################################################## STOPPED HERE
    # Loop to estimate rep days for each year
    if year is None:
        year_info = defaultdict(lambda: defaultdict(dict))
        for period in periods:
            for prov in regions_list:
                if aggregate == False:
                    # Filter load to relevant province
                    load_df_filtered = load_df.loc[
                        :, load_df.columns.str.startswith(prov)
                    ]
                else:
                    load_df_filtered = load_df.filter(regex=f"^({'|'.join(provinces)})")
                # Load sum
                load_agg = load_df_filtered.sum(axis=1)
                load_agg = load_agg.to_frame()
                load_mat = daily_prof(load_agg.loc[pd.IndexSlice[period, :], :], hd)
                start_date = str(period) + "-01-01"
                dates = pd.date_range(
                    start=start_date,
                    end=f"{pd.to_datetime(start_date).year}-12-31",
                    freq="D",
                )
                dates = dates[~((dates.month == 2) & (dates.day == 29))]
                load_mat.index = dates
                load_mat.to_csv(f"{saving_folder_path}load_mat.csv")
                # Extract monthly information
                if aggregate == False:
                    month_info = get_month_stat(load_mat, provinces=regions_list)
                else:
                    month_info = get_month_stat(load_mat, provinces=regions_list)
                # Plot the figures
                if save_fig:
                    fig, axes = plt.subplots(6, 2, figsize=(12, 18))
                    axes = axes.flatten()

                    for month, stats in month_info.items():
                        ax = axes[month - 1]  # Adjust to 0

                        # Plot peak
                        ax.plot(
                            stats["peak_day_vector"],
                            color="red",
                            label=f"Month {month} Peak Day {stats['peak_day']} Province {prov}",
                            linewidth=2,
                        )
                        # Plot average
                        ax.plot(
                            stats["avg_vector"],
                            color="blue",
                            label=f"Month {month} Avg Day {stats['avg_day']} Province {prov}",
                            linewidth=2,
                        )
                        # Title and labels
                        ax.set_title(f"Month {month} Demand {period} Province {prov}")
                        ax.set_xlabel("Hour")
                        ax.set_ylabel("Demand")
                        ax.legend()

                    plt.tight_layout()
                    plt.savefig(
                        f"{saving_folder_path}Representative_days_{period}_{prov}.png",
                        dpi=300,
                        bbox_inches="tight",
                    )
                    plt.close()
                # Save data for the year and province
                year_info[period][prov] = month_info
    else:
        year_info = defaultdict(lambda: defaultdict(dict))
        period = year
        for prov in regions_list:
            # Filter load to relevant province
            if aggregate == False:
                # Filter load to relevant province
                load_df_filtered = load_df.loc[:, load_df.columns.str.startswith(prov)]
            else:
                load_df_filtered = load_df.filter(regex=f"^({'|'.join(provinces)})")
            # Load sum
            load_agg = load_df_filtered.sum(axis=1)
            load_agg = load_agg.to_frame()
            load_mat = daily_prof(load_agg.loc[pd.IndexSlice[period, :], :], hd)
            start_date = str(period) + "-01-01"
            dates = pd.date_range(
                start=start_date,
                end=f"{pd.to_datetime(start_date).year}-12-31",
                freq="D",
            )
            dates = dates[~((dates.month == 2) & (dates.day == 29))]
            load_mat.index = dates
            load_mat.to_csv(f"{saving_folder_path}load_mat.csv")
            # Extract monthly information
            month_info = get_month_stat(load_mat, regions_list)
            # Plot the figures
            if save_fig:
                fig, axes = plt.subplots(6, 2, figsize=(12, 18))
                axes = axes.flatten()

                for month, stats in month_info.items():
                    ax = axes[month - 1]  # Adjust to 0

                    # Plot peak
                    ax.plot(
                        stats["peak_day_vector"],
                        color="red",
                        label=f"Month {month} Peak Day {stats['peak_day']} Province {prov}",
                        linewidth=2,
                    )
                    # Plot average
                    ax.plot(
                        stats["avg_vector"],
                        color="blue",
                        label=f"Month {month} Avg Day {stats['avg_day']} Province {prov}",
                        linewidth=2,
                    )
                    # Title and labels
                    ax.set_title(f"Month {month} Demand {period} Province {prov}")
                    ax.set_xlabel("Hour")
                    ax.set_ylabel("Demand")
                    ax.legend()

                plt.tight_layout()
                plt.savefig(
                    f"{saving_folder_path}Representative_days_{period}_{prov}.png",
                    dpi=300,
                    bbox_inches="tight",
                )
                plt.close()
            # Save data for the year and province
            year_info[period][prov] = month_info

    # Save snap name
    filename = "snapshots_avg_method"
    filename_csv = f"{filename}.csv"
    # Alter snapshots
    snap_df[["objective", "stores", "generators"]] = (
        0.0  # Use float to allow decimal weights
    )
    # Set the weights

    for year_key, year_prov in year_info.items():
        for prov, prov_stats in year_prov.items():
            for month, stats in prov_stats.items():
                peak_day = stats["peak_day"]
                avg_day = stats["avg_day"]
                # If peak demand and average day are the same
                if peak_day == avg_day:
                    # Timestamps for identified day
                    avg_hours = pd.date_range(start=avg_day, periods=24, freq="h")
                    # Assign weights
                    snap_df.loc[pd.IndexSlice[year_key, avg_hours], ["objective"]] += (
                        stats["w_peak"] + stats["w_avg"]
                    )
                    snap_df.loc[
                        pd.IndexSlice[year_key, avg_hours], ["stores", "generators"]
                    ] = 1
                else:
                    # Timestamps for the identified days
                    peak_hours = pd.date_range(start=peak_day, periods=24, freq="h")
                    avg_hours = pd.date_range(start=avg_day, periods=24, freq="h")
                    # Assign weights
                    snap_df.loc[pd.IndexSlice[year_key, peak_hours], ["objective"]] += (
                        stats["w_peak"]
                    )
                    snap_df.loc[
                        pd.IndexSlice[year_key, peak_hours], ["stores", "generators"]
                    ] = 1
                    snap_df.loc[pd.IndexSlice[year_key, avg_hours], ["objective"]] += (
                        stats["w_avg"]
                    )
                    snap_df.loc[
                        pd.IndexSlice[year_key, avg_hours], ["stores", "generators"]
                    ] = 1

    if (
        year is not None
    ):  # Case where a single year was used to define representative days
        # periods_not_covered = [yr for yr in periods if yr != year]
        snap_df_year = snap_df.loc[year, ["objective", "stores", "generators"]].copy()

        for yr in periods:
            if yr != year:
                mask = snap_df.index.get_level_values("period") == yr
                snap_df.loc[mask, ["objective", "stores", "generators"]] = (
                    snap_df_year.values
                )

    # Save and finish
    try:
        os.makedirs(saving_folder_path)
    except OSError:
        print("Folder exist skipping step")

    if save_csv:
        snap_df.to_csv(f"{saving_folder_path}{filename_csv}")

    return snap_df
