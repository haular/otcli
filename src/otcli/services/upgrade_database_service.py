import logging

import typer

from otcli.infrastructure.odoo_client import check_existing_upgrade, run_upgrade

logger = logging.getLogger(__name__)


def upgrade_database(backup_file: str) -> str:
    if check_existing_upgrade(backup_file) and typer.confirm('Upgraded file found. Do you want to reuse it?', default=True):
        typer.echo('Reusing existing upgraded file')
        return 'upgraded.zip'
    return run_upgrade(backup_file)
