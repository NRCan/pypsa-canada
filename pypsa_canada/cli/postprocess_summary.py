"""
CLI command to test compare_results script against existing run outputs.

Usage:
    pypsa-canada test-compare --run-dir results/minimal_model-2021-2050/run_2026-05-06_17-33 --config config/minimal_model.yaml
    pypsa-canada test-compare  # uses defaults
"""

import builtins
import sys
import types
from pathlib import Path

import click
import yaml


def _run_snakemake_script(script: Path, snakemake: types.SimpleNamespace):
    """Execute a workflow script with a mocked snakemake namespace."""
    builtins.snakemake = snakemake
    script_path = str(script.parent)
    script_globals = {"__builtins__": __builtins__, "snakemake": snakemake}
    sys.path.insert(0, script_path)
    try:
        exec(
            compile(script.read_text(encoding="utf-8"), str(script), "exec"),
            script_globals,
        )
    finally:
        if sys.path and sys.path[0] == script_path:
            sys.path.pop(0)


def _ensure_postprocess_outputs(run_dir: Path, config: dict, result_type: str):
    """Create post-process outputs from solved networks when they are missing."""
    planning_dir = run_dir / "post_process_planning"
    dispatch_dir = run_dir / "post_process_dispatch"

    planning_summary = planning_dir / f"{result_type}_summary_planning.csv"
    dispatch_summary = dispatch_dir / f"{result_type}_summary_dispatch.csv"

    script_root = Path(__file__).parent.parent / "workflow" / "scripts"

    if not planning_summary.exists():
        solved_planning = run_dir / "planning_solved_network"
        if not solved_planning.exists():
            raise click.ClickException(
                f"Missing planning summary and solved network folder: {solved_planning}"
            )

        planning_snakemake = types.SimpleNamespace(
            input=types.SimpleNamespace(solved_planning_network=str(solved_planning)),
            output=types.SimpleNamespace(planning_postprocess=str(planning_dir)),
            config=config,
            log=[str(run_dir / "logs" / "post_process_planning_cli.log")],
        )
        _run_snakemake_script(
            script_root / "post_process_planning.py", planning_snakemake
        )

    if not dispatch_summary.exists():
        solved_dispatch = run_dir / "dispatch_solved_network"
        if not solved_dispatch.exists():
            raise click.ClickException(
                f"Missing dispatch summary and solved network folder: {solved_dispatch}"
            )

        dispatch_snakemake = types.SimpleNamespace(
            input=types.SimpleNamespace(solved_dispatch_network=str(solved_dispatch)),
            output=types.SimpleNamespace(dispatch_postprocess=str(dispatch_dir)),
            config=config,
            log=[str(run_dir / "logs" / "post_process_dispatch_cli.log")],
        )
        _run_snakemake_script(
            script_root / "post_process_dispatch.py", dispatch_snakemake
        )


@click.command("postprocess-summary")
@click.option(
    "--run-dir",
    default="results/minimal_model-2021-2050/run_2026-05-06_17-33",
    help="Path to an existing run output directory.",
    type=click.Path(),
)
@click.option(
    "--config",
    "config_path",
    default="config/minimal_model.yaml",
    help="Path to the config YAML file.",
    type=click.Path(exists=True),
)
@click.option(
    "--result-type",
    default=None,
    help="Override result_type (default: read from config or 'Provincial').",
)
def generate_postprocess_summary(run_dir, config_path, result_type):
    """Generate postprocess summary script against existing run outputs."""
    run_dir = Path(run_dir)
    if not run_dir.exists():
        click.echo(f"ERROR: Run directory not found: {run_dir}", err=True)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    result_type = result_type or config.get("postprocess", {}).get(
        "result_type", "Provincial"
    )

    _ensure_postprocess_outputs(run_dir, config, result_type)

    # Build a mock snakemake object
    snakemake = types.SimpleNamespace(
        input=types.SimpleNamespace(
            planning_dir=str(run_dir / "post_process_planning"),
            dispatch_dir=str(run_dir / "post_process_dispatch"),
        ),
        output=types.SimpleNamespace(
            summary_output=str(run_dir / "results_summary.csv"),
        ),
        params=types.SimpleNamespace(
            result_type=result_type,
        ),
        config=config,
        log=["logs/compare_results_test.log"],
    )

    # Run the script
    script = Path(__file__).parent.parent / "workflow" / "scripts" / "create_summary.py"
    _run_snakemake_script(script, snakemake)
