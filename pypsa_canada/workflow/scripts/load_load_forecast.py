from enum import Enum

import pandas as pd


class LoadGrowthFileMissing(Exception):
    """Exception raised when a required load growth file is missing or invalid."""

    def __init__(self, message=None):
        self.message = message
        super().__init__(message)


class LoadProfile(Enum):
    """
    Enumeration of available load profile types.

    Attributes:
        DEFAULT: Default load forecast from model data.
        CUSTOM: Custom user-provided load forecast.
        CER: Canada Energy Regulator load forecast (not yet implemented).
        CODERS: CODERS load forecast (not yet implemented).
    """

    DEFAULT = 1
    CUSTOM = 2
    CER = 3
    CODERS = 4


def load_year_forecast(load_growth_forecast: str, year: list[int]) -> pd.DataFrame:
    """
    Load load growth forecast data for specific years.

    Args:
        load_growth_forecast: Path to the load growth CSV file.
        year: List of years to filter the forecast data.

    Returns:
        DataFrame containing load growth data for the specified years.

    Raises:
        FileNotFoundError: If the load growth file doesn't exist.
        LoadGrowthFileMissing: If the file is invalid or cannot be parsed.
    """
    load_growth = pd.read_csv(load_growth_forecast, index_col=0, parse_dates=[0])
    return load_growth[load_growth.index.year.isin(year)]


def load_load_forecast(
    load_mode: LoadProfile, load_growth_forecast: str
) -> pd.DataFrame:
    """
    Load load growth forecast based on the specified profile type.

    Args:
        load_mode: Type of load profile to use (from LoadProfile enum).
        load_growth_forecast: Path to the load growth CSV file.

    Returns:
        DataFrame containing the load growth forecast data.

    Raises:
        LoadGrowthFileMissing: If the load growth filepath is missing or invalid.
        NotImplementedError: If the selected load mode is not yet implemented.
    """
    if not load_growth_forecast and load_mode in {
        LoadProfile.DEFAULT,
        LoadProfile.CUSTOM,
    }:
        raise LoadGrowthFileMissing("No load growth filepath provided")

    match load_mode:
        # Loads default load forecast from csv file
        case LoadProfile.DEFAULT:
            print(f"Loading load growth path = {load_growth_forecast}")
            try:
                load_growth = pd.read_csv(
                    load_growth_forecast, index_col=0, parse_dates=[0]
                )
            except FileNotFoundError:
                raise LoadGrowthFileMissing(
                    f"Load growth file not found at {load_growth_forecast}"
                )
            load_growth = load_growth.set_index("name")

        # Loads custom load forecast from user-provided CSV file
        case LoadProfile.CUSTOM:
            print(f"Loading load growth path = {load_growth_forecast}")
            try:
                load_growth = pd.read_csv(
                    load_growth_forecast, index_col=0, parse_dates=[0]
                )
            except FileNotFoundError:
                raise LoadGrowthFileMissing(
                    f"Load growth file not found at {load_growth_forecast}"
                )
            # TODO: check why this is used in old workflow
            # load_growth = load_growth[load_growth.index.year.isin(specific_year)]

        case LoadProfile.CER:
            raise NotImplementedError("Unimplemented")
        case LoadProfile.CODERS:
            raise NotImplementedError("Unimplemented")
        case _:
            raise Exception("Invalid load mode")

    return load_growth
