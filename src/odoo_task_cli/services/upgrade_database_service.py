import logging

import typer

from odoo_task_cli.config import config
from odoo_task_cli.infrastructure.odoo_client import run_upgrade, check_existing_upgrade

logger = logging.getLogger(__name__)


def upgrade_database(backup_file: str) -> str:
    if config.get("remote_backup_enabled", False):
        typer.echo("❌ Upgrade no está implementado para clientes remotos.")
        return backup_file
    
    if check_existing_upgrade(backup_file) and typer.confirm('Upgraded file found. Do you want to reuse it?', default=True):
        typer.echo('Reusing existing upgraded file')
        return 'upgraded.zip'
    return run_upgrade(backup_file)
