import logging

import typer

from otcli.bootstrap import config
from otcli.domain.workdir import setup_working_directory
from otcli.infrastructure.backup import backup_odoo

logger = logging.getLogger(__name__)


def backup_odoo_instance(with_filestore: bool) -> None:
    client_to_backup = config.client_name

    typer.echo(f"Iniciando proceso de backup para el cliente: '{client_to_backup}'")
    setup_working_directory()
    backup_odoo(with_filestore=with_filestore)
    typer.echo(f"Proceso de backup completado para el cliente: '{client_to_backup}'")
