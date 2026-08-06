"""
CLI command to run the complete postprocess chain on existing run outputs.

This module executes all postprocessing steps:
1. Post-process planning results
2. Post-process dispatch results
3. Create combined summary CSV
4. Export to IDEA format (if configured)
5. Generate corridor utilization maps

Usage:
    pypsa-canada postprocess-summary --run-dir results/minimal_model-2021-2050/run_2026-05-06_17-33 --config config/minimal_model.yaml
    pypsa-canada postprocess-summary --skip-export  # Skip IDEA export
    pypsa-canada postprocess-summary --skip-maps    # Skip corridor map generation
    pypsa-canada postprocess-summary  # uses defaults
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
@click.option(
    "--skip-export",
    is_flag=True,
    help="Skip IDEA export step.",
)
@click.option(
    "--skip-maps",
    is_flag=True,
    help="Skip corridor map generation.",
)
def generate_postprocess_summary(run_dir, config_path, result_type, skip_export, skip_maps):
    """
    Run the complete postprocess chain on a results folder.

    This command executes all postprocessing steps:
    1. Post-process planning results
    2. Post-process dispatch results
    3. Create combined summary CSV
    4. Export to IDEA format (if configured and not skipped)
    5. Generate corridor utilization maps (if not skipped)
    """
    run_dir = Path(run_dir)
    if not run_dir.exists():
        click.echo(f"ERROR: Run directory not found: {run_dir}", err=True)
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    result_type = result_type or config.get("postprocess", {}).get(
        "result_type", "Provincial"
    )

    script_root = Path(__file__).parent.parent / "workflow" / "scripts"

    # Step 1 & 2: Ensure post_process_planning and post_process_dispatch outputs exist
    click.echo("Step 1-2: Processing planning and dispatch results...")
    _ensure_postprocess_outputs(run_dir, config, result_type)

    # Step 3: Create summary
    click.echo("Step 3: Creating combined summary CSV...")
    summary_snakemake = types.SimpleNamespace(
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
        log=[str(run_dir / "logs" / "create_summary_cli.log")],
    )
    _run_snakemake_script(script_root / "create_summary.py", summary_snakemake)
    click.echo(f"✓ Summary created: {run_dir / 'results_summary.csv'}")

    # Step 4: Export to IDEA format (if configured)
    export_format = config.get("postprocess", {}).get("export_format")
    if not skip_export and export_format == "idea":
        click.echo("Step 4: Exporting to IDEA format...")
        idea_snakemake = types.SimpleNamespace(
            input=types.SimpleNamespace(
                planning_dir=str(run_dir / "post_process_planning"),
                dispatch_dir=str(run_dir / "post_process_dispatch"),
            ),
            output=types.SimpleNamespace(
                idea_output=str(run_dir / "idea_outputs.csv"),
            ),
            params=types.SimpleNamespace(
                result_type=result_type,
            ),
            config=config,
            log=[str(run_dir / "logs" / "export_idea_cli.log")],
        )
        _run_snakemake_script(script_root / "export_idea.py", idea_snakemake)
        click.echo(f"✓ IDEA export created: {run_dir / 'idea_outputs.csv'}")
    elif skip_export:
        click.echo("Step 4: Skipping IDEA export (--skip-export flag)")
    else:
        click.echo(f"Step 4: Skipping IDEA export (export_format={export_format})")

    # Step 5 & 6: Generate corridor maps
    if not skip_maps:
        solved_planning = run_dir / "planning_solved_network"
        solved_dispatch = run_dir / "dispatch_solved_network"

        if solved_planning.exists():
            click.echo("Step 5: Generating planning corridor map...")
            maps_dir = run_dir / "post_process_maps"
            maps_dir.mkdir(exist_ok=True)

            planning_map_snakemake = types.SimpleNamespace(
                input=types.SimpleNamespace(
                    planning_solved_network=str(solved_planning),
                    post_process_planning=str(run_dir / "post_process_planning"),
                ),
                output=types.SimpleNamespace(
                    planning_corridor_map=str(maps_dir / "planning_corridor_utilization_map.html"),
                    planning_corridor_summary=str(maps_dir / "planning_corridor_utilization_map_summary.csv"),
                ),
                config=config,
                log=[str(run_dir / "logs" / "plot_planning_corridor_map_cli.log")],
            )
            _run_snakemake_script(script_root / "plot_corridor_map.py", planning_map_snakemake)
            click.echo(f"✓ Planning corridor map created: {maps_dir / 'planning_corridor_utilization_map.html'}")
        else:
            click.echo(f"Step 5: Skipping planning corridor map (no solved network at {solved_planning})")

        if solved_dispatch.exists() and solved_planning.exists():
            click.echo("Step 6: Generating dispatch corridor map...")
            maps_dir = run_dir / "post_process_maps"
            maps_dir.mkdir(exist_ok=True)

            dispatch_map_snakemake = types.SimpleNamespace(
                input=types.SimpleNamespace(
                    planning_solved_network=str(solved_planning),
                    dispatch_solved_network=str(solved_dispatch),
                    post_process_planning=str(run_dir / "post_process_planning"),
                    post_process_dispatch=str(run_dir / "post_process_dispatch"),
                ),
                output=types.SimpleNamespace(
                    dispatch_corridor_map=str(maps_dir / "dispatch_corridor_utilization_map.html"),
                    dispatch_corridor_summary=str(maps_dir / "dispatch_corridor_utilization_map_summary.csv"),
                ),
                config=config,
                log=[str(run_dir / "logs" / "plot_dispatch_corridor_map_cli.log")],
            )
            _run_snakemake_script(script_root / "plot_corridor_map.py", dispatch_map_snakemake)
            click.echo(f"✓ Dispatch corridor map created: {maps_dir / 'dispatch_corridor_utilization_map.html'}")
        else:
            if not solved_dispatch.exists():
                click.echo(f"Step 6: Skipping dispatch corridor map (no solved network at {solved_dispatch})")
            else:
                click.echo("Step 6: Skipping dispatch corridor map (planning network required)")
    else:
        click.echo("Steps 5-6: Skipping corridor maps (--skip-maps flag)")

    click.echo("\n✓ Complete postprocess chain finished successfully!")
