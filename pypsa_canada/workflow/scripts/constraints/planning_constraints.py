import logging
import os
import warnings

# from pypsa.descriptors import get_active_assets, get_extendable_i
from pathlib import Path

import pandas as pd
import pypsa
from linopy.expressions import merge

# from pypsa.descriptors import get_active_assets, get_extendable_i
from xarray import DataArray

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s %(name)s %(levelname)s:%(message)s"
)
logger = logging.getLogger(__name__)


def add_CER_constraint_planning(network, snapshots, constraint, groups, CER_gens, year):
    """
    Function to add the CER constraint according to the option parameters given.

    Parameters
    ----------
    constraint : dataframe
        CER constraint parameters
    network : pypsa.Network
        The pypsa network class sent as an object
    snapshots : list
        list containing all snapshots affected
    groups : list
        list containing CER generators group
    CER_gens : dataframe
        dataframe containing the generators concerned by the constraint with their group associated to
    year : int
        Investment year concerned by the emission limit

    Returns
    -------
    boolean
        Zero value if constraint is added
    """
    m = network.model

    # Set the limit and offset based on the year
    limit, offset = None, None
    for limit_year in constraint["values"]["limit"]:
        if year >= int(limit_year):
            limit = constraint["values"]["limit"][limit_year]
            offset = constraint["values"]["offset"][limit_year]
            continue
        else:
            if limit is not None and offset is not None:
                break
            else:
                raise ValueError(
                    f"No limit or offset found for year {year} in constraint values."
                )

    for group in groups:
        gens = CER_gens[CER_gens.group == group]
        weightings = network.snapshot_weightings.loc[snapshots]
        weightings = DataArray(weightings.objective[snapshots]).sel(period=year)
        unit = "tCO2eq"

        # Implementing single constraint for both existing and extendable generators
        emission_cap_existing = 0
        emission_cap_extendable = 0
        emissions_existing = 0
        emissions_extendable = 0

        for gen, data in gens.iterrows():
            if data.p_nom_extendable:
                emission_cap_extendable += (
                    (limit + offset) * m["Generator-p_nom"].loc[gen] * 8760 / 1000
                )
                emissions_extendable += (
                    m["Generator-p"].loc[snapshots, gen].sel(period=year) * weightings
                ).sum() * (
                    network.carriers.loc[data.carrier].co2_emissions / data.efficiency
                )
            else:
                emission_cap_existing += (limit + offset) * data.p_nom * 8760 / 1000
                emissions_existing += (
                    m["Generator-p"].loc[snapshots, gen].sel(period=year) * weightings
                ).sum() * (
                    network.carriers.loc[data.carrier].co2_emissions / data.efficiency
                )

        lhs = emissions_extendable + emissions_existing - emission_cap_extendable
        rhs = emission_cap_existing
        print(f"{group} generators included in CER constraint in {year}:", gens.index)
        m.add_constraints(
            lhs,
            "<=",
            rhs,
            name=f"GlobalConstraint-CER_constraint_{group}_{unit}_{year}_dynamic",
        )
        # print(f"CER_constraint_{group}_{unit}_{year}")
        # print(lhs)
        # print(rhs)
    return 0


