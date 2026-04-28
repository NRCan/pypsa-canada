from enum import Enum

import numpy as np
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
        FULL_LOAD: Full load forecast from model data.
        CER: Canada Energy Regulator load forecast (not yet implemented).
        CODERS: CODERS load forecast (not yet implemented).
    """

    DEFAULT = 1
    FULL_LOAD = 2
    GROWTH_FORECAST = 3
    CER = 4
    CODERS = 5


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


def apply_load_growth_from_forecast(
    load_df: pd.DataFrame,
    load_growth_node: pd.DataFrame,
    years: list[int],
) -> pd.DataFrame:
    """
    Apply interpolated load growth factors for all investment years.

    Applies year-specific growth factors from a forecast DataFrame, with linear
    interpolation between forecast years when needed. Returns a stacked DataFrame
    covering all specified years.

    Args:
        load_df: Reference load data DataFrame (single year, up to 8760 rows).
        load_growth_node: Pre-loaded load growth forecast DataFrame.
        years: List of investment years to apply growth for.

    Returns:
        DataFrame with scaled load values stacked across all years.
    """
    if load_df.shape[0] > 8760:
        base_df = load_df.iloc[0:8760, :].copy()
    else:
        base_df = load_df.copy()

    forecast_years = np.asarray(load_growth_node.columns.astype(int))

    print("forecast_years for load growth:\n", forecast_years)

    map_dict = {}
    # Loads the csv file into a dict
    for year in years:
        for i, year_after in enumerate(forecast_years):
            # Ignore reference year
            if year > year_after:
                continue

            # Grab 2021
            elif year == year_after:
                map_dict = load_growth_node[str(year)]
                break
            elif year < year_after:
                year_before = forecast_years[i - 1]
                map_dict_before = load_growth_node[str(year_before)]
                map_dict_after = load_growth_node[str(year_after)]
                map_dict = map_dict_before + (map_dict_after - map_dict_before) * (
                    year - year_before
                ) / (year_after - year_before)
                break
    print(f"map_dict for load growth:\n{map_dict}")

    for key, value in map_dict.items():
        print(f"for key = {key}, value = {value}")
        base_df.loc[:, key] = base_df[key] * value

    n = years.index(year)
    load_df.loc[(year)] = base_df.astype(float).values
    load_df.iloc[8760 * n : (8760) * (n + 1)] = base_df.astype(float).values

    print(f"load_df after applying load growth:\n{load_df}")

    return load_df


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
    match load_mode:
        # Loads full load forecast from model data
        case LoadProfile.FULL_LOAD | LoadProfile.DEFAULT:
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

        case  LoadProfile.GROWTH_FORECAST:
            print(f"Loading load growth path = {load_growth_forecast}")
            try:
                load_growth = pd.read_csv(
                    load_growth_forecast, index_col=0
                )
            except FileNotFoundError:
                raise LoadGrowthFileMissing(
                    f"Load growth file not found at {load_growth_forecast}"
                )

        case LoadProfile.CER:
            raise NotImplementedError("Unimplemented")
        case LoadProfile.CODERS:
            raise NotImplementedError("Unimplemented")
        case _:
            raise Exception("Invalid load mode")

    return load_growth
