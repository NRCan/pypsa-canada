"""Regression tests for the corridor map package, independent of Snakemake."""

import numpy as np
import pandas as pd
import pytest

from pypsa_canada.workflow.scripts.corridor_map import flows
from pypsa_canada.workflow.scripts.corridor_map.capacity import (
    load_final_capacity_additions,
)
from pypsa_canada.workflow.scripts.corridor_map.data import load_context
from pypsa_canada.workflow.scripts.corridor_map.map import build_corridor_map
from pypsa_canada.workflow.scripts.corridor_map.settings import SUMMARY_COLUMNS


def test_load_context_normalizes_links_and_groups_corridors(tmp_path):
    """Keep existing capacity and include optimized capacity for new links."""
    pd.DataFrame(
        {
            "name": ["A", "B"],
            "x": [-110.0, -105.0],
            "y": [53.0, 52.0],
            "province": ["AB", "SK"],
        }
    ).to_csv(tmp_path / "buses.csv", index=False)
    pd.DataFrame(
        {
            "name": ["existing", "new", "unbuilt"],
            "bus0": ["A", "B", "A"],
            "bus1": ["B", "A", "B"],
            "p_nom": [100.0, 0.0, 0.0],
            "p_nom_opt": [150.0, 40.0, 0.0],
        }
    ).to_csv(tmp_path / "links.csv", index=False)

    coordinates, provinces, corridors = load_context(str(tmp_path), "planning")

    assert coordinates == {"A": (53.0, -110.0), "B": (52.0, -105.0)}
    assert provinces == {"A": "AB", "B": "SK"}
    assert list(corridors) == [("A", "B")]
    assert [row["s_nom"] for row in corridors[("A", "B")]] == [100.0, 40.0]
    assert [bool(row["is_new"]) for row in corridors[("A", "B")]] == [False, True]


def test_capacity_additions_deduplicate_directions(tmp_path):
    """Use the maximum directional addition per year before accumulating."""
    summary = tmp_path / "unit_summary_planning.csv"
    pd.DataFrame(
        {
            "Region": ["A->B", "B->A", "A->B"],
            "Parameter": ["New_Transmission_Capacity"] * 3,
            "Time": [2030, 2030, 2040],
            "Value": [10.0, 10.0, 5.0],
        }
    ).to_csv(summary, index=False)

    added, year, detail = load_final_capacity_additions(str(summary))

    assert added == {"A__to__B": 15.0}
    assert year == 2040
    assert detail["A__to__B"]["Cumulative_Value"].tolist() == [10.0, 15.0]


def test_corridor_flow_reverse_fallback(tmp_path, monkeypatch):
    """Sum parallel flow columns and negate flows loaded from the opposite side."""
    monkeypatch.setattr(flows, "_hourly_cache", {})
    timestamps = pd.date_range("2030-01-01", periods=2, freq="h")
    hourly = tmp_path / "SK_hourly.csv"
    pd.DataFrame(
        {
            "snapshot": timestamps,
            "AB_first_transmission_flow": [10.0, -20.0],
            "AB_second_transmission_flow": [5.0, -5.0],
            "AB_generation": [999.0, 999.0],
        }
    ).to_csv(hourly, index=False)

    actual_time, actual_flow = flows.get_corridor_flow("AB", "SK", {"SK": str(hourly)})

    assert actual_time is not None
    pd.testing.assert_index_equal(actual_time, timestamps)
    np.testing.assert_array_equal(actual_flow, [-15.0, 25.0])


@pytest.mark.parametrize("flow_source", ["direct", "provincial", "missing"])
def test_map_outputs_and_hourly_cache_reset(tmp_path, flow_source):
    """Export summaries and reset hourly data between consecutive map builds."""
    timestamps = pd.date_range("2030-01-01", periods=2, freq="h")
    corridors = {
        ("A", "B"): [
            {"name": "existing_315", "bus0": "A", "bus1": "B", "s_nom": 100.0},
            {
                "name": "new_315",
                "bus0": "A",
                "bus1": "B",
                "s_nom": 50.0,
                "is_new": True,
            },
        ]
    }
    coordinates = {"A": (53.0, -110.0), "B": (52.0, -105.0)}

    for run, scale in enumerate([1.0, 0.5]):
        nodal_index = {}
        direct_flows = None
        if flow_source == "provincial":
            hourly = tmp_path / f"AB_{run}_hourly.csv"
            pd.DataFrame(
                {
                    "snapshot": timestamps,
                    "SK_transmission_flow": np.array([90.0, 150.0]) * scale,
                }
            ).to_csv(hourly, index=False)
            nodal_index = {"AB": str(hourly)}
        elif flow_source == "direct":
            direct_flows = pd.DataFrame(
                {
                    "existing_315": np.array([60.0, 100.0]) * scale,
                    "new_315": np.array([30.0, 50.0]) * scale,
                },
                index=timestamps,
            )

        html_path = tmp_path / str(run) / "map.html"
        csv_path = tmp_path / str(run) / "summary.csv"
        build_corridor_map(
            corridors,
            coordinates,
            {"A": "AB", "B": "SK"},
            nodal_index,
            timestamps if direct_flows is not None else None,
            direct_flows,
            str(html_path),
            str(csv_path),
            "planning",
            {},
            2040,
            {},
        )

        assert "leaflet" in html_path.read_text().lower()
        summary = pd.read_csv(csv_path)
        assert summary.columns.tolist() == SUMMARY_COLUMNS
        if flow_source == "missing":
            assert summary.empty
        else:
            row = summary.iloc[0]
            assert row["corridor_capacity_mw"] == 150.0
            assert row["capacity_for_utilization_mw"] == 150.0
            assert row["existing_lines_capacity_mw"] == 100.0
            assert row["new_lines_capacity_mw"] == 50.0
            assert row["max_utilization"] == pytest.approx(scale)
            assert row["avg_utilization"] == pytest.approx(0.8 * scale)
            assert row["hours_ge_0_8"] == (1 if run == 0 else 0)
