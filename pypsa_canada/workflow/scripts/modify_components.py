# scripts/add_loads.py
import logging
import sys
import traceback

from _benchmarks import (
    finish_benchmark_tracker,
    result_benchmark_csv_path,
    start_benchmark_tracker,
)
from helpers import setup_script_logging
from pypsa import Network

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
snakemake = globals().get("snakemake")
LOG_PATH = (
    str(snakemake.log[0])
    if snakemake is not None and snakemake.log
    else "logs/temp.log"
)


setup_script_logging(LOG_PATH)

config = snakemake.config if snakemake is not None else None


def modify_component(
    n: Network,
    component: str,
    name: str,
    col: str = None,
    value: str | int | float = None,
    action: str = "Modify",
):
    """
    Modify or delete a PyPSA component, and if the name contains 'OPT',
    apply the same action to all components with the same base name and a year suffix.

    Parameters
    ----------
    n : Network
        The PyPSA Network object to modify.
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
    if name not in n.c[component].static.index:
        raise ValueError(
            f"Component {component} with name {name} to {action} does not exist in the network."
        )

    df = n.c[component].static

    # List of component names to process
    names_to_process = [name]
    if "OPT" in name:
        # Add all components with the same base name and a year suffix
        suffix_matches = df.index[df.index.str.startswith(name + "-20")]
        names_to_process.extend(suffix_matches)

    if action.lower() == "modify":
        if col is None or value is None:
            raise ValueError(
                "For modification, 'column' and 'value' must be specified."
            )
        n.c[component].static.loc[names_to_process, col] = value

    elif action.lower() == "delete":
        n.remove(component, names_to_process)

    else:
        print(f"Invalid action '{action}' for component {component}: {name}")


def main():
    if snakemake is None:
        raise RuntimeError("modify_components.py must be executed by Snakemake")

    benchmark_timer, benchmark_memory = start_benchmark_tracker()

    network = Network(snakemake.input.input_data)

    modify_components = config.get("planning").get("modify_components", {})

    for component, components_dict in modify_components.items():
        if components_dict is not None:
            for component_name, component_dict in components_dict.items():
                if isinstance(component_dict, dict):
                    action = component_dict.pop("action", "Modify")
                    if action.lower() == "modify":
                        for col, value in component_dict.items():
                            modify_component(
                                n=network,
                                component=component,
                                name=component_name,
                                col=col,
                                value=value,
                                action="Modify",
                            )
                    elif action.lower() == "delete":
                        modify_component(
                            n=network,
                            component=component,
                            name=component_name,
                            action="Delete",
                        )

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)

    finish_benchmark_tracker(
        result_benchmark_csv_path(snakemake.output.planning_unsolved_network),
        "modify_components",
        benchmark_timer,
        benchmark_memory,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("modify_components failed:\n%s", traceback.format_exc())
        sys.exit(1)
