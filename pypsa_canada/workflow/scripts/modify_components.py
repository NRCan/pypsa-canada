# scripts/add_loads.py
import logging
import os
import sys
import traceback

from helpers import setup_script_logging
from pypsa import Network

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"


setup_script_logging(LOG_PATH)

config = snakemake.config


def modify_component(self, component, name, col=None, value=None, action="Modify"):
    """
    Modify or delete a PyPSA component, and if the name contains 'OPT',
    apply the same action to all components with the same base name and a year suffix.

    Parameters
    ----------
    component : str
        PyPSA component type (Generator, StorageUnit, Line, Link).
    name : str
        Name of the component to modify or delete.
    col : str, optional
        Column to be modified.
    value : [int, float, str], optional
        New value to assign.
    action : str, optional
        Either "Delete" or "Modify", default is "Modify".
    """
    if name not in self.network.df(component).index:
        raise ValueError(
            f"Component {component} with name {name} to {action} does not exist in the network."
        )

    df = self.network.df(component)

    # List of component names to process
    names_to_process = [name]
    if "OPT" in name:
        # Add all components with the same base name and a year suffix
        suffix_matches = df.index[df.index.str.startswith(name + "-20")]
        names_to_process.extend(suffix_matches)

    if action == "Modify":
        if col is None or value is None:
            raise ValueError(
                "For modification, 'column' and 'value' must be specified."
            )
        df.loc[names_to_process, col] = value
        if component == "Generator":
            self.network.generators = df
        elif component == "StorageUnit":
            self.network.storage_units = df
        elif component == "Line":
            self.network.lines = df
        elif component == "Link":
            self.network.links = df

    elif action == "Delete":
        self.network.mremove(component, names_to_process)

    else:
        print(f"Invalid action '{action}' for component {component}: {name}")


def main():
    network = Network(snakemake.input.input_data)

    # Components modification
    modify_components = {
        "Link": {},
        "Generator": {},
        "StorageUnit": {},
        "Line": {},
    }

    for component, components_dict in modify_components.items():
        if components_dict is not None:
            for component_name, component_dict in components_dict.items():
                if isinstance(component_dict, dict):
                    for col, value in component_dict.items():
                        network = modify_component(
                            component=component,
                            name=component_name,
                            col=col,
                            value=value,
                            action="Modify",
                        )
                elif component_dict == "Delete":
                    network = modify_component(
                        component=component, name=component_name, action="Delete"
                    )

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)

    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("modify_components failed:\n%s", traceback.format_exc())
        sys.exit(1)
