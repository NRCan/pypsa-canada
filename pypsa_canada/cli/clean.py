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


def _build_crash_dirs(workdir: Path, run_name: str, crashes: bool) -> list[Path]:
    targets = []
    if crashes:
        results_dir = workdir / "results" / run_name
        if results_dir.exists():
            # Find all crash_* directories
            crash_dirs = [d for d in results_dir.iterdir() if d.is_dir() and d.name.startswith("crash_")]
            targets.extend(crash_dirs)
    return targets


def _build_metadata_targets(
    workdir: Path, snakemake: bool, timestamps: bool
) -> list[Path]:
    targets = []
    if snakemake:
        snakemake_dir = workdir / ".snakemake"
        if snakemake_dir.exists():
            targets.append(snakemake_dir)
    if timestamps:
        # Find all .timestamp files in the workflow directory
        timestamp_files = list(workdir.glob("**/.run_timestamp"))
        targets.extend(timestamp_files)
    return targets


@click.command()
@click.option(
    "-f",
    "--file",
    required=True,
    help="Pre-configured simulation config file",
)
@click.option(
    "--crashes/--no-crashes",
    default=True,
    show_default=True,
    help="Clean crash directories (default behavior)",
)
@click.option(
    "--results/--no-results",
    default=False,
    show_default=True,
    help="Clean entire results directory (including successful runs)",
)
@click.option(
    "--resources/--no-resources",
    default=True,
    show_default=True,
    help="Clean resources directory (built networks) (default behavior)",
)
@click.option(
    "--logs/--no-logs",
    default=True,
    show_default=True,
    help="Clean logs directory (default behavior)",
)
@click.option(
    "--snakemake/--no-snakemake",
    default=True,
    show_default=True,
    help="Clean .snakemake metadata directory (default behavior)",
)
@click.option(
    "--timestamps/--no-timestamps",
    default=True,
    show_default=True,
    help="Clean .timestamp metadata files (default behavior)",
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
    crashes: bool,
    results: bool,
    resources: bool,
    logs: bool,
    snakemake: bool,
    timestamps: bool,
    dry_run: bool,
    yes: bool,
):
    """
    Clean output directories (results, resources, logs) for a run.

    By default, cleans crash directories, resources, logs, and metadata.
    Successful run results are preserved unless --results is explicitly provided.
    """

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

    crash_dirs = _build_crash_dirs(workdir, run_name, crashes)
    target_dirs = _build_target_dirs(workdir, run_name, results, resources, logs)
    metadata_targets = _build_metadata_targets(workdir, snakemake, timestamps)

    existing_crashes = [d for d in crash_dirs if d.exists()]
    existing_dirs = [d for d in target_dirs if d.exists()]
    existing_metadata = [m for m in metadata_targets if m.exists()]

    all_existing = existing_crashes + existing_dirs + existing_metadata

    if not all_existing:
        print(f"Nothing to clean for run '{run_name}' — no crash directories or metadata found.")
        return

    print(f"Run: {run_name}")
    if existing_crashes:
        print("Crash directories to remove:")
        for d in existing_crashes:
            print(f"  {d}")

    if existing_dirs:
        print("Directories to remove:")
        for d in existing_dirs:
            print(f"  {d}")

    if existing_metadata:
        print("Metadata to remove:")
        for m in existing_metadata:
            print(f"  {m}")

    if dry_run:
        print("\n[Dry run] No files were deleted.")
        return

    if not yes:
        click.confirm("\nProceed with deletion?", abort=True)

    for d in existing_crashes:
        shutil.rmtree(d)
        print(f"Removed crash: {d}")

    for d in existing_dirs:
        shutil.rmtree(d)
        print(f"Removed: {d}")

    for m in existing_metadata:
        if m.is_dir():
            shutil.rmtree(m)
            print(f"Removed directory: {m}")
        else:
            m.unlink()
            print(f"Removed file: {m}")

    print("\nClean complete.")
