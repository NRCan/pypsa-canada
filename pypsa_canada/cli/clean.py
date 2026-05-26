#!/usr/bin/env python3
"""
CLI command to clean outputs (results, resources, logs) for a given run.
"""

import logging
import shutil
import sys
from pathlib import Path

import click
import yaml

logger = logging.getLogger(__name__)


def _load_config(configfile: Path) -> dict:
    with open(configfile) as f:
        return yaml.safe_load(f) or {}


def _get_run_name(config: dict) -> str:
    run = config.get("run", {})
    name = run.get("name", "")
    prefix = run.get("prefix", "")
    if prefix and name:
        return f"{prefix}/{name}"
    return name or ""


def _build_target_dirs(
    workdir: Path, run_name: str, results: bool, resources: bool, logs: bool
) -> list[Path]:
    targets = []
    if results:
        targets.append(workdir / "results" / run_name)
    if resources:
        targets.append(workdir / "resources" / run_name)
    if logs:
        targets.append(workdir / "logs" / run_name)
    return targets


@click.command()
@click.option(
    "-f",
    "--file",
    required=True,
    help="Pre-configured simulation config file",
)
@click.option(
    "--results/--no-results",
    default=True,
    show_default=True,
    help="Clean results directory",
)
@click.option(
    "--resources/--no-resources",
    default=True,
    show_default=True,
    help="Clean resources directory (built networks)",
)
@click.option(
    "--logs/--no-logs",
    default=True,
    show_default=True,
    help="Clean logs directory",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Preview what would be deleted without removing anything",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt",
)
def clean(
    file: str,
    results: bool,
    resources: bool,
    logs: bool,
    dry_run: bool,
    yes: bool,
):
    """Clean output directories (results, resources, logs) for a run."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    workdir = Path.cwd()
    configfile = workdir / file

    if not configfile.exists():
        print(f"Error: config file not found at {configfile}")
        sys.exit(1)

    config = _load_config(configfile)
    run_name = _get_run_name(config)

    if not run_name:
        print("Error: could not determine run name from config (run.name is empty)")
        sys.exit(1)

    target_dirs = _build_target_dirs(workdir, run_name, results, resources, logs)
    existing = [d for d in target_dirs if d.exists()]

    if not existing:
        print(f"Nothing to clean for run '{run_name}' — no output directories found.")
        return

    print(f"Run: {run_name}")
    print("Directories to remove:")
    for d in existing:
        print(f"  {d}")

    if dry_run:
        print("\n[Dry run] No files were deleted.")
        return

    if not yes:
        click.confirm("\nProceed with deletion?", abort=True)

    for d in existing:
        shutil.rmtree(d)
        print(f"Removed: {d}")

    print("\nClean complete.")
