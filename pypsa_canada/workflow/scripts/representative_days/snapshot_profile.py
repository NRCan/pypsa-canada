from enum import Enum

from pypsa import Network

from representative_days.avg_peak import avg_peak_method
from representative_days.carpe_diem import carpe_diem_method
# from representative_days.kmedoid import kmedoid_method
from representative_days.kmedoid_quad import kmedoid_quad_method
from representative_days.net_loads import net_load_calculation
# from representative_days.opt import opt_method
from representative_days.opt_quad import opt_quad_method
# from representative_days.opt_triple import opt3_method
from representative_days.vre_vector import vre_method


class SnapshotProfile(Enum):
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
    Initialize = 0
    Completed = 1
    Delayed = 2


class GenerateSnapshotProfile:
    def __init__(
        self,
        n: Network,
        provinces=None,
        with_hydro=False,
        save_file=False,
        netload_filepath="./",
    ):
        self.n = n
        self.provinces = provinces
        self.with_hydro = with_hydro
        self.save_file = save_file
        self.netload_filepath = netload_filepath
        # self.snapshot_status = SnapshotStatus.Initialize

    def use_kmedoid_method(
        self,
        rep_length: int = 14,
        cluster: int = 6,
        extreme_select: bool = False,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path: str = "./",
    ):
        self.net_load = net_load_calculation(
            self.n,
            self.provinces,
            self.with_hydro,
            self.save_file,
            self.netload_filepath,
        )

        return kmedoid_method(
            self.n,
            self.net_load,
            rep_length,
            cluster,
            extreme_select,
            save_fig,
            save_csv,
            saving_folder_path,
        )

    def use_opt(
        self,
        bin: int = 12,
        solver: str = "cbc",
        mip_gap: float = 0.001,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path: str = "./",
    ):
        self.net_load = net_load_calculation(
            self.n,
            self.provinces,
            self.with_hydro,
            self.save_file,
            self.netload_filepath,
        )

        return opt_method(
            n=self.n,
            nload_data=self.net_load,
            bin=bin,
            solver=solver,
            mip_gap=mip_gap,
            save_fig=save_fig,
            save_csv=save_csv,
            saving_folder_path=saving_folder_path,
        )

    def use_vre(
        self,
        cluster: int = 6,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path="./",
    ):
        return vre_method(self.n, cluster, save_fig, save_csv, saving_folder_path)

    def use_kmedoid_quad(
        self,
        provinces: list,
        year: int = None,
        cluster: int = 6,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path="./",
    ):
        return kmedoid_quad_method(
            self.n,
            provinces=provinces,
            year=year,
            cluster=cluster,
            save_fig=save_fig,
            save_csv=save_csv,
            saving_folder_path=saving_folder_path,
        )

    def use_opt_triple(
        self,
        bin: int = 12,
        solver: str = "highs",
        mip_gap: float = 0.01,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path="./",
    ):
        return opt3_method(
            n=self.n,
            bin=bin,
            solver=solver,
            mip_gap=mip_gap,
            save_fig=save_fig,
            save_csv=save_csv,
            saving_folder_path=saving_folder_path,
        )

    def use_opt_quad(
        self,
        provinces: list,
        year: int = None,
        aggregate: bool = False,
        bin: int = 12,
        solver: str = "highs",
        mip_gap: float = 0.01,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path="./",
    ):
        return opt_quad_method(
            n=self.n,
            provinces=provinces,
            year=year,
            aggregate=aggregate,
            bin=bin,
            solver=solver,
            mip_gap=mip_gap,
            save_fig=save_fig,
            save_csv=save_csv,
            saving_folder_path=saving_folder_path,
        )

    def use_carpe_diem(self, n, provinces: list, clusters: int = 6):
        return carpe_diem_method(n=n, provinces=provinces, clusters=clusters)

    def use_avg_peak(
        self,
        provinces: list,
        year: int = None,
        aggregate: bool = False,
        save_fig: bool = True,
        save_csv: bool = False,
        saving_folder_path="./",
    ):
        return avg_peak_method(
            n=self.n,
            provinces=provinces,
            year=year,
            aggregate=aggregate,
            save_fig=save_fig,
            save_csv=save_csv,
            saving_folder_path=saving_folder_path,
        )


