import logging

import click

from pypsa_canada.cli.dag import dag
from pypsa_canada.cli.workflow import run

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """PyDSS commands"""


cli.add_command(run)
cli.add_command(dag)


if __name__ == "__main__":
    cli()