def add_planning_reserve_margin(
    network: "pypsa.Network",
    year: int,
    # snapshots: pd.DatetimeIndex | pd.MultiIndex,
    province: str,
    margin: float = 1.2,
    capacity_values_filepath: str = None,
):
    """
    Function to add a planning reserver margin constraint.
    This function will force the simulation to generate more
    than the peak load with a % reserve margin added. The
    function will verify if there are any active asset (generators, cascade
    hydro links and storage for now) for this investment period to add
    the constraint. If there are none, it will exit this function.

    Parameters
    ----------
    m : Linopy.model
        The linopy model property from the pypsa network
    network : pypsa.Network
        The pypsa network class sent as an object
    year : int
        The current investment period
    margin : float, optional
        Decimal value defined as the margin multiplier, by default 1.2
    province : str
        Province for which to add planning reserve margin constraint

    Returns
    -------
    boolean
        Zero value if constraint is added
    """
    m = network.model

    # Calculate reserve margin load from peak
    if "province" in network.buses.columns:
        bus_province_list = list(
            network.buses.index[network.buses.province == province]
        )
    else:
        bus_province_list = list(
            network.buses.index[[province in x for x in network.buses.index]]
        )

    load_province_list = list(
        network.loads_t.p_set.columns[
            [province in x for x in network.loads_t.p_set.columns]
        ]
    )
    # logger.info(f"network.loads_t.p_set={network.loads_t.p_set}")

    peakdemand = (
        network.loads_t.p_set.loc[:, load_province_list].loc[year].sum(axis=1).max()
    )
    reserve_margin = peakdemand * margin
    logger.info(f"Bus_province_list={bus_province_list}")
    logger.info(f"load_province_list={load_province_list}")

    logger.info(
        f"Maximum peak demand {province} = {peakdemand} MW and margin = {margin}"
    )
    logger.info(f"Reserve margin of {province} estimated to: {reserve_margin} MW")

    # Import file with capacity value (fractional) vs. carrier/model
    # Check for custom data folder path from environment variable
    # custom_data_folder = os.environ.get("PYPSA_CUSTOM_DATA_FOLDER")
    # data_filepath = os.path.join(custom_data_folder, "data", "constraints", capacity_values_filepath)
    data_filepath = os.path.join(str(Path.cwd()), str(capacity_values_filepath))

    capacity_value_by_carrier = pd.read_csv(data_filepath, index_col="Carrier")
    capacity_value_by_carrier.columns = capacity_value_by_carrier.columns.astype(int)
    print(f"Capacity value by carrier = {capacity_value_by_carrier}")
    # Initialize both sides of constraint
    lhs = []
    rhs = reserve_margin

    # Calculate the capacity value of each type of component
    components_list = ["Generator", "StorageUnit", "Link"]
    for component in components_list:
        df = network.df(component).copy()
        if df.empty:
            continue

        if component != "Link":
            # def get_capacity_value(row):
            #     try:
            #         return capacity_value_by_carrier.loc[row.model, year]
            #     except KeyError as e:
            #         print(f"KeyError: {e}")
            #         print(f"  Problem at row index: {row.name}")
            #         print(f"  Row data: {row.to_dict()}")
            #         print(f"  Looking for model='{row.model}', year={year}")
            #         print(f"  Available models: {capacity_value_by_carrier.index.tolist()}")
            #         print(f"  Available years: {capacity_value_by_carrier.columns.tolist()}")
            #         raise

            # df["capacity_value_fractional"] = df.apply(get_capacity_value, axis=1)

            # Create a mapping dictionary from the year column
            capacity_map = (
                capacity_value_by_carrier[year].to_dict()
                if year in capacity_value_by_carrier.columns
                else {}
            )

            # Check for models not in the mapping dictionary
            missing_models = df[~df["model"].isin(capacity_map.keys())][
                "model"
            ].unique()
            if len(missing_models) > 0:
                logger.warning(
                    f"Models not found in capacity_value_by_carrier for year {year}: {missing_models.tolist()}"
                )
                logger.warning(
                    "  These models will be assigned capacity_value_fractional = 0"
                )

            df["capacity_value_fractional"] = df["model"].map(capacity_map).fillna(0)
            # df["capacity_value_fractional"] = df.apply(
            #     lambda row: capacity_value_by_carrier.loc[row.model, year], axis=1
            # )
            df["capacity_value"] = df["p_nom"] * df["capacity_value_fractional"]
            df = df.loc[df.bus.isin(bus_province_list)]

        else:
            df = df[df.index.str.contains("_turbine_link")]
            df["capacity_value_fractional"] = capacity_value_by_carrier.loc[
                "hydro_storage", year
            ]
            df["capacity_value"] = df["p_nom"] * df["capacity_value_fractional"]
            df = df.loc[df.bus1.isin(bus_province_list)]

        df = df[
            (df.build_year + df.lifetime > int(year)) & (df.build_year <= int(year))
        ]
        print(f"DF {component} = {df}")
        if df.empty:
            continue

        existing_cap_value = df.capacity_value.sum()

        # Compute right-hand side of constraint requiring extendable gen capacity value (total) be greater or equal to reserve margin minus existing gen total capacity value
        rhs -= existing_cap_value
        print(f"Existing {component} cap_value for {province} = {existing_cap_value}")
        print(f"RHS = {rhs}")
        logger.debug(
            f"Existing {component} cap_value for {province} = {existing_cap_value}"
        )
        logger.debug(f"List of {component} for reserve margin: {df.index}")

        # Skip if reserve margin has been satisfied
        if rhs <= 0:
            print(f"Reserve margin satisfied for {province} in {year}, skipping")
            return

        # Get extendable components
        ext_comp = df[df.p_nom_extendable]
        logger.debug(
            f"Numbers of Extensible {component} for {province}={len(ext_comp.index)}"
        )
        if ext_comp.empty:
            continue

        # Want to multiply p_noms in model by fractional capacity values to get left-hand side (lhs) of constraint
        lhs.append(
            (
                m[f"{component}-p_nom"].loc[ext_comp.index]
                * ext_comp.capacity_value_fractional
            ).sum()
        )

    if lhs:
        lhs = merge(lhs)
        m.add_constraints(
            lhs,
            ">=",
            rhs,
            name=f"GlobalConstraint-Planning_reserve_margin_{year}_{province}",
        )
    else:
        warnings.warn(
            f"Warning: No valid extendable units for reserve in {province} {year}, check inputs"
        )
    return 0


