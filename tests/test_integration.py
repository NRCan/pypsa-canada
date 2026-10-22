import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pypsa
import pytest


def _run_snakemake_script(monkeypatch, scripts_path, script_name, snakemake):
    """Run a workflow script's ``main`` using a test-provided Snakemake context.

    Snakemake normally injects the ``snakemake`` object and adds the workflow
    scripts directory to Python's import path. This helper supplies those
    conditions directly so tests can run an individual stage without starting
    the full Snakemake workflow. It also disables script log redirection to
    keep test output and process-wide streams intact.
    """
    monkeypatch.syspath_prepend(str(scripts_path))
    import helpers

    monkeypatch.setattr(helpers, "setup_script_logging", lambda _: None)
    script_path = scripts_path / script_name
    module_name = f"test_{script_path.stem}_script"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.snakemake = snakemake
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        module.main()
    finally:
        sys.modules.pop(module_name, None)


@pytest.mark.integration
@pytest.mark.planning
def test_minimal_planning_workflow_solves_and_exports(tmp_path, monkeypatch):
    network = pypsa.Network()
    periods = [2030, 2035]
    network.set_investment_periods(periods)
    snapshots = pd.DatetimeIndex(
        [
            pd.Timestamp(year=year, month=1, day=1, hour=hour)
            for year in periods
            for hour in range(2)
        ]
    )
    network.set_snapshots(
        pd.MultiIndex.from_arrays(
            [snapshots.year, snapshots], names=["period", "timestep"]
        )
    )
    network.add("Bus", "bus", province="AB")
    network.add("Carrier", "test", co2_emissions=0)
    network.add(
        "Generator",
        "extendable_generator",
        bus="bus",
        carrier="test",
        p_nom=0,
        p_nom_extendable=True,
        p_nom_max=100,
        capital_cost=1,
        marginal_cost=1,
        build_year=2030,
        lifetime=30,
    )
    network.add("Load", "load", bus="bus", p_set=10)

    input_path = tmp_path / "unsolved.nc"
    output_path = tmp_path / "solved"
    network.export_to_netcdf(input_path)

    config = {
        "solving": {
            "options": {
                "planning": {
                    "enable_committable": False,
                    "enable_p_min_pu": False,
                    "enable_ramp_rates": False,
                    "load_shedding": False,
                    "linearized_unit_commitment": False,
                    "include_objective_constant": False,
                }
            },
            "solver": {"name": "highs", "options": "highs-fast"},
            "solver_options": {"highs-fast": {}},
        },
        "planning": {
            "constraints": {
                "add_bidirection_link": {"enable": False},
                "add_stop_production": {"enable": False, "years": {}},
                "CER_constraint": {"enable": False, "year": 9999},
                "NZ_constraint": {"enable": False},
                "planning_reserve_margin": {
                    "enable": False,
                    "provinces_list": {},
                },
                "component_capacity_expansion_constraint": {"enable": False},
            },
            "custom_constraints": {"enabled": False},
        },
        "run": {"benchmark_results_file": str(tmp_path / "benchmarks.csv")},
    }
    snakemake = SimpleNamespace(
        config=config,
        input=SimpleNamespace(unsolved_network=str(input_path)),
        output=SimpleNamespace(solved_network_csv=str(output_path)),
        log=[str(tmp_path / "solve_planning.log")],
    )

    scripts_path = Path(__file__).parents[1] / "pypsa_canada" / "workflow" / "scripts"
    _run_snakemake_script(monkeypatch, scripts_path, "solve_planning.py", snakemake)

    solved_generators = pd.read_csv(output_path / "generators.csv", index_col=0)
    assert solved_generators.loc["extendable_generator", "p_nom_opt"] == pytest.approx(
        10
    )


