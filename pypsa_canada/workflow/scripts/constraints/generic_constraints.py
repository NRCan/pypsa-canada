import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Iterable

import numpy as np
import pandas as pd
import pypsa
from pypsa.descriptors import get_activity_mask, get_switchable_as_dense

from pypsa_canada.deprecation import deprecated

if TYPE_CHECKING:
    import pypsa

logger = logging.getLogger(__name__)


def _load_single_custom_constraint_module(
    module_path: str | Path,
    module_index: int,
) -> ModuleType:
    """
    Load one custom-constraint module from a Python file.
    """
    path = Path(module_path).resolve()

    if not path.is_file():
        raise FileNotFoundError(
            f"Custom constraint module not found: {path}"
        )

    module_name = (
        f"pypsa_canada_custom_constraints_"
        f"{module_index}_{path.stem}"
    )

    spec = importlib.util.spec_from_file_location(
        module_name,
        path,
    )

    if spec is None or spec.loader is None:
        raise ImportError(
            f"Unable to load custom constraint module: {path}"
        )

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


def load_custom_constraint_modules(
    module_paths: str | Path | Iterable[str | Path] | None,
) -> list[ModuleType]:
    """
    Load one or more custom-constraint modules.

    Supports both:
        module_path: "constraint.py"

    and:
        module_paths:
          - "constraint_1.py"
          - "constraint_2.py"
    """
    if not module_paths:
        return []

    if isinstance(module_paths, (str, Path)):
        paths = [module_paths]
    else:
        paths = list(module_paths)

    modules = []

    for module_index, module_path in enumerate(
        paths,
        start=1,
    ):
        modules.append(
            _load_single_custom_constraint_module(
                module_path=module_path,
                module_index=module_index,
            )
        )

    return modules


def CER_generator_grouping(network, CER_constraint, year: int, mode: str):
    """
    _summary_

    Parameters
    ----------
    network : pypsa.Network()
        PyPSA network model
    CER_constraint : dict
        Dictionary containing all informations needed for CER constraint
    year : int
        Current year to be applied
    mode : str
        Either Planning or Dispatch in str type
    active_cer_year : int
        Starting year for CER constraint to be applied

    Returns
    -------
    _type_
        _description_
    """
    # Determine regulated generators
    CER_fuels = list(CER_constraint["carriers"])
    min_cap = CER_constraint["min_cap"]  # NOQA F841
    active_cer_year = CER_constraint["year"]
    CER_generators = pd.DataFrame()
    if mode == "dispatch":
        CER_generators = (
            network.generators[network.generators["carrier"].isin(CER_fuels)]
            .query("p_nom_opt >= @min_cap")
            .copy()
        )
        if not CER_generators.empty:
            CER_generators = CER_generators[
                (CER_generators.build_year >= 2025)
                | (
                    (CER_generators.carrier == "gas")
                    & (CER_generators.build_year + 25 < year)
                )
                | (
                    (CER_generators.carrier != "gas")
                    & (
                        (CER_generators.build_year + 25 < year)
                        | (year >= active_cer_year)
                    )
                )
            ]
        if CER_generators.empty:
            return CER_generators, None, None

        CER_generators = aggregate_generators_into_group(
            CER_constraint, CER_generators, network
        )

    else:
        CER_generators_existing = (
            network.generators[network.generators["carrier"].isin(CER_fuels)]
            .query("p_nom_extendable == False")
            .query("p_nom >= @min_cap")
        )
        if not CER_generators_existing.empty:
            CER_generators_existing = CER_generators_existing[
                (
                    (
                        CER_generators_existing.build_year
                        + CER_generators_existing.lifetime
                    )
                    > year
                )
                & (
                    (CER_generators_existing.build_year >= 2025)
                    | (
                        (CER_generators_existing.carrier == "gas")
                        & (CER_generators_existing.build_year + 25 < year)
                    )
                    | (
                        (CER_generators_existing.carrier != "gas")
                        & (
                            (CER_generators_existing.build_year + 25 < year)
                            | (year >= active_cer_year)
                        )
                    )
                )
            ]
        CER_generators_extendable = (
            network.generators[network.generators["carrier"].isin(CER_fuels)]
            .query("p_nom_extendable == True")
            .query("p_nom_max >= @min_cap")
        )
        if CER_generators_existing.empty and CER_generators_extendable.empty:
            return CER_generators, None, None

        CER_generators_existing = aggregate_generators_into_group(
            CER_constraint, CER_generators_existing, network
        )
        CER_generators_extendable = aggregate_generators_into_group(
            CER_constraint, CER_generators_extendable, network
        )
        CER_generators = pd.concat([CER_generators_existing, CER_generators_extendable])

    CER_group_list = CER_generators.group.unique()
    CER_group_budget = pd.DataFrame(columns=CER_group_list)

    return CER_generators, CER_group_budget, CER_group_list


