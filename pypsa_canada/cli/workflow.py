#!/usr/bin/env python3
"""
CLI script to run a Snakemake workflow using the Python API (Snakemake 8+).
Usage: python run_workflow.py

Expects a Snakefile in the same directory.
"""

import logging
import logging
import os
import sys
from importlib.resources import files
from pathlib import Path

import click
from snakemake.api import SnakemakeApi
from snakemake.settings.types import (
    ConfigSettings,
    DAGSettings,
    DeploymentSettings,
    ResourceSettings,
)

os.environ.pop("SNAKEMAKE_OUTPUT_CACHE", None)  # no cache location => cache unused


@click.option(
    "-f",
    "--file",
    help="Pre-configured simulation file (Can add multiples files. Each file should have a new argument -f)",
    # multiple=True,
)
# @click.option(
#     "-d",
#     "--dir",
#     help="Run all configuration files from a directory path",
#     type=click.Path(exists=True),
#     default=None,
# )
@click.option(
    "--data-folder",
    type=click.Path(exists=True),
    default=None,
    help="Path to custom data folder (default: current working directory). Sets PYPSA_CUSTOM_DATA_FOLDER environment variable.",
)
@click.option(
    "-t",
    "--targets",
    help="A list of targets (rules) to generate",
    multiple=True,
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    show_default=False,
    help="Debug on/off (default=false)",
)
@click.option(
    "--unlock",
    is_flag=True,
    default=False,
    show_default=False,
    help="Unlock the working directory after a crash or interruption",
)
# @click.option(
#     "--test",
#     is_flag=True,
#     default=False,
#     show_default=False,
#     help="Test mode on/off (default=false)",
# )
# @click.option(
#     "--dispatch",
#     help="Dispatch inputs files to run without running planning inputs",
# )
@click.command()
# def run(file=None, dir=None, debug=False, test=False, dispatch=None):
def run(
    file: str,
    targets: str,
    data_folder: str | None = None,
    debug: bool = False,
    test: bool = False,
    cores: int | None = None,
    unlock: bool = False,
):
    # Configure logging level
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set Snakemake logger to the same level
    snakemake_logger = logging.getLogger("snakemake")
    snakemake_logger.setLevel(log_level)

    # Set PYPSA_CUSTOM_DATA_FOLDER environment variable
    if data_folder is None:
        data_folder = str(Path.cwd())
    os.environ["PYPSA_CUSTOM_DATA_FOLDER"] = data_folder
    print(f"PYPSA_CUSTOM_DATA_FOLDER set to: {data_folder}")

    wf_root = files("pypsa_canada.workflow")
    snakefile = Path(str(wf_root.joinpath("Snakefile")))
    workdir = Path.cwd()

    # File
    configfile = workdir / file  # "tutorial_config.yaml"
    profile_dir = workdir / "profile"
    # profile_config = profile_dir / "config.yaml"

    # Check if config file exists
    if not configfile.exists():
        print(f"Warning: config.yaml not found at {configfile}")
    if configfile.exists():
        print(f"Using config: {configfile}")

    # # Check if profile exists
    # if profile_dir.exists() and (profile_dir / "config.yaml").exists():
    #     print(f"Found profile directory: {profile_dir}")

    # # Read cores from profile config if available
    # cores = 4  # default
    # if profile_config.exists():
    #     print(f"Found profile directory: {profile_dir}")
    #     try:
    #         with open(profile_config, 'r') as f:
    #             profile_data = yaml.safe_load(f)
    #             if profile_data and 'cores' in profile_data:
    #                 cores = profile_data['cores']
    #                 print(f"Using {cores} cores from profile config")
    #     except Exception as e:
    #         print(f"Warning: Could not read profile config: {e}")

    # Check if Snakefile exists
    if not snakefile.exists():
        print(f"Error: Snakefile not found at {snakefile}")
        print("Please create a Snakefile in the current directory.")
        sys.exit(1)

    print(f"Running Snakemake workflow from: {workdir}")
    print(f"Using Snakefile: {snakefile}\n")

    # Initialize and run the workflow
    try:
        with SnakemakeApi() as api:
            config_settings = None
            if configfile.exists():
                config_settings = ConfigSettings(configfiles=[configfile])

            # Create deployment settings with profile
            deployment_settings = None
            if profile_dir.exists():
                deployment_settings = DeploymentSettings(profile=profile_dir)
            else:
                deployment_settings = DeploymentSettings()

            if cores is None:
                cores = os.cpu_count() if os.cpu_count() else 1
                if not unlock:  # Only print this when not unlocking
                    print(
                        f"No number of cores selected ---> Using all available cores from machine: {cores} cores"
                    )
            # Create resource settings
            resource_settings = ResourceSettings(cores=cores)

            # execution_settings = ExecutionSettings()
            # Create workflow
            workflow_api = api.workflow(
                snakefile=snakefile,
                workdir=workdir,
                resource_settings=resource_settings,
                config_settings=config_settings,
                deployment_settings=deployment_settings,
            )

            # Create DAG settings
            dag_settings = DAGSettings(targets=targets)

            # Create DAG
            dag_api = workflow_api.dag(dag_settings=dag_settings)

            # Check if we should unlock instead of execute
            if unlock:
                print("Unlocking workflow directory...")
                dag_api.unlock()
                print("\n✓ Workflow unlocked successfully!")
                print("You can now re-run the workflow.")
            else:
                # Execute the workflow with resource settings
                print("Executing workflow...\n")
                result = dag_api.execute_workflow()

                # Report results
                print("Displaying result of simulation: \n")
                print(result)
                print("\nWorkflow completed successfully!")

    except Exception as e:
        action = "unlock" if unlock else "workflow"
        print(f"\n[ERROR] Failed to {action}: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
