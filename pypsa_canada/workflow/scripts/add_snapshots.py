import logging
import os
import sys
import traceback

import numpy as np
import pandas as pd
from load_load_forecast import LoadProfile, load_load_forecast
from pypsa import Network

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"

# Ensure log directory exists
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)

# Configure logging to both file and stdout (handy for --show-failed-logs)
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    format="%(asctime)s %(levelname)s %(message)s",
)

config = snakemake.config


def create_yearly_snapshots(
    network: Network,
    snapshot_config,
) -> Network:
    snapshot_new_df = pd.DatetimeIndex([])
    # import reference year snapshots into list <ref_list>
    period_df = pd.DatetimeIndex([])
    folder_name = snapshot_config["folder_name"]
    years = snapshot_config["years"]
    ref_year = snapshot_config["ref_year"]
    ref_list = pd.read_csv(os.path.join(folder_name, "snapshots.csv"), usecols=[0])
    ref_list = ref_list.squeeze()
    ref_list = ref_list.tolist()

    # Create yearly snapshots <period_df> and create new snapshot dataframe <snapshot_new_df>
    for year in years:
        temp_list = ref_list.copy()
        temp_list = list(
            map(
                lambda x: str(x).replace(str(ref_year), str(year)),
                # lambda x: str(x).replace(str(snapshot_config["ref_year"]), str(year)),
                temp_list,
            )
        )
        period_df = pd.to_datetime(temp_list)
        snapshot_new_df = snapshot_new_df.append(period_df)

    # print(f"network ref snapshots=\n{network.snapshots}")
    print(f"Network snapshots=\n{snapshot_new_df}")
    network.snapshots = snapshot_new_df
    # network.snapshots = snapshot_new_df

    # Create copies of reference series data before overwriting the snapshot index
    # ss_weightings_old_df = network.snapshot_weightings.copy()
    # generator_t_p_max_pu_old_df = network.generators_t.p_max_pu.copy()
    # generator_t_p_min_pu_old_df = network.generators_t.p_min_pu.copy()
    # links_t_p_max_pu_old_df = network.links_t.p_max_pu.copy()
    # links_t_p_min_pu_old_df = network.links_t.p_min_pu.copy()
    print(f"Load shape={network.loads_t.p_set.shape}")
    print(f"Load shape create_yearly_snapshots=\n {network.loads_t.p_set}")
    # loads_t_p_set_old_df = network.loads_t.p_set.copy()
    # storage_units_t_inflow_old_df = network.storage_units_t.inflow.copy()
    return network


def save_ref_year_data(
    network: Network, network_ref: Network, snapshot_config
) -> Network:
    generator_t_p_max_pu = network_ref.generators_t.p_max_pu.copy()
    storage_units_t_inflow_old_df = network_ref.storage_units_t.inflow.copy()
    links_t_p_max_pu = network_ref.links_t.p_max_pu.copy()
    links_t_p_min_pu = network_ref.links_t.p_min_pu.copy()

    for i in range(0, len(snapshot_config["years"])):
        a = i * 8760
        b = (i + 1) * 8760
        network.snapshot_weightings[a:b] = 1
        network.generators_t.p_max_pu[a:b] = generator_t_p_max_pu.values
        network.storage_units_t.inflow[a:b] = storage_units_t_inflow_old_df.values
        if hasattr(network, "links_t_p_max_pu"):
            network.links_t.p_max_pu[a:b] = links_t_p_max_pu.values
        if hasattr(network, "links_t_p_min_pu"):
            network.links_t.p_min_pu[a:b] = links_t_p_min_pu.values
        # network.generators_t.marginal_cost[a:b] = marginal_cost_ref.loc[str(years[i])].values

    return network


