import logging
import os
import sys
import traceback

import pandas as pd
import pint
from helpers import setup_script_logging
from pypsa import Network

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"


setup_script_logging(LOG_PATH)

config = snakemake.config


def create_extra_load_p_set(network, extra_load_config):
    """
    Create Pandas dataframes from csv files to add like an extra load.

    Parameters
    ----------
    path : str
        Path of the file or folder where are the csv files we want to sum.

    Returns
    -------
    Pd.Dataframe
        return a Dataframe from all the csv file together.
    """
    p_set_loads = []
    path = extra_load_config["path"]

    path = os.path.dirname(path)
    for filename in os.listdir(os.path.abspath(path)):
        bus_heat_load = pd.read_csv(os.path.join(path, filename))
        rows_title = []
        for index, row in bus_heat_load.iterrows():
            rows_title.append(row["PyPSA_Buse"])
        p_set_load = pd.DataFrame()
        bus_heat_load.set_index("PyPSA_Buse")
        for columns in bus_heat_load.columns:
            if columns.isdigit():
                new_row = {}
                for bus in rows_title:
                    index = bus_heat_load.index[bus_heat_load["PyPSA_Buse"] == bus][0]
                    bus_heat_mg = convert_peta_joule_to_mega_watts(
                        bus_heat_load.loc[index, columns]
                    )
                    new_row[bus + " Load"] = bus_heat_mg / 8760
                temp_df = pd.DataFrame([new_row] * 8760)
                p_set_load = pd.concat([p_set_load, temp_df], ignore_index=True)

        p_set_load.columns.name = "Load"
        p_set_loads.append(p_set_load)
    return sum(p_set_loads)


def convert_peta_joule_to_mega_watts(peta):
    """
    Convert peta joule to mega watts per hour

    Parameters
    ----------
    peta : float
        Float that represent the peta joule.

    Returns
    -------
    float
        Returns mega watts per hour
    """
    ureg = pint.UnitRegistry()
    energy_peta_joule = peta * ureg.petajoule
    seconds = (1 * ureg.hour).to(ureg.second)
    power_mw = (energy_peta_joule / seconds).to(ureg.megawatt)

    return power_mw.magnitude


def add_extra_load_p_set(network, extra_load_config):
    """
    Adding an extra load to the current load on the planning inputs.

    Parameters
    ----------
    extra_load : Pd.Dataframe
        Extra load in a dataframe from a file of external load.
    """
    extra_load = extra_load_config["extra_load"]

    extra_load.index = network.loads_t.p_set.index
    network.loads_t.p_set = network.loads_t.p_set.add(extra_load, fill_value=0)
    network.loads_t.p_set = network.loads_t.p_set.round(0)


def main():
    network = Network(snakemake.input.input_data)
    # network_ref = network.copy()
    extra_load_config = config["extra_loads"]

    if extra_load_config["is_used"]:
        network = create_extra_load_p_set(network, extra_load_config)
        network = add_extra_load_p_set(network, extra_load_config)

    network.export_to_netcdf(snakemake.output.planning_unsolved_network)
    if config["run"]["export_csv"]:
        network.export_to_csv_folder(snakemake.output.planning_unsolved_network_csv)

    return


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_extra_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