def aggregate_generators_into_group(CER_constraint, CER_generators, network):
    """
    Aggregate generators into group

    Parameters
    ----------
    CER_constraint : dict
        Dictionary containing all informations needed for CER contraint
    CER_generators : DataFrame
    network : pypsa.Network
        The pypsa network (used to look up bus province column)

    Returns
    -------
    DataFrame
    """
    if CER_constraint["aggregation"] == "individual":
        CER_generators["group"] = CER_generators.index
    elif CER_constraint["aggregation"] == "provincial":
        CER_generators["group"] = CER_generators.bus.map(network.buses["province"])
    elif CER_constraint["aggregation"] == "group":
        pass
    return CER_generators


@deprecated(
    version="0.1",
    alternative="Spill_cost",
)
def add_spilling_variable(
    network: "pypsa.Network", snapshots: "pd.DatetimeIndex | None" = None
):
    """
    M : Linopy.model
        The linopy model property from the pypsa network
    """

    # Define a binary spill variable for each storage unit with inflow, equal to 1 if spilling, 0 if not
    # Inspired from: https://github.com/PyPSA/PyPSA/blob/863d289d7e8f7bec202df628f3dca2d980a5ce72/pypsa/optimization/variables.py#L123
    m = network.model
    c = "StorageUnit"
    if network.df(c).empty:
        pass

    # Use network snapshots if not provided
    if snapshots is None:
        snapshots = network.snapshots

    # Dataframe with inflow for each storage_unit for each snapshot
    upper = get_switchable_as_dense(network, c, "inflow", snapshots)
    if (upper.max() <= 0).all():
        pass

    active = get_activity_mask(network, c, snapshots).where(upper > 0, False)
    coords = (snapshots, active.columns)

    m.add_variables(
        coords=coords, name=f"GlobalConstraint-{c}_spilling", binary=True, mask=active
    )


def add_stop_prod_constraint(
    network: "pypsa.Network",
    snapshots: pd.DatetimeIndex | pd.MultiIndex,
    carriers: list[str],
):
    """
    Constraint to stop production of a specific carrier

    Parameters
    ----------
    network : pypsa.Network
        The pypsa network class sent as an object
    snapshots : list
        list containing all snapshots affected
    carriers: list[str]
        list containing all carriers to restrict production
    """
    # carriers = ["gas"]
    m = network.model
    # for carrier in constraint["carriers"]:
    for carrier in carriers:
        ffgen = network.generators.loc[network.generators.carrier == carrier]
        if not ffgen.empty:
            carriers = ffgen.carrier.to_xarray()
            total_prod = (
                m.variables["Generator-p"]
                .loc[snapshots, ffgen.index]
                .groupby(carriers)
                .sum()
                .sum("snapshot")
            )
            if isinstance(snapshots, pd.MultiIndex):
                period = snapshots.get_level_values("period").unique()
                if len(period) == 1:
                    period = period[0]  # raw single value
                m.add_constraints(
                    total_prod == 0,
                    name=f"GlobalConstraint-Stop_production_{carrier}_{period}_dynamic",
                )
            else:
                m.add_constraints(
                    total_prod == 0,
                    name=f"GlobalConstraint-Stop_production_{carrier}_{snapshots[0]}_dynamic",
                )