def add_emission_constraint_planning(network, snapshots, emissions_limit, year):
    """
    Function to add Net-Zero constraint in planning, it's a global emissions limit on all the network for a correspunding investment year.

    Parameters
    ----------
    m : Linopy.model
        The linopy model property from the pypsa network
    network : pypsa.Network
        The pypsa network class sent as an object
    snapshots : list
        list containing all snapshots affected
    emissions_limit : float
        Emissions limit value for the correspunding year in MtCO2eq
    year : int
        Investment year concerned by the emission limit

    Returns
    -------
    boolean
        Zero value if constraint is added
    """
    m = network.model

    carriers = network.carriers[network.carriers.co2_emissions != 0].index.to_list()
    gens = network.generators[network.generators.carrier.isin(carriers)]
    sus = network.storage_units[network.storage_units.carrier.isin(carriers)]
    weightings = network.snapshot_weightings.loc[snapshots]
    weightings = DataArray(weightings.objective[snapshots]).sel(period=year)
    emissions_gen = 0
    emissions_su = 0

    for gen, data in gens.iterrows():
        emissions_gen += (
            m["Generator-p"].loc[snapshots, gen].sel(period=year) * weightings
        ).sum() * (network.carriers.loc[data.carrier].co2_emissions / data.efficiency)
    for su, data in sus.iterrows():
        emissions_su += (
            m["StorageUnit-p_store"].loc[snapshots, su].sel(period=year) * weightings
        ).sum() * (
            network.carriers.loc[data.carrier].co2_emissions * data.efficiency_store
        )

    lhs = emissions_gen + emissions_su
    rhs = emissions_limit

    m.add_constraints(
        lhs,
        "<=",
        rhs,
        name=f"GlobalConstraint-Emissions_Limit_{year}_{emissions_limit}_tCO2eq_dynamic",
    )
    return 0


