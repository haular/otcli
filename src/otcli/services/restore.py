"""Orchestrates the interactive restore flow for Odoo backups."""

import glob
import logging
import os

import typer

from otcli.bootstrap import config
from otcli.domain.exceptions import OdooCLIError
from otcli.infrastructure.odoo_http import (
    check_connection,
    drop_database,
    get_database_list,
    restore_database,
)
from otcli.infrastructure.restore import restore_database_from_container

logger = logging.getLogger(__name__)


def _select_backup_file() -> str | None:
    """Prompt the user to pick a ``.zip`` from ``config.client_backup_dir``.

    Returns the selected absolute path or ``None`` if the directory contains
    no backups.
    """
    backup_dir = config.client_backup_dir
    zip_files = sorted(glob.glob(os.path.join(backup_dir, '*.zip')))

    if not zip_files:
        typer.echo(f'No .zip backup files found in {backup_dir}.')
        return None

    typer.echo(f'Found {len(zip_files)} backup files in {backup_dir}:')
    for i, zip_file in enumerate(zip_files, 1):
        typer.echo(f'  {i}: {os.path.basename(zip_file)}')

    while True:
        try:
            choice = typer.prompt('Select a backup file to restore (enter number)', type=int)
        except ValueError:
            typer.echo('Invalid input. Please enter a number.')
            continue
        index = choice - 1
        if 0 <= index < len(zip_files):
            return zip_files[index]
        typer.echo('Invalid selection. Please enter a valid number.')


def _restore_via_curl(backup_file: str) -> None:
    """Restore using Odoo's HTTP /web/database/restore endpoint."""
    if not check_connection():
        logger.error('Odoo server is not running. Please start the server and try again.')
        raise OdooCLIError('Odoo server is not running. Please start the server and try again.')

    db_list = get_database_list()
    odoo_db_name = config.db_name

    if odoo_db_name in db_list:
        if not typer.confirm(
            f'Database {odoo_db_name} already exists. Do you want to drop and recreate it?',
            default=True,
        ):
            return
        drop_database()

    restore_database(backup_file)


def _prompt_restore_method() -> str:
    """Ask the user for the restoration method. Returns 'd' or 'c'."""
    while True:
        choice = typer.prompt(
            'Select restoration method: (C)URL or (D)ocker container? [C/D] (Default: D)',
            default='D',
        ).lower()
        if choice in ('', 'd'):
            return 'd'
        if choice == 'c':
            return 'c'
        typer.echo("Invalid restoration method. Please choose 'C' for CURL or 'D' for Docker container.")


def restore_odoo_database() -> None:
    """Interactive entry point used by the ``restore`` CLI command."""
    selected_backup_file = _select_backup_file()
    if selected_backup_file is None:
        return

    method = _prompt_restore_method()
    if method == 'd':
        restore_database_from_container(selected_backup_file)
    else:
        _restore_via_curl(selected_backup_file)
