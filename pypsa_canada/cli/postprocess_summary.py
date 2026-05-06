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

    # Build a mock snakemake object
    snakemake = types.SimpleNamespace(
        input=types.SimpleNamespace(
            planning_dir=str(run_dir / "post_process_planning"),
            dispatch_dir=str(run_dir / "post_process_dispatch"),
        ),
        output=types.SimpleNamespace(
            compare_output=str(run_dir / "compare_results"),
        ),
        params=types.SimpleNamespace(
            result_type=result_type,
        ),
        config=config,
        log=["logs/compare_results_test.log"],
    )

    # Inject mock into builtins so the script sees it at module level
    builtins.snakemake = snakemake

    # Run the script
    script = (
        Path(__file__).parent.parent / "workflow" / "scripts" / "compare_results.py"
    )
    script_globals = {"__builtins__": __builtins__, "snakemake": snakemake}
    exec(
        compile(script.read_text(encoding="utf-8"), str(script), "exec"), script_globals
    )