def component_capacity_expansion_constraint(network, constraints_csv_filepath: str):
    """
    Function to add min/max on component expansion based on carrier,
    work-around for pypsa global_constraints since they don't work properly
    """
    m = network.model
    file_path = os.path.join(str(Path.cwd()), str(constraints_csv_filepath))

    logger.info(f"Custom filepath = {file_path}")
    if os.path.exists(file_path):
        custom_constraints = pd.read_csv(file_path, index_col=0)
        logger.info(f"custom_constraints = {custom_constraints}")
    else:
        raise FileNotFoundError(
            f"Error: custom_constraints.csv not found at {file_path}, skipping component capacity expansion constraints"
        )
    custom_constraints = custom_constraints[
        custom_constraints.type == "capacity_expansion_limit"
    ]
    # custom_constraints = custom_constraints[
    #     custom_constraints.constraint_group.isin(constraints)
    # ]

    logger.info("Adding custom constraint (step1) before loop")
    for constraint, data in custom_constraints.iterrows():
        # components = network.df(data.component_type).copy()
        components = network.components[data.component_type].static

        if data.year not in network.investment_periods:
            warnings.warn(
                f"Warning: {constraint} {data.year} not in investment periods, skipping"
            )
            continue

        # Get existing capacity
        if data.bus != "All":
            if "->" in data.bus:
                buses = data.bus.split("->")
                components = components[
                    (components.bus0.isin(buses) & components.bus1.isin(buses))
                ]
            else:
                components = components[components.bus == data.bus]

        components = components[components[data.attribute] == data.attribute_name]
        components = components.loc[
            (components.build_year + components.lifetime > int(data.year))
            & (components.build_year <= int(data.year))
        ]

        if components.empty:
            warnings.warn(
                f"Warning: {constraint} no components of type {data.component_type}, skipping"
            )
            continue

        if data.include_existing:
            existing_cap = components.p_nom.sum()
        else:
            existing_cap = 0

        rhs = data.value - existing_cap

        # If constraint is satisfied/violated by existing capacity, skip constraint
        if rhs <= 0:
            if data.sense == "<=":
                warnings.warn(
                    f"Warning: {constraint} existing capacity of {existing_cap}MW exceeds constraint in year {data.year}, setting extendable to 0"
                )
                rhs = 0
            elif data.sense == ">=":
                print(
                    f"{constraint} constraint already met by {existing_cap}MW of existing capacity, skipping"
                )
                continue

        # Sum capacity of extendable components
        extendable_comps = components[components.p_nom_extendable]
        lhs = m[f"{data.component_type}-p_nom"].loc[extendable_comps.index].sum()

        # Add constraint
        m.add_constraints(
            lhs,
            data.sense,
            rhs,
            name=f"{data.component_type}_cap_const-{constraint}",
        )
    return 0


def add_bidirection_link_constraint_OPT(network: "pypsa.Network", links: pd.DataFrame):
    """
    Function to add a constraint for extendable transmission lines such that the capacity is equal in both directions

    Parameters
    ----------
    links : pd.DataFrame
        dataframe containing the OPT transmission links
    network : pypsa.Network
        The pypsa network class sent as an object
    """
    m = network.model

    unique_links = links.assign(
        pair=links.apply(
            lambda r: tuple(sorted([r.bus0, r.bus1, str(r.build_year)])), axis=1
        )
    ).drop_duplicates("pair")
    print(unique_links)

    pairs = []
    for link_fwd, data in unique_links.iterrows():
        link_bck = links[
            (links.bus0 == data.bus1)
            & (links.bus1 == data.bus0)
            & (links.build_year == data.build_year)
        ]
        if not link_bck.empty:
            pairs.append((link_fwd, link_bck.index[0]))

    pairs = pd.DataFrame(
        pairs,
        columns=["fwd", "bck"],
    )

    lhs = m["Link-p_nom"].loc[pairs["fwd"].values]
    rhs = m["Link-p_nom"].loc[pairs["bck"].values]
    exp = lhs - rhs

    m.add_constraints(
        exp == 0,
        name="OPT_link_pnom_equality",
    )

    # for link_fwd, data in unique_links.iterrows():
    #     link_bck = links[(links.bus0 == data.bus1) & (links.bus1 == data.bus0) & (links.build_year == data.build_year)]
    #     if not link_bck.empty:
    #         link_bck = link_bck.iloc[0].name
    #         # P_nom equality for extendable links in planning mode
    #         link0_p_nom = m["Link-p_nom"].loc[link_fwd]
    #         link1_p_nom = m["Link-p_nom"].loc[link_bck]
    #         m.add_constraints(
    #             link0_p_nom,
    #             "==",
    #             link1_p_nom,
    #             name=f"Pnom_equality_of_{link_fwd}_{link_bck}_{data.build_year}_links",
    #         )
