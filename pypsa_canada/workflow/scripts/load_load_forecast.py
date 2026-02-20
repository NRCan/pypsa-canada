from enum import Enum

import pandas as pd


class LoadGrowthFileMissing(Exception):
    def __init__(self, message=None):
        self.message = message
        super().__init__(message)


class LoadProfile(Enum):
    DEFAULT = 1
    CUSTOM = 2
    CER = 3
    CODERS = 4


def load_load_forecast(
    load_mode: LoadProfile, load_growth_filepath, specific_year
) -> pd.DataFrame:
    load_growth: pd.DataFrame

    match load_mode:
        case LoadProfile.DEFAULT:
            if load_growth_filepath is not None:
                print(f"Loading load growth path = {load_growth_filepath}")
                load_growth = pd.read_csv(
                    load_growth_filepath, index_col=0, parse_dates=[0]
                )
                load_growth = load_growth.set_index("name")
            else:
                raise Exception("No load growth filepath")
        case LoadProfile.CUSTOM:
            print(f"Loading load growth path = {load_growth_filepath}")
            load_growth = pd.read_csv(
                load_growth_filepath, index_col=0, parse_dates=[0]
            )
            load_growth = load_growth[load_growth.index.year.isin(specific_year)]
        case LoadProfile.CER:
            raise Exception("Unimplemented")
        case LoadProfile.CODERS:
            raise Exception("Unimplemented")
        case _:
            raise Exception("Invalid load mode")

    return load_growth
