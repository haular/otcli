import logging

import typer

from odoo_task_cli.config import config
from odoo_task_cli.domain.utils import setup_working_directory
from odoo_task_cli.infrastructure.db_client import backup_odoo
from odoo_task_cli.infrastructure.ssh_client import backup_remote_database

logger = logging.getLogger(__name__)


def backup_odoo_instance(with_filestore: bool) -> None:
    client_to_backup = config.client_name

    typer.echo(f"Iniciando proceso de backup para el cliente: '{client_to_backup}'")
    
    if config.get("remote_backup_enabled", False):
        typer.echo("Realizando backup remoto...")
        backup_remote_database(with_filestore=with_filestore)
    else:
        typer.echo("Realizando backup local...")
        setup_working_directory()
        backup_odoo(with_filestore=with_filestore)
    
    typer.echo(f"Proceso de backup completado para el cliente: '{client_to_backup}'")
