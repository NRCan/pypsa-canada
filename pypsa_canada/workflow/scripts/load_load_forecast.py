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
        DEFAULT: Default load profile (directly in base model).
        FULL_LOAD: Loads a full load profile (in a .csv file).
        GROWTH_FORECAST: Load growth forecast is applied to base load profile for all investment periods.
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


def read_load_profile(
    load_mode: LoadProfile, load_growth_forecast: str
) -> pd.DataFrame:
    """
    Loads the load growth profile or forecast based on the specified profile type.

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
        case LoadProfile.DEFAULT:
            print("No load growth read for DEFAULT load profile")
        # Loads full load profile from model data
        case LoadProfile.FULL_LOAD:
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

        # Loads load growth forecast to apply to load profile
        case LoadProfile.GROWTH_FORECAST:
            print(f"Loading load growth path = {load_growth_forecast}")
            try:
                load_growth = pd.read_csv(load_growth_forecast, index_col=0)
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


def apply_load_profile(
    load_config: dict, investment_periods: list[int], initial_loads_p_set_path: str = None
) -> pd.DataFrame:
    """
    Apply load forecast based on configuration settings.

    Args:
        load_config: Load configuration dictionary
        initial_loads_p_set: Path to the initial load p_set CSV file (optional)

    Returns:
        DataFrame containing the updated load forecast data.

    Raises:
        NotImplementedError: If the selected load mode is not yet implemented.
        KeyError: If required configuration keys are missing.
    """
    load_mode: LoadProfile = LoadProfile[load_config["load_mode"].upper()]
    load_growth_forecast = load_config["load_growth_forecast"]

    print(f"Loading load profile: {load_mode.name}")
    load_growth = read_load_profile(
        load_mode=load_mode, load_growth_forecast=load_growth_forecast
    )
    match load_mode:
        # Keeps base model profile
        case LoadProfile.DEFAULT:
            raise Exception("Default load profile should not run add_loads")
        # Applies load_growth to network load
        case LoadProfile.FULL_LOAD:
            return load_growth
        # Applies load_growth to network for all investment periods
        case LoadProfile.GROWTH_FORECAST:
            initial_loads_p_set = pd.read_csv(
                initial_loads_p_set_path, index_col=0, parse_dates=[0]
            )
            return generate_load_profile_from_forecast(
                initial_loads_p_set, load_growth, investment_periods
            )
        case LoadProfile.CER:
            raise NotImplementedError("CER load profile processing not yet implemented")
        case LoadProfile.CODERS:
            raise NotImplementedError(
                "CODERS load profile processing not yet implemented"
            )
        case _:
            raise ValueError(f"Invalid load mode: {load_mode}")


def generate_load_profile_from_forecast(
    initial_load_df: pd.DataFrame,
    load_growth_forecast: pd.DataFrame,
    investement_periods: list[int],
) -> pd.DataFrame:
    """
    Apply interpolated load growth factors for all investment years.

    Applies year-specific growth factors from a forecast DataFrame, with linear
    interpolation between forecast years when needed. Returns a stacked DataFrame
    covering all specified years.

    Args:
        initial_load_df: Reference load data DataFrame (single year, up to 8760 rows).
        load_growth_forecast: Load growth forecast DataFrame with growth factors for specific years.
        years: List of investment years to apply growth for.

    Returns:
        DataFrame with scaled load values stacked across all years.
    """
    if initial_load_df.empty:
        return initial_load_df

    if initial_load_df.shape[0] > 8760:
        base_df = initial_load_df.iloc[0:8760, :].copy()
    else:
        base_df = initial_load_df.copy()

    if not isinstance(base_df.index, pd.DatetimeIndex):
        base_df.index = pd.to_datetime(base_df.index)

    base_df = base_df.astype(float)

    forecast_years = np.asarray(sorted(load_growth_forecast.columns.astype(int)))

    print("forecast_years for load growth:\n", forecast_years)

    def get_growth_factors(year: int) -> pd.Series:
        if year <= forecast_years[0]:
            return load_growth_forecast[str(forecast_years[0])].astype(float)
        if year >= forecast_years[-1]:
            return load_growth_forecast[str(forecast_years[-1])].astype(float)

        upper_idx = np.searchsorted(forecast_years, year, side="right")
        year_before = forecast_years[upper_idx - 1]
        year_after = forecast_years[upper_idx]
        map_dict_before = load_growth_forecast[str(year_before)].astype(float)
        map_dict_after = load_growth_forecast[str(year_after)].astype(float)

        return map_dict_before + (map_dict_after - map_dict_before) * (
            year - year_before
        ) / (year_after - year_before)

    annual_profiles = []
    base_year = base_df.index[0].year

    for year in investement_periods:
        growth_factors = get_growth_factors(year)
        scaled_df = base_df.mul(growth_factors.reindex(base_df.columns), axis=1)
        scaled_df.index = base_df.index + pd.DateOffset(years=year - base_year)
        annual_profiles.append(scaled_df)

    load_profile = pd.concat(annual_profiles)

    print(f"load_df after applying load growth:\n{load_profile}")

    return load_profile
