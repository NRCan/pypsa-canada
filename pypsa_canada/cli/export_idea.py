"""CLI command to execute the IDEA export script against an existing run directory."""

import builtins
import types
from pathlib import Path

import click
import yaml


def run_export_idea(run_dir, config_path, result_type=None, log_file=None):
    """Execute the IDEA export script with an existing run directory."""
    run_dir = Path(run_dir)
    if not run_dir.exists():
        raise click.ClickException(f"Run directory not found: {run_dir}")

    with open(config_path, encoding="utf-8") as file_handle:
        config = yaml.safe_load(file_handle)

    result_type = result_type or config.get("postprocess", {}).get(
        "result_type", "Provincial"
    )

    idea_output = run_dir / "idea_output"
    snakemake = types.SimpleNamespace(
        input=types.SimpleNamespace(
            planning_dir=str(run_dir / "post_process_planning"),
            dispatch_dir=str(run_dir / "post_process_dispatch"),
        ),
        output=types.SimpleNamespace(
            idea_output=str(idea_output),
        ),
        params=types.SimpleNamespace(
            result_type=result_type,
        ),
        config=config,
        log=[str(log_file or (run_dir / "logs" / "export_idea_cli.log"))],
    )

    builtins.snakemake = snakemake

    script = Path(__file__).parent.parent / "workflow" / "scripts" / "export_idea.py"
    script_globals = {"__builtins__": __builtins__, "snakemake": snakemake}
    exec(
        compile(script.read_text(encoding="utf-8"), str(script), "exec"), script_globals
    )


@click.command("export-idea")
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
    "--log-file",
    default=None,
    help="Optional log file path for the exporter.",
)
def export_idea(run_dir, config_path, result_type, log_file):
    run_export_idea(run_dir, config_path, result_type=result_type, log_file=log_file)


def main():
    export_idea.main(standalone_mode=False)


if __name__ == "__main__":
    main()