def add_bidirection_link_constraint(network: "pypsa.Network", links_dict: dict):
    """
    Function to add a constraint for connexion represented
    by 2 unidirectional links (necessary to consider a marginal cost)
    to avoid energy transfer in both directions at the same time

    Parameters
    ----------
    links_dict : dict
        dictionary containing the connexions concerned and the two link names for each
    network : pypsa.Network
        The pypsa network class sent as an object
    """
    m = network.model
    for intertie, links in links_dict.items():
        if (links[0] in network.links.index) and (links[1] in network.links.index):
            # Only fixed and committable transmission are treaten here
            if (not network.links.loc[links[0]].p_nom_extendable) and (
                not network.links.loc[links[1]].p_nom_extendable
            ):
                if (network.links.loc[links[0]].committable) and (
                    network.links.loc[links[1]].committable
                ):
                    # Bidirection for commitable and not extendable links (can't do it for others cause no variable "status")
                    if (network.links.loc[links[0]].p_nom != 0) or (
                        network.links.loc[links[1]].p_nom != 0
                    ):
                        link0_status = m.variables["Link-status"].sel(
                            {"name": links[0]}
                        )
                        link1_status = m.variables["Link-status"].sel(
                            {"name": links[1]}
                        )
                        m.add_constraints(
                            link0_status + link1_status <= 1,
                            name=f"Bidirectionnality_of_{intertie}",
                        )


@deprecated(
    version="0.1",
    alternative="Spill_cost",
)
def prevent_spill_if_not_fully_charged(
    network: "pypsa.Network",
    snapshots: pd.DatetimeIndex | pd.MultiIndex,
    M: int = 2000,
):
    """
    Function to add a constraint to dispatch that forces spill
    to 0 for a storage unit when it is not fully charged.

    Created to try to remedy sub-obtimal charging of storage
    units when multiple UC periods are considered, where
    units spill when they could have charged.

    Parameters
    ----------
    network : pypsa.Network
        The pypsa network class sent as an object
    snapshots:
        The pypsa network snapshots for which the constraint will be applied
    M : int
        Integer that is larger than the largest of the maximum states of charge of all storage units with inflow
    """

    # Define a binary spill variable for each storage unit with inflow, equal to 1 if spilling, 0 if not
    # Inspired from: https://github.com/PyPSA/PyPSA/blob/863d289d7e8f7bec202df628f3dca2d980a5ce72/pypsa/optimization/variables.py#L123

    m = network.model
    c = "StorageUnit"
    # if network.df(c).empty:
    #     pass

    # #Dataframe with inflow for each storage_unit for each snapshot
    upper = get_switchable_as_dense(network, c, "inflow", snapshots)

    # For each storage unit with inflow, add constraints such that spill is 0 if not fully charged
    units_with_inflow = upper.max()[upper.max() > 0].index
    print(f"Model variables = {m.variables}")
    for unit, data in network.storage_units.loc[units_with_inflow].iterrows():
        M1 = int(np.ceil(upper.loc[snapshots, unit].max()))
        lhs1 = (
            m["StorageUnit-spill"].loc[snapshots, unit]
            - M1 * m["StorageUnit-spilling"].loc[snapshots, unit]
        )
        rhs1 = 0

        # Second constraint needs to be formulated differently if unit is extendable or not
        if data.p_nom_extendable:
            lhs2 = (
                M * m["StorageUnit-spilling"].loc[snapshots, unit]
                + data.max_hours * m["StorageUnit-p_nom"].loc[unit]
                - m["StorageUnit-state_of_charge"].loc[snapshots, unit]
            )
            rhs2 = M
        else:
            lhs2 = (
                M * m["StorageUnit-spilling"].loc[snapshots, unit]
                - m["StorageUnit-state_of_charge"].loc[snapshots, unit]
            )
            rhs2 = M - data.max_hours * data.p_nom

        m.add_constraints(
            lhs1,
            "<=",
            rhs1,
            name=f"GlobalConstraint-Storage_unit_{unit}_spill_seq_max_inflow_constraint_{snapshots[0]}",
        )
        m.add_constraints(
            lhs2,
            "<=",
            rhs2,
            name=f"GlobalConstraint-Storage_unit_{unit}_spill_iff_fully_charged_constraint_{snapshots[0]}",