@pytest.mark.integration
@pytest.mark.dispatch
def test_minimal_dispatch_workflow_uses_manually_solved_planning_network(
    tmp_path, monkeypatch
):
    planning_network = pypsa.Network()
    snapshots = pd.date_range("2030-01-01", periods=2, freq="h")
    planning_network.set_snapshots(snapshots)
    planning_network.add("Bus", "bus", province="AB")
    planning_network.add("Carrier", "test", co2_emissions=0)
    planning_network.add(
        "Generator",
        "extendable_generator",
        bus="bus",
        carrier="test",
        p_nom=0,
        p_nom_extendable=True,
        p_nom_max=100,
        capital_cost=1,
        marginal_cost=1,
        build_year=2020,
        lifetime=30,
    )
    planning_network.add("Load", "load", bus="bus", p_set=10)

    base_network_path = tmp_path / "planning_base.nc"
    planning_network.export_to_netcdf(base_network_path)

    status, condition = planning_network.optimize(solver_name="highs")
    assert (status, condition) == ("ok", "optimal")
    optimal_capacity = planning_network.generators.at[
        "extendable_generator", "p_nom_opt"
    ]
    assert optimal_capacity == pytest.approx(10)

    planning_solved_path = tmp_path / "planning_solved.nc"
    planning_network.export_to_netcdf(planning_solved_path)
    dispatch_network_path = tmp_path / "dispatch_input.nc"
    dispatch_network_csv_path = tmp_path / "dispatch_input_csv"
    output_path = tmp_path / "dispatch_solved"
    config = {
        "solving": {
            "options": {
                "dispatch": {
                    "enable_committable": False,
                    "enable_p_min_pu": False,
                    "enable_ramp_rates": False,
                    "load_shedding": False,
                    "linearized_unit_commitment": False,
                    "include_objective_constant": False,
                }
            },
            "solver": {"name": "highs", "options": "highs-fast"},
            "solver_options": {"highs-fast": {}},
        },
        "dispatch": {
            "horizon": 2,
            "overlap": 0,
            "investment_period": [2030],
            "planning_solved_network": str(planning_solved_path),
            "constraints": {
                "add_stop_production": {"enable": False, "years": {}},
                "add_bidirection_link": {"enable": False},
                "add_prevent_spill_if_not_fully_charged": {"enable": False},
                "CER_constraint": {"enable": False, "year": 9999},
            },
            "custom_constraints": {"enabled": False},
        },
        "year_settings": {"investment_period": [2030]},
        "run": {"benchmark_results_file": str(tmp_path / "benchmarks.csv")},
    }
    create_dispatch_snakemake = SimpleNamespace(
        config=config,
        input=SimpleNamespace(
            base_network=str(base_network_path),
            planning_solved_network=config["dispatch"]["planning_solved_network"],
        ),
        output=SimpleNamespace(
            dispatch_planning_unsolved_network_nc=str(dispatch_network_path),
            dispatch_planning_unsolved_network_csv=str(dispatch_network_csv_path),
        ),
        log=[str(tmp_path / "create_dispatch_network.log")],
    )
    scripts_path = Path(__file__).parents[1] / "pypsa_canada" / "workflow" / "scripts"
    _run_snakemake_script(
        monkeypatch,
        scripts_path,
        "create_dispatch_network.py",
        create_dispatch_snakemake,
    )

    solve_dispatch_snakemake = SimpleNamespace(
        config=config,
        input=SimpleNamespace(unsolved_dispatch_network=str(dispatch_network_path)),
        output=SimpleNamespace(dispatch_output_file_csv=str(output_path)),
        log=[str(tmp_path / "solve_dispatch.log")],
    )
    _run_snakemake_script(
        monkeypatch, scripts_path, "solve_dispatch.py", solve_dispatch_snakemake
    )

    solved_generators = pd.read_csv(
        output_path / "2030" / "generators.csv", index_col=0
    )
    assert solved_generators.loc["extendable_generator", "p_nom"] == pytest.approx(10)

    solve_stats = pd.read_csv(output_path / "solve_stats.csv")
    assert solve_stats["Status"].tolist() == ["ok"]
    assert solve_stats["Condition"].tolist() == ["optimal"]

    generator_dispatch = pd.read_csv(
        output_path / "2030" / "generators-p.csv", index_col=0
    )
    assert generator_dispatch["extendable_generator"].to_numpy() == pytest.approx(
        [10, 10]
    )
