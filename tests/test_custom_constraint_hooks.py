import importlib
import shutil
import sys
import types
from types import SimpleNamespace

import pandas as pd
import pytest
from constraints.generic_constraints import load_custom_constraint_module

snakemake_module = types.ModuleType("snakemake")
snakemake_utils_module = types.ModuleType("snakemake.utils")


def update_config(config, update):
    config.update(update)


snakemake_utils_module.update_config = update_config
snakemake_module.utils = snakemake_utils_module
sys.modules.setdefault("snakemake", snakemake_module)
sys.modules.setdefault("snakemake.utils", snakemake_utils_module)

solve_dispatch = importlib.import_module("solve_dispatch")
solve_planning = importlib.import_module("solve_planning")


@pytest.fixture
def local_tmp_dir(request):
    tmp_dir = request.path.parent / ".tmp_custom_constraint_hooks" / request.node.name
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    tmp_dir.mkdir(parents=True)
    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def write_module(tmp_dir, source):
    module_path = tmp_dir / "custom_constraints.py"
    module_path.write_text(source)
    return module_path


def planning_config(custom_constraints=None):
    config = {
        "planning": {
            "constraints": {
                "add_bidirection_link": {"enable": False},
                "add_stop_production": {"enable": False, "years": {}},
                "CER_constraint": {"enable": False},
                "NZ_constraint": {"enable": False},
                "planning_reserve_margin": {"enable": False},
                "component_capacity_expansion_constraint": {"enable": False},
            }
        }
    }
    if custom_constraints is not None:
        config["custom_constraints"] = custom_constraints
    return config


def dispatch_config(custom_constraints=None):
    config = {
        "dispatch": {
            "constraints": {
                "add_stop_production": {"enable": False, "years": {}},
                "add_bidirection_link": {"enable": False},
                "add_prevent_spill_if_not_fully_charged": {"enable": False},
                "CER_constraint": {"enable": False},
            }
        }
    }
    if custom_constraints is not None:
        config["custom_constraints"] = custom_constraints
    return config


class FakePlanningNetwork:
    def __init__(self):
        timesteps = pd.date_range("2030-01-01", periods=2, freq="h")
        self.snapshots = pd.MultiIndex.from_arrays(
            [timesteps.year, timesteps], names=["period", "timestep"]
        )
        self.links = pd.DataFrame(columns=["carrier", "p_nom_extendable"])
        self.model = SimpleNamespace(constraints=[])
        self.calls = []


class FakeDispatchNetwork:
    def __init__(self):
        self.snapshots = pd.date_range("2030-01-01", periods=2, freq="h")
        self.generators = pd.DataFrame({"committable": []})
        self.stores = pd.DataFrame()
        self.storage_units = pd.DataFrame()
        self.generators_t = SimpleNamespace(status=pd.DataFrame(index=self.snapshots))
        self.model = SimpleNamespace(constraints=[])
        self.calls = []

    def optimize(self, snapshots, **kwargs):
        kwargs["extra_functionality"](self, snapshots)
        return "ok", "optimal"


def test_loader_returns_none_for_none():
    assert load_custom_constraint_module(None) is None


def test_loader_missing_file_raises(local_tmp_dir):
    with pytest.raises(FileNotFoundError):
        load_custom_constraint_module(local_tmp_dir / "missing.py")


def test_loader_loads_module(local_tmp_dir):
    module_path = write_module(local_tmp_dir, "VALUE = 42\n")
    module = load_custom_constraint_module(module_path)

    assert module.VALUE == 42


def test_planning_hook_invokes_add_planning_constraints(local_tmp_dir):
    module_path = write_module(
        local_tmp_dir,
        (
            "def add_planning_constraints(network, snapshots, config, year):\n"
            "    network.calls.append((list(snapshots), config, year))\n"
        ),
    )
    network = FakePlanningNetwork()
    old_config = solve_planning.config
    solve_planning.config = planning_config(
        {"enabled": True, "module_path": str(module_path)}
    )
    try:
        solve_planning.add_all_planning_constraints(network, network.snapshots)
    finally:
        solve_planning.config = old_config

    assert len(network.calls) == 1
    expected_snapshots = list(
        network.snapshots[network.snapshots.get_level_values(0) == 2030]
    )
    assert network.calls[0][0] == expected_snapshots
    assert network.calls[0][1]["module_path"] == str(module_path)
    assert network.calls[0][2] == 2030


def test_dispatch_hook_invokes_add_dispatch_constraints(local_tmp_dir):
    module_path = write_module(
        local_tmp_dir,
        (
            "def add_dispatch_constraints(network, snapshots, config, year):\n"
            "    network.calls.append((list(snapshots), config, year))\n"
        ),
    )
    network = FakeDispatchNetwork()
    old_config = solve_dispatch.config
    old_snakemake = solve_dispatch.snakemake
    solve_dispatch.config = dispatch_config(
        {"enabled": True, "module_path": str(module_path)}
    )
    solve_dispatch.snakemake = SimpleNamespace(
        output=SimpleNamespace(dispatch_output_file_csv=str(local_tmp_dir / "out"))
    )
    try:
        solve_dispatch.optimize_uc_period(
            network=network,
            horizon=24,
            overlap=0,
            solver_name="test-solver",
            period_year=2030,
        )
    finally:
        solve_dispatch.config = old_config
        solve_dispatch.snakemake = old_snakemake

    assert len(network.calls) == 1
    assert network.calls[0][0] == list(network.snapshots)
    assert network.calls[0][1]["module_path"] == str(module_path)
    assert network.calls[0][2] == 2030


def test_missing_optional_hook_function_is_skipped(local_tmp_dir):
    module_path = write_module(local_tmp_dir, "VALUE = 42\n")
    network = FakePlanningNetwork()
    old_config = solve_planning.config
    solve_planning.config = planning_config(
        {"enabled": True, "module_path": str(module_path)}
    )
    try:
        solve_planning.add_all_planning_constraints(network, network.snapshots)
    finally:
        solve_planning.config = old_config

    assert network.calls == []