def snapshots_selection(
    network: Network,
    snapshot_config: dict,
    snapshot_status: SnapshotStatus = SnapshotStatus.Initialize,
) -> tuple[Network, SnapshotStatus]:
    """
    Snapshots method selection function

    Parameters
    ----------
    snapshot_config : dict
        configuration path for selected method
    """
    snapshot_method: SnapshotProfile = SnapshotProfile[
        snapshot_config.get("method", "Default").upper()
    ]
    print(f'Network Generators= {network.c["Generator"].static}')
    snapshot_profile = GenerateSnapshotProfile(
        network,
        provinces=snapshot_config.get("provinces_selection", None),
        with_hydro=snapshot_config["include_hydro"],
        save_file=True,
        netload_filepath=snapshot_config["saving_folder_path"],
    )
    print(f'snapshot_method = {snapshot_method}')
    match snapshot_method:
        case SnapshotProfile.DEFAULT:
            print("Using current snapshot file already in input")
            snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.KMEDOID:
            network.snapshot_weightings = snapshot_profile.use_kmedoid_method(
                rep_length=snapshot_config.get("rep_length", None),
                cluster=snapshot_config["cluster"],
                extreme_select=snapshot_config["extreme_days_select"],
                save_fig=snapshot_config["save_fig"],
                save_csv=snapshot_config["save_csv"],
                saving_folder_path=snapshot_config["saving_folder_path"],
            )
            snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.OPT:
            network.snapshot_weightings = snapshot_profile.use_opt(
                bin=snapshot_config["cluster"],
                solver=snapshot_config["solver"],
                save_fig=snapshot_config["save_fig"],
                save_csv=snapshot_config["save_csv"],
                saving_folder_path=snapshot_config["saving_folder_path"],
            )
            snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.KMEDOID_VRE:
            network.snapshot_weightings = snapshot_profile.use_vre(
                cluster=snapshot_config["cluster"],
                save_fig=snapshot_config["save_fig"],
                save_csv=snapshot_config["save_csv"],
                saving_folder_path=snapshot_config["saving_folder_path"],
            )
            snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.KMEDOID_VRE_HYDRO:
            print(f'Snapshot status = {snapshot_status}')
            if snapshot_config["year"] is not None:
                print(f'First if')
                network.snapshot_weightings = snapshot_profile.use_kmedoid_quad(
                    cluster=snapshot_config["cluster"],
                    save_fig=snapshot_config["save_fig"],
                    save_csv=snapshot_config["save_csv"],
                    saving_folder_path=snapshot_config["saving_folder_path"],
                    provinces=snapshot_config["provinces_selection"],
                    year=snapshot_config["year"],
                )
            else:
                print(f'ELSE')
                if snapshot_status == SnapshotStatus.Initialize:
                    print("Delaying Snapshot generation method")
                    snapshot_status = SnapshotStatus.Delayed

                elif snapshot_status == SnapshotStatus.Delayed:
                    network.snapshot_weightings = snapshot_profile.use_kmedoid_quad(
                        provinces=snapshot_config["provinces_selection"],
                        year=snapshot_config["year"],
                        cluster=snapshot_config["cluster"],
                        save_fig=snapshot_config["save_fig"],
                        save_csv=snapshot_config["save_csv"],
                        saving_folder_path=snapshot_config["saving_folder_path"],
                    )
                    snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.OPT_VRE:
            network.snapshot_weightings = snapshot_profile.use_opt_triple(
                bin=snapshot_config["cluster"],
                solver=snapshot_config["solver"],
                save_fig=snapshot_config["save_fig"],
                save_csv=snapshot_config["save_csv"],
                saving_folder_path=snapshot_config["saving_folder_path"],
            )
            snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.OPT_VRE_HYDRO:
            print("Test_snapshot")
            if snapshot_status == SnapshotStatus.Initialize:
                print("Delaying Snapshot generation method")
                snapshot_status = SnapshotStatus.Delayed

            elif snapshot_status == SnapshotStatus.Delayed:
                print("Running OPT VRE Hydro method")
                network.snapshot_weightings = snapshot_profile.use_opt_quad(
                    bin=snapshot_config["cluster"],
                    provinces=snapshot_config["provinces_selection"],
                    # year=snapshot_config["year"],
                    year=snapshot_config.get("year", None),
                    aggregate=snapshot_config["aggregate"],
                    solver=snapshot_config["solver"],
                    save_fig=snapshot_config["save_fig"],
                    save_csv=snapshot_config["save_csv"],
                    saving_folder_path=snapshot_config["saving_folder_path"],
                    mip_gap=snapshot_config["mip_gap"],
                )
                snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.CARPE_DIEM:
            print("Test_snapshot")
            if snapshot_status == SnapshotStatus.Initialize:
                print("Delaying Snapshot generation method")
                snapshot_status = SnapshotStatus.Delayed

            elif snapshot_status == SnapshotStatus.Delayed:
                print("Running CARPE DIEM method")
                snapshot_profile = GenerateSnapshotProfile(network)
                (
                    network.snapshot_weightings,
                    network.generators_t.p_max_pu,
                    network.links_t.p_max_pu,
                    network.links_t.p_min_pu,
                    network.loads_t.p_set,
                ) = snapshot_profile.use_carpe_diem(
                    n=network,
                    provinces=snapshot_config["provinces_selection"],
                    clusters=snapshot_config["cluster"],
                )
                snapshot_status = SnapshotStatus.Completed

        case SnapshotProfile.AVG_PEAK:
            print("Test_snapshot")
            if snapshot_status == SnapshotStatus.Initialize:
                print("Delaying Snapshot generation method")
                snapshot_status = SnapshotStatus.Delayed

            elif snapshot_status == SnapshotStatus.Delayed:
                print("Running AVG PEAK method")
                network.snapshot_weightings = snapshot_profile.use_avg_peak(
                    provinces=snapshot_config["provinces_selection"],
                    year=snapshot_config["year"],
                    aggregate=snapshot_config["aggregate"],
                    save_fig=snapshot_config["save_fig"],
                    save_csv=snapshot_config["save_csv"],
                    saving_folder_path=snapshot_config["saving_folder_path"],
                )
        case _:
            raise Exception("Invalid method")

    return network, snapshot_status
