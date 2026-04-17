"""
Representative snapshot selection module for PyPSA Canada.

This module provides various methods for selecting representative days/snapshots
for temporal aggregation in energy system optimization models.
"""

from enum import Enum

from pypsa import Network

from representative_days.avg_peak import avg_peak_method
from representative_days.carpe_diem import carpe_diem_method
from representative_days.kmedoid import kmedoid_method
from representative_days.kmedoid_quad import kmedoid_quad_method
from representative_days.net_loads import net_load_calculation
from representative_days.opt import opt_method
from representative_days.opt_quad import opt_quad_method
from representative_days.opt_triple import opt3_method
from representative_days.vre_vector import vre_method


class SnapshotProfile(Enum):
    """Available snapshot selection methods."""

    DEFAULT = 0
    KMEDOID = 1
    OPT = 2
    KMEDOID_VRE = 3
    KMEDOID_VRE_HYDRO = 4
    OPT_VRE = 5
    OPT_VRE_HYDRO = 6
    CARPE_DIEM = 7
    AVG_PEAK = 8


class SnapshotStatus(Enum):
    """Status of snapshot generation state."""

    Initialize = 0
    Completed = 1
    Delayed = 2


def snapshots_selection(
    network: Network,
    snapshot_config: dict,
    snapshot_status: SnapshotStatus = SnapshotStatus.Initialize,
) -> tuple[Network, SnapshotStatus]:
    """
    Snapshots method selection function.

    Parameters
    ----------
    network : Network
        PyPSA network object
    snapshot_config : dict
        Configuration dictionary for selected method
    snapshot_status : SnapshotStatus, optional
        Current status of snapshot generation, by default SnapshotStatus.Initialize

    Returns
    -------
    tuple[Network, SnapshotStatus]
        Updated network and snapshot status

    Raises
    ------
    ValueError
        If invalid snapshot method is specified
    """
    snapshot_method: SnapshotProfile = SnapshotProfile[
        snapshot_config.get("method", "Default").upper()
    ]

    provinces = snapshot_config.get("provinces_selection")
    cluster = snapshot_config.get("cluster", 6)
    solver = snapshot_config.get("solver", "highs")
    year = snapshot_config.get("year")
    aggregate = snapshot_config.get("aggregate", False)
    with_hydro = snapshot_config.get("include_hydro", False)

    output_params = {
        "save_fig": snapshot_config.get("save_fig", False),
        "save_csv": snapshot_config.get("save_csv", False),
        "saving_folder_path": snapshot_config.get("saving_folder_path", "./"),
    }

    def _calculate_net_load():
        return net_load_calculation(
            network,
            provinces=provinces,
            with_hydro=with_hydro,
            save_file=False,
            filepath=output_params["saving_folder_path"],
        )

    def _check_delayed_execution(snapshot_profile: str) -> bool:
        """Check if method execution should be delayed."""
        if snapshot_status == SnapshotStatus.Initialize:
            print(f"Delaying snapshot generation for {snapshot_profile}")
            return True
        return False

    match snapshot_method:
        case SnapshotProfile.DEFAULT:
            print("Using current snapshot file already in input")
            snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.KMEDOID:
            network, net_load = _calculate_net_load()
            network.snapshot_weightings = kmedoid_method(
                network,
                net_load,
                rep_length=snapshot_config.get("rep_length", 14),
                cluster=cluster,
                extreme_select=snapshot_config.get("extreme_days_select", False),
                **output_params,
            )

        case SnapshotProfile.OPT:
            network, netload = _calculate_net_load()
                n=network,
                nload_data=net_load,
                bin=cluster,
                solver=solver,
                **output_params,
            )

        case SnapshotProfile.KMEDOID_VRE:
            network.snapshot_weightings = vre_method(
                network,
                cluster=cluster,
                **output_params,
            )

        case SnapshotProfile.KMEDOID_VRE_HYDRO:
            if snapshot_status == SnapshotStatus.Initialize and year is None:
                print("Delaying snapshot generation - year required")
                snapshot_status = SnapshotStatus.Delayed
            else:
                network.snapshot_weightings = kmedoid_quad_method(
                    network,
                    provinces=provinces,
                    year=year,
                    cluster=cluster,
                    **output_params,
                )

        case SnapshotProfile.OPT_VRE:
            network.snapshot_weightings = opt3_method(
                n=network,
                bin=cluster,
                solver=solver,
                **output_params,
            )

        case SnapshotProfile.OPT_VRE_HYDRO:
            if _check_delayed_execution("OPT VRE Hydro"):
                snapshot_status = SnapshotStatus.Delayed
            elif snapshot_status == SnapshotStatus.Delayed:
                print("Running OPT VRE Hydro method")
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
            if _check_delayed_execution("CARPE DIEM"):
                snapshot_status = SnapshotStatus.Delayed
            elif snapshot_status == SnapshotStatus.Delayed:
                print("Running CARPE DIEM method")
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
            if _check_delayed_execution("AVG PEAK"):
                snapshot_status = SnapshotStatus.Delayed
            elif snapshot_status == SnapshotStatus.Delayed:
                print("Running AVG PEAK method")
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

    # Set status to Completed unless explicitly set to Delayed
    if snapshot_status != SnapshotStatus.Delayed:
        snapshot_status = SnapshotStatus.Completed

    return network, snapshot_status
