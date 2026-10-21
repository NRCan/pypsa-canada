import numpy as np
import pandas as pd
from representative_days.kmedoid_quad import _fit_kmedoids
from representative_days.snapshot_selection import snapshots_selection


def test_all_days_keeps_snapshots_and_sets_unit_weightings(minimal_planning_network):
    network = minimal_planning_network
    original_snapshots = network.snapshots.copy()

    network.snapshot_weightings.loc[:, ["objective", "stores", "generators"]] = [
        2,
        3,
        4,
    ]

    snapshots_selection(network, {"method": "ALL_DAYS"})

    pd.testing.assert_index_equal(network.snapshots, original_snapshots)
    assert (network.snapshot_weightings == 1).all().all()


def test_kmedoids_selects_observed_representative_days():
    data = pd.DataFrame(
        [
            [0.0, 1.0, 2.0, 3.0, 2.0, 1.0],
            [0.2, 1.0, 2.1, 3.0, 2.0, 0.9],
            [-0.1, 0.9, 1.9, 3.1, 2.2, 1.0],
            [0.1, 1.1, 2.0, 2.9, 1.8, 1.2],
            [5.0, 4.0, 3.0, 2.0, 3.0, 4.0],
            [5.1, 4.2, 3.0, 2.1, 2.9, 4.0],
            [4.9, 3.8, 3.1, 1.9, 3.2, 4.1],
            [5.2, 4.0, 2.8, 2.0, 3.1, 3.9],
            [2.0, 2.0, 5.0, 5.0, 2.0, 2.0],
            [2.1, 1.9, 5.1, 4.9, 2.0, 2.2],
            [1.9, 2.1, 4.9, 5.2, 2.1, 1.9],
            [2.2, 2.0, 5.0, 5.1, 1.9, 2.1],
        ]
    ).to_numpy()

    result = _fit_kmedoids(data, n_clusters=3)

    assert result.labels_.shape == (len(data),)
    assert len(np.unique(result.labels_)) == 3
    assert len(np.unique(result.medoid_indices_)) == 3
    np.testing.assert_array_equal(result.cluster_centers_, data[result.medoid_indices_])

    distances = np.linalg.norm(
        data[:, np.newaxis, :] - result.cluster_centers_[np.newaxis, :, :], axis=2
    )
    np.testing.assert_array_equal(result.labels_, distances.argmin(axis=1))
    assert sorted(np.bincount(result.labels_).tolist()) == [4, 4, 4]
