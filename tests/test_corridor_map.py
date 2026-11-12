"""Regression tests for the corridor map package, independent of Snakemake."""

import numpy as np
import pandas as pd
import pytest

from pypsa_canada.workflow.scripts.corridor_map import flows
from pypsa_canada.workflow.scripts.corridor_map.capacity import (
    get_corridor_added_capacity_for_year,
    load_final_capacity_additions,
)
from pypsa_canada.workflow.scripts.corridor_map.charts import build_util_plot_html
from pypsa_canada.workflow.scripts.corridor_map.data import load_context
from pypsa_canada.workflow.scripts.corridor_map.map import (
    CorridorData,
    MapContext,
    build_corridor_map,
    capacity_by_timestamp,
)
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

    coordinates, provinces, corridors = load_context(str(tmp_path))

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


def test_capacity_additions_are_limited_to_the_current_year():
    """Do not include transmission capacity that is added in future years."""
    additions = pd.DataFrame(
        {
            "Time": [2030, 2040],
            "Value": [20.0, 30.0],
            "Cumulative_Value": [20.0, 50.0],
        }
    )
    detail = {"A__to__B": additions}

    assert get_corridor_added_capacity_for_year("A", "B", 2025, detail) == 0.0
    assert get_corridor_added_capacity_for_year("B", "A", 2030, detail) == 20.0
    assert get_corridor_added_capacity_for_year("A", "B", 2035, detail) == 20.0
    assert get_corridor_added_capacity_for_year("A", "B", 2040, detail) == 50.0


def test_utilization_uses_capacity_available_in_each_timestamp_year():
    """Calculate each utilization point with that year's available capacity."""
    timestamps = pd.to_datetime(["2030-01-01", "2040-01-01"])
    _, metrics = build_util_plot_html(
        timestamps,
        np.array([120.0, 120.0]),
        np.array([120.0, 150.0]),
        "A <-> B",
        "year-specific capacity",
    )

    assert metrics["max_utilization"] == pytest.approx(1.0)
    assert metrics["avg_utilization"] == pytest.approx(0.9)
    assert metrics["hours_ge_0_8"] == 2


def test_map_capacity_tracks_corridor_expansion_by_timestamp_year():
    """Apply the planning capacity timeline to each corridor's flow timestamps."""
    rows = [
        {"name": "existing", "s_nom": 100.0},
        {"name": "new", "s_nom": 50.0, "is_new": True},
    ]
    expansion_detail = {
        "A__to__B": pd.DataFrame(
            {
                "Time": [2030, 2040],
                "Value": [20.0, 30.0],
                "Cumulative_Value": [20.0, 50.0],
            }
        )
    }
    context = MapContext(
        corridors={("A", "B"): rows},
        bus_ll={"A": (53.0, -110.0), "B": (52.0, -105.0)},
        bus_to_province={},
        nodal_index={},
        link_flows_ts=None,
        link_flows_df=None,
        map_label="planning",
        last_year=2040,
        out_html="",
        out_csv="",
        expansion_detail=expansion_detail,
    )
    corridor = CorridorData(
        bus_a="A",
        bus_b="B",
        rows=rows,
        corridor_capacity_mw=150.0,
        base_capacity_mw=100.0,
        added_capacity_mw=50.0,
        kv_label="315 kV",
        sorted_lines=rows,
        lines_html="",
        timestamps=pd.to_datetime(["2030-01-01", "2040-01-01"]),
    )

    np.testing.assert_array_equal(
        capacity_by_timestamp(corridor, context), [120.0, 150.0]
    )


def test_corridor_flow_reverse_fallback(tmp_path):
    """Sum parallel flow columns and negate flows loaded from the opposite side."""
    timestamps = pd.date_range("2030-01-01", periods=2, freq="h", name="snapshot")
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


@pytest.mark.parametrize("nodal_index", [{}, {"AB": None, "SK": None}])
def test_corridor_flow_without_nodal_paths(nodal_index):
    """Treat absent hourly paths as unavailable flow data."""
    assert flows.get_corridor_flow("AB", "SK", nodal_index) == (None, None)


def test_corridor_flow_unreadable_file_raises(tmp_path):
    """Do not treat an indexed but unreadable CSV as absent flow data."""
    hourly = tmp_path / "AB_hourly.csv"

    with pytest.raises(ValueError, match="Error reading CSV file"):
        flows.get_corridor_flow("AB", "SK", {"AB": str(hourly)})


@pytest.mark.parametrize("flow_source", ["direct", "provincial", "missing"])
def test_map_outputs_and_hourly_reset(tmp_path, flow_source):
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
        context = MapContext(
            corridors=corridors,
            bus_ll=coordinates,
            bus_to_province={"A": "AB", "B": "SK"},
            nodal_index=nodal_index,
            link_flows_ts=timestamps if direct_flows is not None else None,
            link_flows_df=direct_flows,
            out_html=str(html_path),
            out_csv=str(csv_path),
            map_label="planning",
            last_year=2040,
            expansion_detail={},
        )
        build_corridor_map(context)

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