# @abstractmethod
def create_yearly_weightings(
    network: Network,
    network_ref: Network,
    snapshot_config: dict,
    discount_rate: float = 0.05,
) -> Network:
    """
    create_yearly_weightings _summary_

    Parameters
    ----------
    discount_rate : float, optional
        rate of interest that is applied to future cash flows of an investment to
        calculate its present value, by default 0.05
    """
    years = snapshot_config["years"]
    load_mode = LoadProfile[snapshot_config["load_mode"].upper()]
    snapshot_new_df = network.snapshots

    # Convert to multiindex and assign to network
    # network_loads_p_temp = network.loads_t.p_set.iloc[0:8760].copy()
    print(f"Shape_of_loads_pset_before_snapshots={network_ref.loads_t.p_set.shape}")
    print(f"loads_pset_before_snapshots={network_ref.loads_t.p_set}")

    network.snapshots = pd.MultiIndex.from_arrays(
        [snapshot_new_df.year, snapshot_new_df], names=["period", "timestep"]
    )

    network.investment_periods = years
    ss_weightings_old_df = network_ref.snapshot_weightings.copy()
    storage_units_t_inflow_old_df = network_ref.storage_units_t.inflow.copy()
    generator_t_p_max_pu_old_df = network_ref.generators_t.p_max_pu.copy()
    generator_t_p_min_pu_old_df = network_ref.generators_t.p_min_pu.copy()
    links_t_p_max_pu_old_df = network_ref.links_t.p_max_pu.copy()
    links_t_p_min_pu_old_df = network_ref.links_t.p_min_pu.copy()
    marginal_cost = network_ref.generators_t.marginal_cost.copy()

    for year in years:
        network.snapshot_weightings.loc[(year)] = ss_weightings_old_df.values
        network.storage_units_t.inflow.loc[(year)] = (
            storage_units_t_inflow_old_df.values
        )
        network.generators_t.p_max_pu.loc[(year)] = generator_t_p_max_pu_old_df.values
        network.generators_t.p_min_pu.loc[(year)] = generator_t_p_min_pu_old_df.values
        if hasattr(network, "links_t_p_max_pu"):
            network.links_t.p_max_pu.loc[(year)] = links_t_p_max_pu_old_df.values
        if hasattr(network, "links_t_p_min_pu"):
            network.links_t.p_min_pu.loc[(year)] = links_t_p_min_pu_old_df.values
        network.generators_t.marginal_cost.loc[(year)] = marginal_cost.loc[
            marginal_cost.index.str.contains(str(year))
        ].values

        # Check if the load profile has not been loaded depending on profile
        print(f"Shape_of_loads_pset={network.loads_t.p_set.shape}")

        loads_t_p_set_ref_df = network_ref.loads_t.p_set.copy()

        match load_mode:
            case LoadProfile.DEFAULT:
                network = apply_growth_load(
                    network, loads_t_p_set_ref_df, year, snapshot_config
                )
            case LoadProfile.CER:
                print("Load will be copied at the end of the preprocess")
            case LoadProfile.CODERS:
                network = apply_growth_load(
                    network, loads_t_p_set_ref_df, year, snapshot_config
                )
            case LoadProfile.CUSTOM:
                # TODO verify this is correct
                network.loads_t.p_set = network_ref.loads_t.p_set.copy()
            # case mode_flat if "flat" in mode_flat:
            # case LoadProfile.FLAT:
            #     network = apply_growth_load(
            #         network, loads_t_p_set_ref_df, year, snapshot_config
            #     )
            case _:
                raise Exception(
                    "Load profile not recognized. Please check the load_profile option in the config file."
                )

    ss_weight_intindex_df = network_ref.snapshot_weightings.reset_index()
    list_snapshots = ss_weight_intindex_df.index[
        ss_weight_intindex_df["objective"] > 0
    ].tolist()
    list_snapshots = network.snapshots[
        list_snapshots
    ]  # Enable only when using .optimize.create_model

    network.investment_period_weightings["years"] = list(np.diff(years)) + [
        snapshot_config["investment_periods"]
    ]
    generate_investment_weightings(n=network, years=years, discount_rate=discount_rate)

    return network


def generate_investment_weightings(n, years: list[int], discount_rate: float = 0.05):
    """
    Function to generate the investment weightings based on the discount rate.
    Code taken from the example of pypsa tutorial:
    https://pypsa.readthedocs.io/en/latest/examples/multi-investment-optimisation.html

    Parameters
    ----------
    n : pypsa.Network
        The pypsa network that will be modified
    years : list[int]
        list of investment periods that will be used to calculate
        the investment periods
    discount_rate : float, optional
        the discount rate used to make the calculation of the
        weightings, by default 0.05
    """
    T = 0
    for period, nyears in n.investment_period_weightings.years.items():
        discounts = [(1 / (1 + discount_rate) ** t) for t in range(T, T + nyears)]
        n.investment_period_weightings.at[period, "objective"] = sum(discounts)
        T += nyears

    # print("Investment Weightings:")
    # print(50 * "=")
    # print(n.investment_period_weightings)
    # print(50 * "=")


def apply_growth_load(
    network: Network,
    load_df: pd.DataFrame,
    year: int,
    snapshot_config,
):
    """
    Function to apply load growth to current load based
    on reference year

    Parameters
    ----------
    load_df : pd.DataFrame
        Dataframe containing load_p-set values for each buses
    year : int
        current year to be applied

    Raises
    ------
    LoadGrowthFileMissing
        Error to indicate missing Load Growth file
    """
    load_growth_forecast = snapshot_config["load_growth_forecast"]
    years = snapshot_config["years"]
    load_mode = LoadProfile[config["load"]["load_mode"].upper()]
    load_growth_node = load_load_forecast(load_mode, load_growth_forecast, years)

    loads_t_p_set_ref_df = load_df.copy()

    if loads_t_p_set_ref_df.shape[0] > 8760:
        buffer_df = load_df.iloc[0:8760, :].copy()
    else:
        buffer_df = load_df.copy()
    n = snapshot_config["years"].index(year)
    # Apply growth per load if file is present
    if load_growth_node is not None:
        for i, year_after in enumerate(
            np.asarray(load_growth_node.columns.astype(int))
        ):
            if year > year_after:
                continue
            elif year == year_after:
                map_dict = load_growth_node[str(year)]
                break
            elif year < year_after:
                year_before = np.asarray(load_growth_node.columns.astype(int))[i - 1]
                map_dict_before = load_growth_node[str(year_before)]
                map_dict_after = load_growth_node[str(year_after)]
                map_dict = map_dict_before + (map_dict_after - map_dict_before) * (
                    year - year_before
                ) / (year_after - year_before)
                break

        for key, value in map_dict.items():
            buffer_df.loc[:, key] = buffer_df[key] * value
        network.loads_t.p_set.loc[(year)] = buffer_df.astype(float).values
        network.loads_t.p_set.iloc[8760 * n : (8760) * (n + 1)] = buffer_df.astype(
            float
        ).values
    else:
        raise Exception(
            "No Load Growth file has been"
            "associated in the load_profile option (Full name of "
            "file within that model folder with extension)."
        )

    return network


def main():
    network = Network(snakemake.input.input_data)
    network_ref = network.copy()
    snapshot_config = config["snapshots"]

    network = create_yearly_snapshots(network, snapshot_config)
    network = save_ref_year_data(network, network_ref, snapshot_config)
    network = create_yearly_weightings(network, network_ref, snapshot_config)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)

    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_snapshot failed:\n%s", traceback.format_exc())
        sys.exit(1)
