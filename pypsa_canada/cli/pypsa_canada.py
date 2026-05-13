import logging

import click

from pypsa_canada.cli.dag import dag
from pypsa_canada.cli.export_idea import export_idea
from pypsa_canada.cli.postprocess_summary import generate_postprocess_summary
from pypsa_canada.cli.workflow import run

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """PyDSS commands"""


cli.add_command(run)
cli.add_command(dag)
cli.add_command(generate_postprocess_summary)
cli.add_command(export_idea)


if __name__ == "__main__":
    cli()
