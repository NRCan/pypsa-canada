#!/usr/bin/env python3
"""
CLI script to generate DAG visualizations for the Snakemake workflow.
"""

import logging
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import click

os.environ.pop("SNAKEMAKE_OUTPUT_CACHE", None)  # no cache location => cache unused


@click.command()
@click.option(
    "-f",
    "--file",
    required=True,
    help="Pre-configured simulation file to use for DAG generation",
)
@click.option(
    "-o",
    "--output",
    default="dag",
    help="Output filename (without extension, default: 'dag')",
)
@click.option(
    "--format",
    type=click.Choice(["pdf", "png", "svg", "dot"], case_sensitive=False),
    default="pdf",
    help="Output format (default: pdf)",
)
@click.option(
    "--rulegraph",
    is_flag=True,
    default=False,
    help="Generate simplified rule graph instead of full DAG",
)
@click.option(
    "--data-folder",
    type=click.Path(exists=True),
    default=None,
    help="Path to custom data folder (default: current working directory)",
)
@click.option(
    "-t",
    "--targets",
    help="Target rule(s) to generate DAG for",
    multiple=True,
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Debug mode on/off (default: false)",
)
def dag(
    file: str,
    output: str,
    format: str,
    rulegraph: bool,
    data_folder: str | None = None,
    targets: tuple = (),
    debug: bool = False,
):
    """Generate DAG visualization for the Snakemake workflow."""

    # Configure logging level
    log_level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Set PYPSA_CUSTOM_DATA_FOLDER environment variable
    if data_folder is None:
        data_folder = str(Path.cwd())
    os.environ["PYPSA_CUSTOM_DATA_FOLDER"] = data_folder
    print(f"PYPSA_CUSTOM_DATA_FOLDER set to: {data_folder}")

    wf_root = files("pypsa_canada.workflow")
    snakefile = Path(str(wf_root.joinpath("Snakefile")))
    workdir = Path.cwd()

    # File
    configfile = workdir / file

    # Check if config file exists
    if not configfile.exists():
        print(f"Error: Config file not found at {configfile}")
        sys.exit(1)

    print(f"Using config: {configfile}")

    # Check if Snakefile exists
    if not snakefile.exists():
        print(f"Error: Snakefile not found at {snakefile}")
        sys.exit(1)

    print(f"Generating {'rulegraph' if rulegraph else 'DAG'} from: {workdir}")
    print(f"Using Snakefile: {snakefile}")

    output_file = f"{output}.{format}"
    print(f"Output: {output_file}\n")

    # Build the Snakemake command
    graph_type = "--rulegraph" if rulegraph else "--dag"

    cmd = [
        "snakemake",
        "-s",
        str(snakefile),
        "--configfile",
        str(configfile),
        "-d",
        str(workdir),
        graph_type,
    ]

    # Add targets if specified
    if targets:
        cmd.extend(targets)

    if debug:
        print(f"Running command: {' '.join(cmd)}\n")

    try:
        # Run snakemake to get DOT content
        print("Generating graph...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
        )

        dot_content = result.stdout

        if not dot_content or not dot_content.strip():
            print(
                "[ERROR] No DAG content generated. Check your workflow configuration."
            )
            if result.stderr:
                print(f"Stderr: {result.stderr}")
            sys.exit(1)

        # Save or convert the output
        if format == "dot":
            # Save DOT file directly
            with open(output_file, "w") as f:
                f.write(dot_content)
            print(f"✓ DOT file saved to: {output_file}")
        else:
            # Convert using graphviz
            try:
                print(f"Converting to {format.upper()} format...")
                process = subprocess.Popen(
                    ["dot", f"-T{format}", "-o", output_file],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                stdout, stderr = process.communicate(input=dot_content)

                if process.returncode != 0:
                    print(f"\n[ERROR] Graphviz failed: {stderr}")
                    print("\nTip: Make sure Graphviz is installed:")
                    print(
                        "  - Windows: choco install graphviz or download from https://graphviz.org/download/"
                    )
                    print("  - Linux: sudo apt-get install graphviz")
                    print("  - macOS: brew install graphviz")
                    print(
                        "\nAlternatively, save as DOT format: pypsa_canada dag -f your_config.yaml --format=dot"
                    )
                    sys.exit(1)

                print(
                    f"✓ {'Rulegraph' if rulegraph else 'DAG'} visualization saved to: {output_file}"
                )

            except FileNotFoundError:
                print("\n[ERROR] Graphviz 'dot' command not found!")
                print("\nPlease install Graphviz:")
                print(
                    "  - Windows: choco install graphviz or download from https://graphviz.org/download/"
                )
                print("  - Linux: sudo apt-get install graphviz")
                print("  - macOS: brew install graphviz")
                print(
                    "\nAlternatively, save as DOT format: pypsa_canada dag -f your_config.yaml --format=dot"
                )
                sys.exit(1)

    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Snakemake command failed with exit code {e.returncode}")
        if e.stdout:
            print(f"\nStdout:\n{e.stdout}")
        if e.stderr:
            print(f"\nStderr:\n{e.stderr}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] DAG generation failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
