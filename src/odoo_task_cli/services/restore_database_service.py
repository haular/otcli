import glob
import logging
import os

import typer

from odoo_task_cli.config import config
from odoo_task_cli.domain.exceptions import OdooCLIError
from odoo_task_cli.infrastructure.odoo_client import (
    check_connection,
    drop_database,
    get_database_list,
    restore_database,
    restore_database_from_container,
)

logger = logging.getLogger(__name__)


def restore_odoo_database() -> None:
    backup_dir = config.client_backup_dir
    zip_files = glob.glob(os.path.join(backup_dir, '*.zip'))

    if not zip_files:
        typer.echo(f'No .zip backup files found in {backup_dir}.')
        return

    typer.echo(f'Found {len(zip_files)} backup files in {backup_dir}:')
    for i, zip_file in enumerate(zip_files, 1):
        typer.echo(f'  {i}: {os.path.basename(zip_file)}')

    while True:
        try:
            choice = typer.prompt('Select a backup file to restore (enter number)', type=int)
            index = int(choice) - 1
            if 0 <= index < len(zip_files):
                selected_backup_file = zip_files[index]
                break
            typer.echo('Invalid selection. Please enter a valid number.')
        except ValueError:
            typer.echo('Invalid input. Please enter a number.')

    while True:
        restore_method = typer.prompt(
            'Select restoration method: (C)URL or (D)ocker container? [C/D] (Default: D)', default='D'
        ).lower()
        if restore_method == 'd' or restore_method == '':
            restore_database_from_container(selected_backup_file)
            break
        if restore_method == 'c':
            # Check Odoo connection
            if not check_connection():
                logger.error('Odoo server is not running. Please start the server and try again.')
                raise OdooCLIError('Odoo server is not running. Please start the server and try again.')
            # Get a database list
            db_list = get_database_list()
            # Get the database name from configuration
            odoo_db_name = config.db_name
            # Restore database
            if odoo_db_name in db_list:
                if typer.confirm(
                    f'Database {odoo_db_name} already exists. Do you want to drop and recreate it?', default=True
                ):
                    drop_database()
                    restore_database(selected_backup_file)
            else:
                restore_database(selected_backup_file)
            break
        typer.echo("Invalid restoration method. Please choose 'C' for CURL or 'D' for Docker container.")
