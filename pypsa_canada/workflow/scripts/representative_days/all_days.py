import pandas as pd
import pypsa


def all_days_method(network: pypsa.Network) -> pd.DataFrame:
    """Return a unit-weighting dataframe for all existing snapshots."""
    print(
        "Applying ALL_DAYS snapshot selection method: keeping all snapshots with unit weightings."
    )
    snap_df = network.snapshot_weightings.copy()
    # periods = np.unique(snap_df.index.get_level_values("period"))

    snap_df.loc[:, ["objective", "stores", "generators"]] = 1
    return snap_df
