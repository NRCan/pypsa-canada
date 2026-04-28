# scripts/add_loads.py
import logging
import sys
import traceback

import pandas as pd
from helpers import setup_script_logging
from load_load_forecast import LoadProfile, load_load_forecast

# Snakemake injects a global `snakemake` object when using `script:`.
# It contains paths declared in the rule (input, output, log, params, threads, resources, etc.).
LOG_PATH = str(snakemake.log[0]) if snakemake.log else "logs/temp.log"


setup_script_logging(LOG_PATH)

config = snakemake.config


def apply_forecast_load(load_config: dict) -> pd.DataFrame:
    """
    Apply load forecast based on configuration settings.

    Args:
        load_config: Load configuration dictionary

    Returns:
        DataFrame containing the updated load forecast data.

    Raises:
        NotImplementedError: If the selected load mode is not yet implemented.
        KeyError: If required configuration keys are missing.
    """
    load_mode: LoadProfile = LoadProfile[load_config["load_mode"].upper()]
    load_growth_forecast = load_config["load_growth_forecast"]

    print(f"Loading load profile: {load_mode.name}")
    load_growth = load_load_forecast(load_mode, load_growth_forecast)

    match load_mode:
        case LoadProfile.DEFAULT:
            raise NotImplementedError(
                "DEFAULT load profile processing not yet implemented"
            )
        case LoadProfile.FULL_LOAD:
            return load_growth
        case LoadProfile.GROWTH_FORECAST:
            return load_growth
        case LoadProfile.CER:
            raise NotImplementedError("CER load profile processing not yet implemented")
        case LoadProfile.CODERS:
            raise NotImplementedError(
                "CODERS load profile processing not yet implemented"
            )
        case _:
            raise ValueError(f"Invalid load mode: {load_mode}")


def main():
    load_config = config["load"]
    loads_p_set_updated = apply_forecast_load(load_config)
    loads_p_set_updated.to_csv(snakemake.output.loads_p_set)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Log the full traceback to the log file and ensure a non-zero exit code
        logging.error("add_loads failed:\n%s", traceback.format_exc())
        sys.exit(1)
