import logging
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import pypsa

# Official 2-letter codes for Canadian provinces and territories
CANADIAN_PROVINCES = {
    "AB",  # Alberta
    "BC",  # British Columbia
    "MB",  # Manitoba
    "NB",  # New Brunswick
    "NL",  # Newfoundland and Labrador
    "NS",  # Nova Scotia
    "NT",  # Northwest Territories
    "NU",  # Nunavut
    "ON",  # Ontario
    "PE",  # Prince Edward Island
    "QC",  # Quebec
    "SK",  # Saskatchewan
    "YT",  # Yukon
}


def validate_bus_provinces(network: "pypsa.Network") -> None:
    """
    Validate that every bus has a 'province' column with a valid Canadian province code.

    Raises
    ------
    ValueError
        If the 'province' column is missing or contains invalid values.
    """
    if "province" not in network.buses.columns:
        raise ValueError(
            "buses DataFrame is missing a 'province' column. "
            "Each bus must have a province assigned."
        )

    provinces_in_data = set(network.buses["province"].dropna().unique())
    invalid = provinces_in_data - CANADIAN_PROVINCES
    if invalid:
        raise ValueError(
            f"buses contain invalid province codes: {sorted(invalid)}. "
            f"Valid codes are: {sorted(CANADIAN_PROVINCES)}"
        )

    missing = network.buses["province"].isna()
    if missing.any():
        raise ValueError(
            f"The following buses are missing a province value: "
            f"{list(network.buses.index[missing])}"
        )

    logging.info(f"Bus province validation passed: {sorted(provinces_in_data)}")


def drop_inactive_assets(
    network: "pypsa.Network", period: int, components_to_deactivate: str | None = None
):
    """
    Function to drop all rows with inactive assets

    Parameters
    ----------
    network: pypsa.Network
        PyPSA network to be modified
    component : str
        String value from pypsa components list such as Generator, StorageUnits, etc.
    years: list[int]
        List containing all the investment periods
    """
    # for component in network.components.keys():
    for component in ["Generator", "StorageUnit", "Line", "Link"]:
        # active_elem = {}
        logging.debug(f"Component: {component}")
        c = network.components[component].static
        if not c.empty:
            active_c = c.eval("build_year <= @period < build_year + lifetime")
            inactive_elems = c.index[~active_c].tolist()
            logging.debug(f"Inactive_elems = {inactive_elems}")
            network.df(component).drop(labels=inactive_elems, inplace=True)
            logging.debug(f"Active components = {network.df(component)}")
        else:
            logging.debug(f"DataFrame {component} is empty")


def apply_generator_preprocess_toggles(
    network: "pypsa.Network", stage_config: dict
) -> "pypsa.Network":
    """
    Apply generator preprocessing toggles and normalize power-limit time-series.

    Parameters
    ----------
    network : pypsa.Network
        Network whose generator and time-series tables will be updated.
    stage_config : dict
        Stage configuration dictionary (planning or dispatch section).

    Returns
    -------
    pypsa.Network
        Network with generator columns conditionally removed and power-limit
        time-series coerced to numeric values.
    """
    generators = network.generators

    if not generators.empty:
        enable_committable = stage_config["enable_committable"]
        enable_p_min_pu = stage_config["enable_p_min_pu"]
        enable_ramp_rates = stage_config["enable_ramp_rates"]

        columns_to_drop: list[str] = []

        if not enable_committable:
            if "committable" in generators.columns:
                generators.loc[:, "committable"] = False
            if "up_time_before" in generators.columns:
                generators.loc[:, "up_time_before"] = 0
            if "down_time_before" in generators.columns:
                generators.loc[:, "down_time_before"] = 0
            columns_to_drop.extend(
                [
                    "min_up_time",
                    "min_down_time",
                    "ramp_limit_start_up",
                    "ramp_limit_shut_down",
                ]
            )

        if not enable_p_min_pu:
            columns_to_drop.append("p_min_pu")

        if not enable_ramp_rates:
            columns_to_drop.extend(["ramp_limit_up", "ramp_limit_down"])

        existing_columns_to_drop = [
            column for column in columns_to_drop if column in generators.columns
        ]
        if existing_columns_to_drop:
            logging.info(
                "Removing generator columns due to preprocess toggles: %s",
                existing_columns_to_drop,
            )
            network.generators = generators.drop(columns=existing_columns_to_drop)

    # Keep time-series power-limit tables numeric to avoid PyPSA consistency
    # checks failing on object-typed dense arrays.
    def _coerce_df(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return df
        return df.apply(pd.to_numeric, errors="coerce")

    if hasattr(network, "generators_t"):
        if hasattr(network.generators_t, "p_min_pu"):
            p_min_df = network.generators_t.p_min_pu
            if p_min_df.empty and "p_min_pu" not in network.generators.columns:
                # With no static p_min_pu and empty time-series, PyPSA can construct
                # object-typed dense min_pu during consistency checks.
                network.generators_t.p_min_pu = pd.DataFrame(
                    0.0,
                    index=network.snapshots,
                    columns=network.generators.index,
                    dtype=float,
                )
            else:
                network.generators_t.p_min_pu = _coerce_df(p_min_df).fillna(0.0)
        if hasattr(network.generators_t, "p_max_pu"):
            network.generators_t.p_max_pu = _coerce_df(
                network.generators_t.p_max_pu
            ).fillna(0.0)

    if hasattr(network, "links_t"):
        if hasattr(network.links_t, "p_min_pu"):
            network.links_t.p_min_pu = _coerce_df(network.links_t.p_min_pu).fillna(0.0)
        if hasattr(network.links_t, "p_max_pu"):
            network.links_t.p_max_pu = _coerce_df(network.links_t.p_max_pu).fillna(0.0)

    return network


# def switch_committables(network:pypsa.Network, state:bool=True):
#         #Set all committables components to True
#     network.generators.loc[
#         network.generators.carrier.isin(['coal', 'gas', 'nuclear']),
#         'committable'
#     ] = state
#     network.links.loc[:,'committable'] = state
#     network.storage_units.loc[:,'committable'] = state
#     network.stores.loc[:,'committable'] = state


# def switch_extendables(network:pypsa.Network, state:bool=False):
#     network.generators.loc[
#         network.generators.carrier.isin(['coal', 'gas', 'nuclear']),
#         'extendable'
#     ] = state
#     network.links.loc[:,'extendable'] = state
#     network.storage_units.loc[:,'extendable'] = state
#     network.stores.loc[:,'extendable'] = state
