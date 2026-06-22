"""
Representative snapshot selection module for PyPSA Canada.

This module provides various methods for selecting representative days/snapshots
for temporal aggregation in energy system optimization models.
"""

from enum import Enum

import pandas as pd
from pypsa import Network

from representative_days.all_days import all_days_method
from representative_days.avg_peak import avg_peak_method
from representative_days.carpe_diem import carpe_diem_method
from representative_days.kmedoid_quad import kmedoid_quad_method
from representative_days.opt_quad import opt_quad_method

# from representative_days.opt_triple import opt3_method
# from representative_days.vre_vector import vre_method





class SnapshotProfile(Enum):
    """Available snapshot selection methods."""

    # TODO: verify snapshot selections
    DEFAULT = (
        0  # Use the snapshot file already in the input network (no selection applied)
    )
    ALL_DAYS = 1  # Keep all snapshots and assign a weighting of 1
    # KMEDOID_VRE = 1  # Does not complete
    KMEDOID_VRE_HYDRO = 2  # Functional
    # OPT_VRE = 3  # Does not complete
    OPT_VRE_HYDRO = 4  # Functional
    CARPE_DIEM = 5  # Functional
    AVG_PEAK = 6  # Functional


def snapshots_selection(
    network: Network,
    snapshot_config: dict,
) -> Network:
    """
    Snapshots method selection function.

    Parameters
    ----------
    network : Network
        PyPSA network object
    snapshot_config : dict
        Configuration dictionary for selected method

    Returns
    -------
    Network
        Updated network with selected snapshots

    Raises
    ------
    ValueError
        If invalid snapshot method is specified
    """
    snapshot_method: SnapshotProfile = SnapshotProfile[
        snapshot_config["method"].upper()
    ]

    provinces = snapshot_config.get("provinces_selection")
    cluster = snapshot_config.get("cluster", 6)
    solver = snapshot_config.get("solver", "highs")
    year = snapshot_config.get("year")
    aggregate = snapshot_config.get("aggregate", False)

    output_params = {
        "save_fig": snapshot_config.get("save_fig", False),
        "save_csv": snapshot_config.get("save_csv", False),
        # TODO: consider removing from config
        "saving_folder_path": snapshot_config.get("saving_folder_path", "./"),
    }

    match snapshot_method:
        case SnapshotProfile.DEFAULT:
            print("Using current snapshot file already in input")

        case SnapshotProfile.ALL_DAYS:
            network.snapshot_weightings = all_days_method(network)

        # case SnapshotProfile.KMEDOID_VRE:
        #     network.snapshot_weightings = vre_method(
        #         network,
        #         cluster=cluster,
        #         **output_params,
        #     )

        case SnapshotProfile.KMEDOID_VRE_HYDRO:
            network.snapshot_weightings = kmedoid_quad_method(
                network,
                provinces=provinces,
                year=year,
                cluster=cluster,
                **output_params,
            )

        # case SnapshotProfile.OPT_VRE:
        #     network.snapshot_weightings = opt3_method(
        #         n=network,
        #         bin=cluster,
        #         solver=solver,
        #         **output_params,
        #     )

        case SnapshotProfile.OPT_VRE_HYDRO:
            network.snapshot_weightings = opt_quad_method(
                n=network,
                provinces=provinces,
                year=year,
                aggregate=aggregate,
                bin=cluster,
                solver=solver,
                **output_params,
            )

        case SnapshotProfile.CARPE_DIEM:
            (
                network.snapshot_weightings,
                network.generators_t.p_max_pu,
                network.loads_t.p_set,
            ) = carpe_diem_method(
                n=network,
                provinces=provinces,
                clusters=cluster,
            )

        case SnapshotProfile.AVG_PEAK:
            network.snapshot_weightings = avg_peak_method(
                n=network,
                provinces=provinces,
                year=year,
                aggregate=aggregate,
                **output_params,
            )

        case _:
            raise ValueError(
                f"Invalid snapshot method: {snapshot_config.get('method')}"
            )

    return network
