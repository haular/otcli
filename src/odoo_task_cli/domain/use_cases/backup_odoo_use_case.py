import logging

import typer
from odoo_task_cli.app_config import config
from odoo_task_cli.domain.utils import setup_working_directory
from odoo_task_cli.infrastructure.db_client import backup_odoo

logger = logging.getLogger(__name__)


def backup_odoo_instance(with_filestore: bool) -> None:
    setup_working_directory()
    typer.echo("Initiating Odoo backup process.")
    backup_odoo(with_filestore=with_filestore)
    typer.echo("Odoo backup process completed successfully.")
