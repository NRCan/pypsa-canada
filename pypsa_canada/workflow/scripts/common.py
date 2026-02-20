import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pypsa

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
